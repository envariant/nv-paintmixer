"""Shared typing aliases."""

from __future__ import annotations

import numpy as np
from numpy.typing import ArrayLike, NDArray

FloatArray = NDArray[np.float64]
IntArray = NDArray[np.int64]
BoolArray = NDArray[np.bool_]

__all__ = ["ArrayLike", "BoolArray", "FloatArray", "IntArray"]
