"""PDF font resource -> TeX font identity.

A PDF gives us a name like ``FFANCX+CMMI10``.  That string carries, for a TeX document,
almost everything we need: the family (``cmmi`` = math italic), the design size (10 pt),
the encoding (TeX math italic), the TFM to consult (``cmmi10.tfm``), and the MathML
``mathvariant`` the glyphs should be reported with.

Recognising the family is what lets us prefer TeX evidence over ToUnicode.  When we do
not recognise it we say so, and the extraction degrades to whatever the PDF's own Unicode
metadata offers, flagged as such.
"""

from __future__ import annotations

import re
from dataclasses import dataclass
from functools import lru_cache
from typing import Optional

from .data.tex_encodings import ENCODINGS

#: A subset prefix is exactly six uppercase letters and a '+'.
_SUBSET_RE = re.compile(r"^[A-Z]{6}\+")

#: family stem -> (encoding scheme, mathvariant, TFM stem, human description)
#  The TFM stem is the family name; the design size is appended by the caller.
_FAMILIES: dict[str, tuple[str, str, str, str]] = {
    # --- Computer Modern, text ---
    "cmr":     ("OT1",   "normal",      "cmr",     "CM Roman"),
    "cmb":     ("OT1",   "bold",        "cmb",     "CM Bold"),
    "cmbx":    ("OT1",   "bold",        "cmbx",    "CM Bold Extended"),
    "cmsl":    ("OT1",   "italic",      "cmsl",    "CM Slanted"),
    "cmbxsl":  ("OT1",   "bold-italic", "cmbxsl",  "CM Bold Slanted"),
    "cmti":    ("CMTI",  "italic",      "cmti",    "CM Text Italic"),
    "cmbxti":  ("CMTI",  "bold-italic", "cmbxti",  "CM Bold Italic"),
    "cmcsc":   ("OT1",   "normal",      "cmcsc",   "CM Small Caps"),
    "cmss":    ("CMSS",  "sans-serif",  "cmss",    "CM Sans"),
    "cmssbx":  ("CMSS",  "bold-sans-serif", "cmssbx", "CM Sans Bold"),
    "cmssi":   ("CMSS",  "sans-serif-italic", "cmssi", "CM Sans Italic"),
    "cmssdc":  ("CMSS",  "sans-serif",  "cmssdc",  "CM Sans Demi"),
    "cmtt":    ("OT1TT", "monospace",   "cmtt",    "CM Typewriter"),
    "cmsltt":  ("OT1TT", "monospace",   "cmsltt",  "CM Slanted Typewriter"),
    "cmitt":   ("OT1TT", "monospace",   "cmitt",   "CM Italic Typewriter"),
    "cmvtt":   ("OT1TT", "monospace",   "cmvtt",   "CM Variable Typewriter"),
    "cmu":     ("CMTI",  "italic",      "cmu",     "CM Unslanted Italic"),
    "cmdunh":  ("OT1",   "normal",      "cmdunh",  "CM Dunhill"),
    "cmff":    ("OT1",   "normal",      "cmff",    "CM Funny"),
    "cmfi":    ("CMTI",  "italic",      "cmfi",    "CM Funny Italic"),
    "cmfib":   ("OT1",   "normal",      "cmfib",   "CM Fibonacci"),
    "cminch":  ("OT1",   "normal",      "cminch",  "CM Inch"),
    "cmtex":   ("OT1TT", "monospace",   "cmtex",   "CM TeX extended"),
    # --- Computer Modern, math ---
    "cmmi":    ("OML",   "italic",      "cmmi",    "CM Math Italic"),
    "cmmib":   ("OML",   "bold-italic", "cmmib",   "CM Math Italic Bold"),
    "cmsy":    ("OMS",   "normal",      "cmsy",    "CM Math Symbols"),
    "cmbsy":   ("OMS",   "bold",        "cmbsy",   "CM Math Symbols Bold"),
    "cmex":    ("OMX",   "normal",      "cmex",    "CM Math Extension"),
    # --- AMS ---
    "msam":    ("AMSA",  "normal",      "msam",    "AMS Symbols A"),
    "msbm":    ("AMSB",  "double-struck", "msbm",  "AMS Symbols B"),
    "lasy":    ("LASY",  "normal",      "lasy",    "LaTeX Symbols"),
    "lasyb":   ("LASY",  "bold",        "lasyb",   "LaTeX Symbols Bold"),
    "eufm":    ("EUFRAK", "fraktur",    "eufm",    "Euler Fraktur"),
    "eufb":    ("EUFRAK", "bold-fraktur", "eufb",  "Euler Fraktur Bold"),
    "eusm":    ("OMS",   "script",      "eusm",    "Euler Script"),
    "eusb":    ("OMS",   "bold-script", "eusb",    "Euler Script Bold"),
    "euex":    ("OMX",   "normal",      "euex",    "Euler Extension"),
    "cmmi_b":  ("OML",   "bold-italic", "cmmib",   "CM Math Italic Bold"),
    # --- Latin Modern (short forms; long forms are normalised onto these) ---
    "lmr":     ("OT1",   "normal",      "lmr",     "Latin Modern Roman"),
    "lmbx":    ("OT1",   "bold",        "lmbx",    "Latin Modern Bold"),
    "lmri":    ("CMTI",  "italic",      "lmri",    "Latin Modern Italic"),
    "lmsl":    ("OT1",   "italic",      "lmsl",    "Latin Modern Slanted"),
    "lmss":    ("CMSS",  "sans-serif",  "lmss",    "Latin Modern Sans"),
    "lmtt":    ("OT1TT", "monospace",   "lmtt",    "Latin Modern Mono"),
    "lmmi":    ("OML",   "italic",      "lmmi",    "Latin Modern Math Italic"),
    "lmmib":   ("OML",   "bold-italic", "lmmib",   "Latin Modern Math Italic Bold"),
    "lmsy":    ("OMS",   "normal",      "lmsy",    "Latin Modern Math Symbols"),
    "lmbsy":   ("OMS",   "bold",        "lmbsy",   "Latin Modern Math Symbols Bold"),
    "lmex":    ("OMX",   "normal",      "lmex",    "Latin Modern Math Extension"),
}

