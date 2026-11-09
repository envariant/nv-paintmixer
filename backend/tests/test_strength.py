from __future__ import annotations

import numpy as np
import pytest

from paintmixer.calibration.strength import relative_strength, tinting_strengths, with_relative
from paintmixer.calibration.synthetic import STARTER_IDS, synthetic_paints
from paintmixer.colorsci import KMModel


def _model(scale_k: dict[int, float] | None = None) -> KMModel:
    ps = synthetic_paints(STARTER_IDS)
    K = np.stack([p.K for p in ps])
    for i, f in (scale_k or {}).items():
        K[i] = K[i] * f
    return KMModel(K, np.stack([p.S for p in ps]))


def test_strengths_per_paint() -> None:
    st = tinting_strengths(_model(), list(STARTER_IDS), "titanium-white")
    assert "titanium-white" not in st and set(st) == set(STARTER_IDS[1:])
    blue = st["phthalo-blue"]
    assert 600 <= blue.peak_nm <= 650  # phthalo blue absorbs red
    assert 530 <= st["quinacridone-magenta"].peak_nm <= 560  # magenta absorbs green
    assert st["arylide-yellow"].peak_nm <= 470  # yellow absorbs blue
    assert blue.reduction_fraction == 0.1 and blue.reduction_hex.startswith("#")
    assert blue.reduction_ks == pytest.approx(float(blue.ks_spectrum.max()), rel=0.05)
    assert all(s.relative_pct is None for s in st.values())


def test_relative_strength_of_a_stronger_batch() -> None:
    ids = list(STARTER_IDS)
    ref = tinting_strengths(_model(), ids, "titanium-white")
    strong = tinting_strengths(_model({2: 1.5}), ids, "titanium-white")  # phthalo blue K x1.5
    rel = with_relative(strong, ref)
    assert rel["phthalo-blue"].relative_pct == pytest.approx(150, abs=3)
    assert rel["arylide-yellow"].relative_pct == pytest.approx(100, abs=1e-9)
    assert relative_strength(ref["phthalo-blue"], ref["phthalo-blue"]) == pytest.approx(100)


def test_unknown_white() -> None:
    with pytest.raises(ValueError):
        tinting_strengths(_model(), list(STARTER_IDS), "zinc-white")
