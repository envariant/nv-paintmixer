"""Mix candidates that differ in kind (tags), their uncertainty, and the gamut margin."""

from __future__ import annotations

from collections.abc import Iterator

import numpy as np
import pytest
from fastapi.testclient import TestClient

from paintmixer.api.app import create_app
from paintmixer.calibration.accuracy import (
    UNDER_SAMPLED_FACTOR,
    mix_uncertainty,
    paint_quality,
)
from paintmixer.calibration.format import CalibrationSampleData, SampleType, Substrate
from paintmixer.colorsci.spectral import N_BANDS
from paintmixer.config import Settings
from paintmixer.demo import seed_demo
from paintmixer.domain import PaintRole
from paintmixer.solver.solve import Candidate, SolveOptions, Target, select_candidates, solve
from tests.solver_helpers import pool_model

API = "/api/v1"


def _cand(ids: list[str], de: float, cost: float, objective: float) -> Candidate:
    n = len(ids)
    return Candidate(
        rank=0,
        paint_ids=ids,
        fractions=[1 / n] * n,
        fractions_quantised=[1 / n] * n,
        volumes_ml=[100 / n] * n,
        masses_g=[100 / n] * n,
        predicted_spectrum=[],
        predicted_lab=[50.0, 0.0, 0.0],
        predicted_hex="#777777",
        de2000=de,
        de2000_continuous=de,
        cost=cost * 100,
        cost_per_ml=cost,
        metamerism={},
        dose_sensitivity=0.1,
        objective=objective,
        warnings=[],
    )


def test_select_candidates_roles_dedup_and_order() -> None:
    a = _cand(["w", "k", "c", "y"], de=0.2, cost=0.07, objective=1.0)  # closest
    b = _cand(["w", "k", "y"], de=0.25, cost=0.08, objective=1.1)  # fewest within the band
    d = _cand(["w", "k", "c", "m"], de=0.9, cost=0.05, objective=1.2)  # cheapest within band
    e = _cand(["w", "c", "m", "y"], de=2.5, cost=0.07, objective=1.3)  # best without black
    f = _cand(["k", "c", "y"], de=30.0, cost=0.09, objective=9.0)  # best without white
    g = _cand(["w", "k", "m"], de=3.0, cost=0.06, objective=1.25)  # objective filler
    pool = [a, b, d, g, e, f]  # objective order
    out = select_candidates(pool, 5, 1.0, black={"k"}, white={"w"})
    assert [c.tags for c in out] == [
        ["closest"],
        ["fewest paints"],
        ["cheapest"],
        ["no black"],
        ["no white"],
    ]
    assert [c.objective for c in out] == sorted(c.objective for c in out)  # objective order
    # top_n truncates in role priority; the objective filler only enters with room to spare
    out = select_candidates(pool, 2, 1.0, black={"k"}, white={"w"})
    assert [c.tags for c in out] == [["closest"], ["fewest paints"]]
    out = select_candidates(pool, 6, 1.0, black={"k"}, white={"w"})
    assert g in out and g.tags == []


def test_select_candidates_one_mix_can_win_several_roles() -> None:
    a = _cand(["w", "c", "y"], de=0.2, cost=0.06, objective=1.0)  # closest, fewest, cheapest
    b = _cand(["w", "k", "c", "y"], de=0.3, cost=0.07, objective=1.1)
    out = select_candidates([a, b], 3, 1.0, black={"k"}, white={"w"})
    assert out[0].tags == ["closest", "fewest paints", "cheapest"] and out[1].tags == []


def test_cheapest_is_skipped_when_costs_are_unknown() -> None:
    a = _cand(["w", "k", "c"], de=0.2, cost=0.0, objective=1.0)
    b = _cand(["w", "c", "y"], de=0.3, cost=0.0, objective=1.1)
    tags = [t for c in select_candidates([a, b], 3, 1.0, set(), set()) for t in c.tags]
    assert "cheapest" not in tags


def _sample(
    sid: str, stype: SampleType, comps: dict[str, float], holdout: bool = False
) -> CalibrationSampleData:
    return CalibrationSampleData(
        sid, stype, Substrate.WHITE, comps, np.full(N_BANDS, 0.5), holdout=holdout
    )


