"""A reader for TeX Font Metric (.tfm) files.

This is the single most valuable input the project has.  A TFM file records exactly the
numbers TeX used when it typeset the page we are decompiling: per-glyph width, height,
depth and italic correction, plus the font-wide parameters that Appendix G of *The
TeXbook* refers to as sigma_1..sigma_22 (math symbol fonts) and xi_1..xi_13 (math
extension fonts).

Because the PDF was produced from these very numbers, a predicted position computed from
a TFM agrees with a measured position to within TeX's own rounding.  That converts a
heuristic ("the script looks about 60% of an em higher") into a residual we can measure.

File format: see `tftopl.web`, or Appendix F of *The TeXbook*.  All lengths are stored as
`fix_word`s -- 32-bit signed with 20 fractional bits -- and are in units of the design
size, except `slant`, which is a pure number.
"""

from __future__ import annotations

import os
import struct
import subprocess
from dataclasses import dataclass, field
from functools import lru_cache
from typing import Optional

NO_TAG, LIG_TAG, LIST_TAG, EXT_TAG = 0, 1, 2, 3


@dataclass(frozen=True)
class CharMetric:
    """Metrics of one character, in units of the design size."""

    code: int
    width: float
    height: float
    depth: float
    italic: float
    tag: int = NO_TAG
    remainder: int = 0

    @property
    def is_charlist(self) -> bool:
        """True if a larger variant of this glyph exists (``remainder`` is its code)."""
        return self.tag == LIST_TAG

    @property
    def is_extensible(self) -> bool:
        """True if this glyph is built from stacked pieces (see ``TfmFont.extensible``)."""
        return self.tag == EXT_TAG


@dataclass(frozen=True)
class Extensible:
    """An extensible recipe: a delimiter assembled from top / mid / bot / rep pieces.

    A code of 0 means "no such piece".  ``rep`` is repeated as often as needed.
    """

    top: int
    mid: int
    bot: int
    rep: int


# Appendix G names for the parameters of a math *symbol* font (family 2, e.g. cmsy10).
SIGMA_NAMES = [
    None, "slant", "space", "space_stretch", "space_shrink", "x_height", "quad",
    "extra_space", "num1", "num2", "num3", "denom1", "denom2", "sup1", "sup2", "sup3",
    "sub1", "sub2", "sup_drop", "sub_drop", "delim1", "delim2", "axis_height",
]

# ... and of a math *extension* font (family 3, e.g. cmex10).
XI_NAMES = [
    None, "slant", "space", "space_stretch", "space_shrink", "x_height", "quad",
    "extra_space", "default_rule_thickness", "big_op_spacing1", "big_op_spacing2",
    "big_op_spacing3", "big_op_spacing4", "big_op_spacing5",
]


class TfmError(Exception):
    pass


@dataclass
class TfmFont:
    """A parsed .tfm.  All lengths are in design-size units until scaled."""

    name: str
    checksum: int
    design_size: float                      # in points
    coding_scheme: str
    chars: dict[int, CharMetric] = field(default_factory=dict)
    params: list[float] = field(default_factory=list)   # 1-based; params[0] unused
    extensible: dict[int, Extensible] = field(default_factory=dict)
    path: Optional[str] = None

    # -- parameter access ---------------------------------------------------------

    def param(self, i: int, default: float = 0.0) -> float:
        """sigma_i / xi_i, in design-size units (except slant, a pure number)."""
        return self.params[i] if 0 < i < len(self.params) else default

    def named_param(self, name: str, default: float = 0.0) -> float:
        """Look a parameter up by its Appendix G name, e.g. ``"axis_height"``.

        Falls back through both naming schemes so ``x_height`` works on any font.
        """
        for table in (SIGMA_NAMES, XI_NAMES):
            if name in table:
                i = table.index(name)
                if i < len(self.params):
                    return self.params[i]
        return default

    @property
    def is_math_symbol_font(self) -> bool:
        return len(self.params) - 1 >= 22

    @property
    def is_math_extension_font(self) -> bool:
        return 13 <= len(self.params) - 1 < 22

    # -- glyph access -------------------------------------------------------------

    def get(self, code: int) -> Optional[CharMetric]:
        return self.chars.get(code)

    def charlist(self, code: int, limit: int = 32) -> list[int]:
        """The successively larger variants of ``code``, starting with ``code`` itself.

        TeX stores growable delimiters and the text/display forms of large operators as a
        linked list through the ``list_tag`` remainder.  Walking it tells us that, say,
        cmex10's `summationtext` and `summationdisplay` are the same operator at two
        sizes -- exactly the distinction we need in order not to report two symbols.
        """
        out, seen, cur = [], set(), code
        while cur is not None and cur not in seen and len(out) < limit:
            seen.add(cur)
            out.append(cur)
            cm = self.chars.get(cur)
            cur = cm.remainder if (cm and cm.is_charlist) else None
        return out

    def scaled(self, code: int, at_size: float) -> Optional[tuple[float, float, float, float]]:
        """(width, height, depth, italic) in points for this glyph set at ``at_size`` pt."""
        cm = self.chars.get(code)
        if cm is None:
            return None
        s = at_size
        return (cm.width * s, cm.height * s, cm.depth * s, cm.italic * s)


