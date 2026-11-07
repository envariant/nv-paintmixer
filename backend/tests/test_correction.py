from __future__ import annotations

import numpy as np
import pytest

from paintmixer.colorsci import KMModel, delta_e_2000, reflectance_to_lab
from paintmixer.correction import additions_for, correction_step, run_closed_loop
from paintmixer.hardware.dispenser import (
    Dispenser,
    DispenserError,
    SimulatedDispenser,
    dispense_recipe,
)
from paintmixer.measurement.base import MeasureRequest
from paintmixer.measurement.sources import SimulatedSource
from paintmixer.solver.model import PoolModel
from paintmixer.solver.solve import SolveOptions, Target, solve
from tests.solver_helpers import pool_model


def biased(model: PoolModel, seed: int = 0) -> PoolModel:
    """A 'fitted' model that is wrong in a smooth, plausible way vs the true one."""
    rng = np.random.default_rng(seed)
    K = model.km.K * rng.uniform(0.85, 1.15, size=(model.n, 1))
    S = model.km.S * rng.uniform(0.85, 1.15, size=(model.n, 1))
    S[0] = 1.0
    return PoolModel(model.paints, KMModel(K, S, model.km.k1, model.km.k2))


def test_simulated_dispenser_error_and_quantisation() -> None:
    d = SimulatedDispenser(
        resolution_ml=0.05, rel_sigma=0.02, abs_sigma_ml=0.0, bias={2: 0.05}, seed=1
    )
    assert isinstance(d, Dispenser)
    vals = np.array([d.dispense(1, 10.0) for _ in range(300)])
    assert abs(vals.mean() - 10.0) < 0.05 and 0.1 < vals.std() < 0.3
    np.testing.assert_allclose(vals / 0.05, np.round(vals / 0.05), atol=1e-9)
    biased_vals = np.array([d.dispense(2, 10.0) for _ in range(300)])
    assert abs(biased_vals.mean() - 10.5) < 0.06
    assert d.dispense(1, 0.0) == 0.0
    with pytest.raises(DispenserError):
        d.dispense(1, -1)
    res = dispense_recipe(d, {"a": 1.0, "b": 0.0}, {"a": 1, "b": 2})
    assert [r.paint_id for r in res] == ["a"]
    with pytest.raises(DispenserError):
        dispense_recipe(d, {"c": 1.0}, {"a": 1})


def test_additions() -> None:
    cur = np.array([50.0, 30.0, 20.0])
    adds, total = additions_for(cur, np.array([0.4, 0.4, 0.2]))
    new = cur + adds
    np.testing.assert_allclose(new / new.sum(), [0.4, 0.4, 0.2])
    assert np.all(adds >= 0) and total == pytest.approx(new.sum())


def test_correction_step_reduces_error_on_biased_model() -> None:
    true = pool_model(5)
    fitted = biased(true, seed=3)
    target = np.array([60.0, -12.0, -20.0])
    rec = solve(fitted, Target(lab=target), SolveOptions(gamut_check=False)).candidates[0]
    idx = np.array([fitted.ids.index(p) for p in rec.paint_ids])
    c = np.array(rec.fractions_quantised)
    meas = true.lab(idx[None], c[None])[0]
    de0 = float(delta_e_2000(meas, target))
    step = correction_step(fitted, idx, c, target, meas)
    assert abs(step.fractions.sum() - 1) < 1e-12
    de1 = float(delta_e_2000(true.lab(idx[None], step.fractions[None])[0], target))
    assert de0 > 1.0 and de1 < de0 / 2


@pytest.mark.parametrize("mode", ["additions", "remix"])
def test_closed_loop_converges_with_simulators(mode: str) -> None:
    true = pool_model(5)
    fitted = biased(true, seed=7)
    target_r = true.reflectance(np.array([[0, 2, 4]]), np.array([[0.6, 0.15, 0.25]]))[0]
    target = reflectance_to_lab(target_r)
    rec = solve(fitted, Target(lab=target), SolveOptions(gamut_check=False)).candidates[0]
    ids = rec.paint_ids
    channels = {p: i + 1 for i, p in enumerate(fitted.ids)}
    disp = SimulatedDispenser(resolution_ml=0.05, rel_sigma=0.01, abs_sigma_ml=0.01, seed=2)
    instrument = SimulatedSource(true.km, true.ids, noise=0.0005, seed=4)

    def dispense(vol: np.ndarray) -> np.ndarray:
        res = dispense_recipe(disp, dict(zip(ids, vol.tolist(), strict=True)), channels)
        got = {r.paint_id: r.actual_ml for r in res}
        return np.array([got.get(p, 0.0) for p in ids])

    def measure(cup: np.ndarray) -> np.ndarray:
        comps = {p: float(v) for p, v in zip(ids, cup, strict=True) if v > 0}
        return reflectance_to_lab(instrument.read(MeasureRequest("cup", None, comps)).reflectance)

    out = run_closed_loop(
        fitted,
        ids,
        rec.fractions_quantised,
        target,
        100.0,
        dispense,
        measure,
        mode=mode,
        tolerance_de=0.6,
    )
    assert out.iterations[0].de > 1.0  # model bias makes the first mix miss
    assert out.converged, [i.de for i in out.iterations]
    assert len(out.iterations) <= 6
    if mode == "additions":
        cups = [sum(i.dispensed_ml) for i in out.iterations]
        assert cups == sorted(cups)  # paint is only ever added


def test_closed_loop_reports_non_convergence() -> None:
    true = pool_model(5)
    target = np.array([60.0, 90.0, -90.0])  # out of gamut
    ids = ["titanium-white", "quinacridone-magenta", "phthalo-blue"]
    idx = np.array([true.ids.index(p) for p in ids])

    def measure(cup: np.ndarray) -> np.ndarray:
        out: np.ndarray = true.lab(idx[None], (cup / cup.sum())[None])[0]
        return out

    out = run_closed_loop(
        true, ids, [0.4, 0.4, 0.2], target, 100.0, lambda v: v, measure, max_iter=3
    )
    assert not out.converged and len(out.iterations) == 4 and "not converged" in out.message