#: Latin Modern's Type 1 fonts often appear under long PostScript names.
_LM_LONG = {
    "lmroman": "lmr", "lmromanslant": "lmsl", "lmromandemi": "lmbx",
    "lmsans": "lmss", "lmsansquot": "lmss", "lmmono": "lmtt",
    "lmmonoslant": "lmtt", "lmmonoprop": "lmtt",
    "lmmathitalic": "lmmi", "lmmathsymbols": "lmsy",
    "lmmathextension": "lmex", "lmromancaps": "lmr", "lmromanunsl": "lmr",
    "lmromandunh": "lmr",
}

#: Fonts whose A-Z slots are calligraphic rather than upright Latin capitals.
_SCRIPT_CAPS_FAMILIES = {"cmsy", "cmbsy", "lmsy", "lmbsy"}


@dataclass(frozen=True)
class FontIdentity:
    """What we were able to work out about a PDF font resource."""

    pdf_name: str                  # the /BaseFont value, subset prefix and all
    base_name: str                 # subset prefix stripped, e.g. "CMMI10"
    family: Optional[str]          # "cmmi", or None if unrecognised
    design_size: Optional[float]   # the size baked into the name, e.g. 10.0
    encoding: Optional[str]        # key into ENCODINGS
    mathvariant: str               # MathML mathvariant for ordinary letters
    tfm_name: Optional[str]        # "cmmi10", ready for load_tfm()
    description: str

    @property
    def is_tex_font(self) -> bool:
        return self.family is not None

    @property
    def is_math_font(self) -> bool:
        return self.encoding in ("OML", "OMS", "OMX", "AMSA", "AMSB", "LASY")

    @property
    def is_extension_font(self) -> bool:
        return self.encoding == "OMX"

    @property
    def has_script_capitals(self) -> bool:
        return self.family in _SCRIPT_CAPS_FAMILIES


_NAME_RE = re.compile(r"^(?P<stem>[a-z]+?)(?P<size>\d+(?:\.\d+)?)?$")
_LM_LONG_RE = re.compile(
    r"^(?P<stem>lm[a-z]+?)(?P<size>\d+)?(?:-(?P<shape>[a-z]+))?$"
)


def strip_subset(name: str) -> str:
    """``FFANCX+CMMI10`` -> ``CMMI10``."""
    name = name.lstrip("/")
    return _SUBSET_RE.sub("", name)


@lru_cache(maxsize=1024)
def identify(pdf_font_name: str) -> FontIdentity:
    """Classify a PDF font name.  Always returns; unknown fonts get ``family=None``."""
    base = strip_subset(pdf_font_name)
    low = base.lower()

    # Latin Modern long form, e.g. "LMMathItalic10-Regular" / "LMRoman10-Bold"
    m = _LM_LONG_RE.match(low)
    if m and m.group("stem") in _LM_LONG:
        stem = _LM_LONG[m.group("stem")]
        shape = m.group("shape") or ""
        if shape in ("bold", "demi") and stem == "lmr":
            stem = "lmbx"
        elif shape in ("italic", "oblique") and stem == "lmr":
            stem = "lmri"
        elif shape == "bold" and stem == "lmmi":
            stem = "lmmib"
        elif shape == "bold" and stem == "lmsy":
            stem = "lmbsy"
        size = float(m.group("size")) if m.group("size") else 10.0
        enc, variant, tfm, desc = _FAMILIES[stem]
        return FontIdentity(pdf_font_name, base, stem, size, enc, variant,
                            f"{tfm}{int(size) if size == int(size) else size}", desc)

    m = _NAME_RE.match(low)
    if m:
        stem, size_s = m.group("stem"), m.group("size")
        if stem in _FAMILIES:
            enc, variant, tfm, desc = _FAMILIES[stem]
            size = float(size_s) if size_s else None
            tfm_name = f"{tfm}{size_s}" if size_s else tfm
            return FontIdentity(pdf_font_name, base, stem, size, enc, variant,
                                tfm_name, desc)

    return FontIdentity(pdf_font_name, base, None, None, None, "normal", None,
                        f"unrecognised font {base!r}")


def glyph_name(font: FontIdentity, code: int) -> Optional[str]:
    """The TeX glyph name for ``code`` in ``font``, or ``None`` if we cannot say.

    Note that this deliberately consults the *font family's* encoding rather than the
    PDF's ToUnicode map.  For pdfTeX output with no ``/Encoding`` entry -- the normal
    case -- the built-in encoding of the embedded Type 1 program governs, and that is
    exactly the table we hold here.
    """
    if font.encoding is None:
        return None
    table = ENCODINGS.get(font.encoding)
    if table is None:
        return None
    # TeX fonts occupy codes 0..127; AFM files list higher duplicate slots we ignore.
    return table.get(code) if 0 <= code <= 127 else None
