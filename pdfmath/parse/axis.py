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

from ..fonts.symbols import NEUTRAL_DELIMITERS, Role
from ..fonts.mathparams import params_for
from .context import ParseContext
from .units import Unit

CENTRED_ROLES = (Role.LARGE_OP, Role.DELIM_OPEN, Role.DELIM_CLOSE, Role.DELIM_PIECE)


def is_centred(unit: Unit) -> bool:
    """Would TeX have centred this box on the maths axis?

    Large operators and every delimiter ``var_delimiter`` produced.  Neutral fences --
    ``|`` and ``\\|`` -- have to be named explicitly: they carry an Ord atom class, so
    the role alone does not identify them, and a tall one is as much a ``\\left``
    delimiter as a bracket is.
    """
    if unit.role in CENTRED_ROLES:
        return True
    sym = unit.symbol
    return sym is not None and sym.base in NEUTRAL_DELIMITERS


def shift_of(unit: Unit, ctx: ParseContext) -> float:
    """How far below the line's baseline this box's own baseline was placed.

    ``axis_height`` is read from the family-2 font *at the current size*, so a fence
    inside a superscript is centred on an axis 0.7 of the height of the outer one.  A
    unit whose size differs from the context's is measured at its own size; getting this
    wrong pushes a script-size delimiter far enough down to be read as a subscript.
    """
    axis = ctx.params.axis_height
    if abs(unit.size - ctx.size) > ctx.eps and ctx.size > 0:
        axis = params_for(ctx.style, ctx.text_size, size=unit.size).axis_height
    return 0.5 * (unit.height - unit.depth) - axis


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
        if u.axis_normalised or not is_centred(u):
            out.append(u)
            continue
        s = shift_of(u, ctx)
        out.append(replace(u, baseline=u.baseline + s, height=u.height - s,
                           depth=u.depth + s, is_char=False, axis_normalised=True))
    return out
