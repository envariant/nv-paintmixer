from __future__ import annotations

import pytest

from paintmixer.domain import PaintInfo
from tests.helpers import load_paints_csv


@pytest.fixture
def paints() -> dict[str, PaintInfo]:
    return load_paints_csv()
