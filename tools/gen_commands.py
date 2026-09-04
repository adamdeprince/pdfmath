"""Generate pdfmath/latex/data/tex_commands.py from LaTeX's own symbol tables.

``fontmath.ltx`` and ``amssymb.sty`` declare every standard math symbol as a command
paired with a symbol font, a slot, and an atom class::

    \\DeclareMathSymbol{\\alpha}{\\mathalpha}{letters}{"0B}
    \\DeclareMathDelimiter{\\langle}{\\mathopen}{symbols}{"68}{largesymbols}{"0A}
    \\DeclareMathAccent{\\hat}{\\mathalpha}{operators}{"5E}

Run backwards, that is the map from a glyph we found in a PDF to the command that puts it
back -- which is what the round-trip oracle needs.  Taking it from LaTeX rather than
writing it by hand means it is complete and cannot drift.

The atom class has to come along.  cmsy slot 0x6A is declared twice, as ``\\mid`` (a
relation) and as ``\\vert`` (ordinary), and they are not interchangeable: emitting the
wrong one changes the inter-atom glue and the recompiled page no longer matches.

Run with:  python tools/gen_commands.py
"""
import os
import pprint
import re
import subprocess
import sys

#: LaTeX symbol-font name -> the encoding key in pdfmath.fonts.data.tex_encodings
FONTS = {"operators": "OT1", "letters": "OML", "symbols": "OMS",
         "largesymbols": "OMX", "AMSa": "AMSA", "AMSb": "AMSB"}

#: LaTeX math class -> the short name used by pdfmath.fonts.symbols.AtomClass
CLASSES = {"ord": "Ord", "alpha": "Ord", "op": "Op", "bin": "Bin", "rel": "Rel",
           "open": "Open", "close": "Close", "punct": "Punct", "inner": "Inner"}

SOURCES = ["fontmath.ltx", "amssymb.sty", "amsfonts.sty"]

_SLOT = r'(?:"([0-9A-Fa-f]+)|`\\?(.)|(\d+))'
_ARG = r'\{\s*(\\?[^}\s]+)\s*\}'
_SYMBOL = re.compile(r'\\DeclareMathSymbol\s*' + _ARG + r'\s*\{\s*\\math(\w+)\s*\}\s*'
                     r'\{\s*(\w+)\s*\}\s*\{\s*' + _SLOT)
_DELIM = re.compile(r'\\DeclareMathDelimiter\s*' + _ARG + r'\s*\{\s*\\math(\w+)\s*\}\s*'
                    r'\{\s*(\w+)\s*\}\s*\{\s*' + _SLOT +
                    r'\s*\}\s*\{\s*(\w+)\s*\}\s*\{\s*' + _SLOT)
_ACCENT = re.compile(r'\\DeclareMathAccent\s*' + _ARG + r'\s*\{\s*\\math(\w+)\s*\}\s*'
                     r'\{\s*(\w+)\s*\}\s*\{\s*' + _SLOT)


def kpse(name):
    try:
        r = subprocess.run(["kpsewhich", name], capture_output=True, text=True, timeout=20)
    except Exception:
        return None
    p = r.stdout.strip()
    return p if p and os.path.exists(p) else None


def source_text(path):
    """File contents with comments stripped and lines joined.

    LaTeX splits a \\DeclareMathDelimiter over several lines with %-comments between the
    arguments, so the declarations cannot be matched line by line.
    """
    out = []
    for line in open(path, errors="replace"):
        out.append(re.sub(r'(?<!\\)%.*$', "", line))
    return re.sub(r"\s+", " ", "".join(out))


def slot(hexv, chrv, decv):
    if hexv is not None:
        return int(hexv, 16)
    if chrv is not None:
        return ord(chrv)
    return int(decv)