def _fix_word(raw: int) -> float:
    if raw & 0x80000000:
        raw -= 1 << 32
    return raw / (1 << 20)


def parse_tfm(data: bytes, name: str = "?", path: str | None = None) -> TfmFont:
    if len(data) < 24:
        raise TfmError(f"{name}: file too short ({len(data)} bytes)")
    lf, lh, bc, ec, nw, nh, nd, ni, nl, nk, ne, np = struct.unpack(">12H", data[:24])
    if not (bc - 1 <= ec <= 255):
        raise TfmError(f"{name}: implausible character range {bc}..{ec}")
    expected = 6 + lh + (ec - bc + 1) + nw + nh + nd + ni + nl + nk + ne + np
    if lf != expected:
        raise TfmError(f"{name}: header says lf={lf}, computed {expected}")
    if len(data) < lf * 4:
        raise TfmError(f"{name}: truncated ({len(data)} bytes, need {lf * 4})")

    words = struct.unpack(f">{lf}I", data[: lf * 4])
    p = 6

    header = words[p:p + lh]; p += lh
    checksum = header[0] if lh > 0 else 0
    design_size = _fix_word(header[1]) if lh > 1 else 10.0
    coding_scheme = ""
    if lh > 2:
        raw = b"".join(struct.pack(">I", w) for w in header[2:12])
        n = raw[0] if raw else 0
        coding_scheme = raw[1:1 + n].decode("ascii", "replace")

    n_chars = ec - bc + 1
    char_info = words[p:p + n_chars]; p += n_chars
    width = [_fix_word(w) for w in words[p:p + nw]]; p += nw
    height = [_fix_word(w) for w in words[p:p + nh]]; p += nh
    depth = [_fix_word(w) for w in words[p:p + nd]]; p += nd
    italic = [_fix_word(w) for w in words[p:p + ni]]; p += ni
    p += nl + nk                                       # lig/kern and kern programs
    exten = words[p:p + ne]; p += ne
    params = [0.0] + [_fix_word(w) for w in words[p:p + np]]

    chars: dict[int, CharMetric] = {}
    extensible: dict[int, Extensible] = {}
    for i, ci in enumerate(char_info):
        w_i = (ci >> 24) & 0xFF
        if w_i == 0:                                   # width index 0 means "not in font"
            continue
        h_i = (ci >> 20) & 0x0F
        d_i = (ci >> 16) & 0x0F
        it_i = (ci >> 10) & 0x3F
        tag = (ci >> 8) & 0x03
        rem = ci & 0xFF
        code = bc + i
        chars[code] = CharMetric(
            code=code,
            width=width[w_i] if w_i < nw else 0.0,
            height=height[h_i] if h_i < nh else 0.0,
            depth=depth[d_i] if d_i < nd else 0.0,
            italic=italic[it_i] if it_i < ni else 0.0,
            tag=tag,
            remainder=rem,
        )
        if tag == EXT_TAG and rem < ne:
            e = exten[rem]
            extensible[code] = Extensible(
                top=(e >> 24) & 0xFF, mid=(e >> 16) & 0xFF,
                bot=(e >> 8) & 0xFF, rep=e & 0xFF,
            )

    return TfmFont(
        name=name, checksum=checksum, design_size=design_size,
        coding_scheme=coding_scheme, chars=chars, params=params,
        extensible=extensible, path=path,
    )


@lru_cache(maxsize=512)
def kpsewhich(name: str) -> Optional[str]:
    """Ask the local TeX installation where a file lives.  ``None`` if there is none."""
    try:
        r = subprocess.run(["kpsewhich", name], capture_output=True, text=True, timeout=15)
    except (OSError, subprocess.SubprocessError):
        return None
    path = r.stdout.strip().splitlines()
    return path[0] if path and os.path.exists(path[0]) else None


@lru_cache(maxsize=512)
def load_tfm(font_name: str) -> Optional[TfmFont]:
    """Load ``<font_name>.tfm`` from the local TeX tree.  ``None`` if unavailable."""
    base = font_name.lower()
    path = kpsewhich(base + ".tfm")
    if path is None:
        return None
    try:
        with open(path, "rb") as fh:
            return parse_tfm(fh.read(), name=base, path=path)
    except (OSError, TfmError):
        return None
