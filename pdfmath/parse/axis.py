"""Undoing TeX's axis centring.

Two constructions shift a box off the line's baseline so that its middle lands on the
maths axis: ``make_op`` for large operators, and ``var_delimiter`` for every delimiter
produced by ``\\left`` / ``\\right`` / ``\\big`` and friends.  In both cases the shift is

    shift = (height - depth) / 2 - axis_height

applied *downwards*, and everything downstream in TeX -- ``make_scripts`` above all --
then works with the unshifted box.  A decompiler that does not undo it will read a
summation sign's drawn baseline as the line's baseline and misjudge everything after it.

The subtlety is that an ordinary ``(`` typed as a character is *not* centred, while
``\\left(`` is, even at the smallest size where both draw the same cmr glyph.  We do not
have to guess: the shift is a known quantity, so we test both hypotheses against the
baseline of the material that certainly is not centred, and take whichever fits.
"""

from __future__ import annotations

from dataclasses import replace
from typing import Optional, Sequence

from ..fonts.symbols import Role
from .context import ParseContext
from .units import Unit

CENTRED_ROLES = (Role.LARGE_OP, Role.DELIM_OPEN, Role.DELIM_CLOSE, Role.DELIM_PIECE)


def shift_of(unit: Unit, ctx: ParseContext) -> float:
    """How far below the line's baseline this box's own baseline was placed."""
    return 0.5 * (unit.height - unit.depth) - ctx.params.axis_height


def normalise(units: list[Unit], ctx: ParseContext) -> list[Unit]:
    """Move axis-centred boxes back onto the line's baseline.

    No hypothesis test is needed, and it is worth saying why.  A delimiter typed as an
    ordinary character is *not* centred, while ``\\left(`` is -- but Computer Modern's
    text-size delimiters are cut so that ``(height - depth) / 2`` is exactly
    ``axis_height``: for cmr's ``(`` and ``[`` and cmsy's ``{`` and ``|`` the shift comes
    out at precisely zero.  Applying the correction unconditionally is therefore a no-op
    on the ambiguous cases and correct on all the others, and the enlarged cmex variants
    can only have come from ``\\left`` / ``\\big`` in the first place.
    """
    out: list[Unit] = []
    for u in units:
        if u.axis_normalised or u.role not in CENTRED_ROLES:
            out.append(u)
            continue
        s = shift_of(u, ctx)
        out.append(replace(u, baseline=u.baseline + s, height=u.height - s,
                           depth=u.depth + s, is_char=False, axis_normalised=True))
    return out
