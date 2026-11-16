"""Helpers for animating widget offsets in cells."""

from textual.css.scalar import Scalar, ScalarOffset, Unit


def cells_offset(x: int, y: int = 0) -> ScalarOffset:
    """Offset in cells, in the form the Textual animator accepts for the offset style."""
    return ScalarOffset(Scalar(x, Unit.CELLS, Unit.CELLS), Scalar(y, Unit.CELLS, Unit.CELLS))
