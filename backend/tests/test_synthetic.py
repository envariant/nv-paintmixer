from __future__ import annotations

import numpy as np

from paintmixer.calibration.format import SampleType, Substrate
from paintmixer.calibration.synthetic import (
    POOL_IDS,
    STARTER_IDS,
    generate_calibration,
    render,
    synthetic_paints,
)
from paintmixer.colorsci import reflectance_to_lab


def test_generate_reproducible_and_complete() -> None:
    a, truth, plan = generate_calibration(synthetic_paints(), seed=3)
    b, _, _ = generate_calibration(synthetic_paints(), seed=3)
    assert [s.sample_id for s in a] == [s.sample_id for s in b]
    np.testing.assert_array_equal(a[10].reflectance, b[10].reflectance)
    assert {s.type for s in a} == set(SampleType)
    assert sum(s.holdout for s in a) > 0
    assert len(a) == plan.n_rows
    ids = {s.sample_id for s in a}
    for s in a:
        if s.type in (SampleType.TINT, SampleType.MIXTURE):
            other = s.drawdown_id + ("-B" if s.substrate == Substrate.WHITE else "-W")
            assert other in ids
    assert truth.ids == list(STARTER_IDS)


def test_noise_level() -> None:
    noisy, truth, _ = generate_calibration(synthetic_paints(), noise=0.002, weigh=False, seed=1)
    resid = []
    for s in noisy:
        if s.type in (SampleType.SUBSTRATE_WHITE, SampleType.SUBSTRATE_BLACK):
            continue
        clean = render(truth, s.components, s.substrate, s.effective_gap_um)
        resid.append(s.reflectance - clean)
    sd = float(np.std(np.concatenate(resid)))
    assert 0.0017 < sd < 0.0023
    spread = np.mean([s.spread for s in noisy if s.spread is not None])
    assert 0.002 < spread < 0.004  # per-reading sigma is 0.002*sqrt(3)


def test_paints_look_like_their_names() -> None:
    paints = synthetic_paints(POOL_IDS)
    from paintmixer.colorsci import KMModel

    m = KMModel(np.stack([p.K for p in paints]), np.stack([p.S for p in paints]))
    lab = {
        p.info.id: reflectance_to_lab(m.reflectance(np.eye(len(paints))[i]))
        for i, p in enumerate(paints)
    }
    # tints with white (20 % paint) to see hue
    tint = {}
    for i, p in enumerate(paints):
        c = np.zeros(len(paints))
        c[i], c[0] = 0.2, 0.8
        tint[p.info.id] = reflectance_to_lab(m.reflectance(c))
    assert lab["titanium-white"][0] > 90
    assert lab["carbon-black"][0] < 10
    assert tint["phthalo-blue"][2] < -20  # blue
    assert tint["quinacridone-magenta"][1] > 20  # red-ish
    assert tint["arylide-yellow"][2] > 40  # yellow
    assert tint["phthalo-green"][1] < -20  # green