def test_under_sampled_paint_has_larger_error_and_uncertainty() -> None:
    roles = {"w": PaintRole.WHITE, "c": PaintRole.CHROMATIC, "y": PaintRole.CHROMATIC}
    samples = [
        _sample("MT-c", SampleType.MASSTONE_OVER_WHITE, {"c": 1.0}),
        _sample("MT-y", SampleType.MASSTONE_OVER_WHITE, {"y": 1.0}),
        _sample("MT-w", SampleType.MASSTONE_OVER_WHITE, {"w": 1.0}),
        _sample("T-c", SampleType.TINT, {"c": 0.1, "w": 0.9}),
        _sample("T-y", SampleType.TINT, {"y": 0.1, "w": 0.9}),
        *(_sample(f"X{i}", SampleType.MIXTURE, {"c": 0.5, "w": 0.5}) for i in range(3)),
        _sample("X9", SampleType.MIXTURE, {"y": 0.5, "w": 0.5}),  # y: one mixture only
        _sample("H1", SampleType.MIXTURE, {"c": 0.3, "y": 0.3, "w": 0.4}, holdout=True),
    ]
    residuals = [
        {"sample_id": s.sample_id, "de2000": 0.8, "holdout": s.holdout, "outlier": False}
        for s in samples
    ]
    q = paint_quality(residuals, {s.sample_id: s for s in samples}, ["w", "c", "y"], roles, "w")
    assert q["c"].coverage.ok and not q["y"].coverage.ok
    assert q["c"].error_de == pytest.approx(0.8)  # the hold-out RMS
    assert q["y"].error_de == pytest.approx(0.8 * UNDER_SAMPLED_FACTOR)
    ew, ec, ey = (q[p].error_de for p in ("w", "c", "y"))
    assert ew is not None and ec is not None and ey is not None
    f = [0.5, 0.5]
    assert mix_uncertainty(f, [ew, ey], 0.2, 0.05) > mix_uncertainty(f, [ew, ec], 0.2, 0.05)


def test_solve_uncertainty_follows_paint_errors() -> None:
    m = pool_model(5)
    target = Target(lab=np.array([60.0, -10.0, 15.0]))
    base = {pid: 0.5 for pid in m.ids}
    opts = SolveOptions(gamut_check=False, top_n=3, paint_error_de=base)
    worse = SolveOptions(gamut_check=False, top_n=3, paint_error_de={**base, "phthalo-blue": 1.0})
    a = {tuple(c.paint_ids): c.uncertainty_de for c in solve(m, target, opts).candidates}
    b = {tuple(c.paint_ids): c.uncertainty_de for c in solve(m, target, worse).candidates}
    for ids, u in a.items():
        assert u is not None and ids in b
        if "phthalo-blue" in ids:
            assert b[ids] > u  # type: ignore[operator]
        else:
            assert b[ids] == pytest.approx(u)
    assert all(
        c.uncertainty_de is None
        for c in solve(m, target, SolveOptions(gamut_check=False)).candidates
    )


def test_gamut_margin_sign_matches_in_gamut() -> None:
    m = pool_model(5)
    seen = set()
    for lab in (
        [60, -10, 15],
        [45, 30, -20],
        [30, 0, 0],
        [50, 75, 60],
        [40, -60, -70],
        [97, 0, 30],
    ):
        res = solve(m, Target(lab=np.array(lab, dtype=float)), SolveOptions(top_n=2), "test")
        assert res.in_gamut is not None and res.gamut_margin_de is not None
        assert (res.gamut_margin_de < 0) == (res.in_gamut is False), lab
        seen.add(res.in_gamut)
    assert seen == {True, False}  # both cases exercised


@pytest.fixture(scope="module")
def demo(tmp_path_factory: pytest.TempPathFactory) -> Iterator[TestClient]:
    url = f"sqlite:///{tmp_path_factory.mktemp('mix') / 'db.sqlite'}"
    seed_demo(url)
    with TestClient(create_app(Settings(database_url=url, compute_workers=0))) as c:
        yield c


def test_starter5_mid_chroma_target_gives_varied_tagged_mixes(demo: TestClient) -> None:
    r = demo.post(f"{API}/solve", json={"target": {"lab": [60, -10, 15]}, "top_n": 3})
    assert r.status_code == 200, r.text
    res = r.json()
    cands = res["candidates"]
    subsets = {tuple(x["paint_id"] for x in c["components"]) for c in cands}
    tagged = [c for c in cands if c["tags"]]
    assert len(subsets) >= 2 and len({c["tags"][0] for c in tagged}) >= 2
    assert sum("closest" in c["tags"] for c in cands) == 1
    assert all(c["uncertainty_de"] is not None and c["uncertainty_de"] > 0 for c in cands)
    assert res["in_gamut"] is True and res["gamut_margin_de"] > 0


def test_swatch_model_has_no_uncertainty(demo: TestClient) -> None:
    demo.post(f"{API}/models/cmykw-demo@2/activate")
    try:
        r = demo.post(f"{API}/solve", json={"target": {"lab": [60, -10, 15]}, "top_n": 2})
        assert r.status_code == 200, r.text
        assert all(c["uncertainty_de"] is None for c in r.json()["candidates"])
    finally:
        demo.post(f"{API}/models/cmykw-demo@1/activate")