def main():
    # glyph name -> {atom class: set of commands}
    found: dict[tuple[str, int], dict[str, set]] = {}
    accents: dict[tuple[str, int], str] = {}

    def record(font, h, c, d, cls, cmd):
        if font not in FONTS or cls not in CLASSES:
            return
        key = (FONTS[font], slot(h, c, d))
        found.setdefault(key, {}).setdefault(CLASSES[cls], set()).add(cmd)

    for name in SOURCES:
        path = kpse(name)
        if not path:
            print(f"WARNING: {name} not found", file=sys.stderr)
            continue
        text = source_text(path)
        for m in _SYMBOL.finditer(text):
            cmd, cls, font, h, c, d = m.groups()
            record(font, h, c, d, cls, cmd)
        for m in _DELIM.finditer(text):
            cmd, cls, f1, h1, c1, d1, f2, h2, c2, d2 = m.groups()
            record(f1, h1, c1, d1, cls, cmd)
            record(f2, h2, c2, d2, cls, cmd)
        for m in _ACCENT.finditer(text):
            cmd, cls, font, h, c, d = m.groups()
            if font in FONTS:
                accents[(FONTS[font], slot(h, c, d))] = cmd

    sys.path.insert(0, os.path.join(os.path.dirname(__file__), ".."))
    from pdfmath.fonts.data.tex_encodings import ENCODINGS
    from pdfmath.fonts.symbols import lookup

    def pick(cmds):
        """Canonical spelling: a control sequence over a bare character, then shortest."""
        return min(cmds, key=lambda c: (not c.startswith("\\"), len(c), c))

    # Keyed by (encoding, glyph name), not by name alone: msbm's blackboard-bold "k"
    # and cmmi's math-italic "k" carry the same glyph name in their AFMs, and a
    # name-only table would put \Bbbk where a variable belongs.
    by_glyph: dict[tuple[str, str], dict[str, str]] = {}
    for (enc, code), classes in sorted(found.items()):
        name = ENCODINGS.get(enc, {}).get(code)
        if not name or not (0 <= code <= 127):
            continue
        slot_map = by_glyph.setdefault((enc, name), {})
        for cls, cmds in classes.items():
            best = pick(cmds)
            if cls not in slot_map or pick({slot_map[cls], best}) == best:
                slot_map[cls] = best

    # The default is the spelling whose declared class matches the class we assign the
    # glyph; that is what keeps the inter-atom glue the same on the way back out.
    default: dict[tuple[str, str], str] = {}
    for key, classes in by_glyph.items():
        want = lookup(key[1]).atom.short
        default[key] = classes.get(want) or pick(set(classes.values()))

    accent_by_glyph = {}
    for (enc, code), cmd in sorted(accents.items()):
        name = ENCODINGS.get(enc, {}).get(code)
        if name and 0 <= code <= 127:
            accent_by_glyph[(enc, name)] = cmd

    dest = os.path.abspath(os.path.join(os.path.dirname(__file__), "..", "pdfmath",
                                        "latex", "data", "tex_commands.py"))
    pp = pprint.PrettyPrinter(indent=4, width=94)
    with open(dest, "w") as fh:
        fh.write('"""LaTeX commands by glyph name, generated by tools/gen_commands.py.\n\n')
        fh.write("Do not edit by hand.  Extracted from LaTeX's own \\\\DeclareMathSymbol,\n")
        fh.write("\\\\DeclareMathDelimiter and \\\\DeclareMathAccent declarations in\n")
        fh.write("fontmath.ltx and amssymb.sty.\n\n")
        fh.write("Keys are (encoding, glyph name): msbm's blackboard-bold \'k\' and cmmi's\n")
        fh.write("math-italic \'k\' share a glyph name, so the encoding has to be part of it.\n")
        fh.write("COMMAND_BY_GLYPH gives the canonical spelling for the atom class we\n")
        fh.write("assign the glyph; BY_CLASS keeps the alternatives, because cmsy 0x6A is\n")
        fh.write("both \\\\mid (a relation) and \\\\vert (ordinary) and the spacing differs.\n")
        fh.write('"""\n\n# fmt: off\nCOMMAND_BY_GLYPH = ')
        fh.write(pp.pformat(default))
        fh.write("\n\nBY_CLASS = ")
        fh.write(pp.pformat(by_glyph))
        fh.write("\n\nACCENT_BY_GLYPH = ")
        fh.write(pp.pformat(accent_by_glyph))
        fh.write("\n# fmt: on\n")
    print(f"{len(default)} symbols, {len(accent_by_glyph)} accents -> {dest}")


if __name__ == "__main__":
    main()
