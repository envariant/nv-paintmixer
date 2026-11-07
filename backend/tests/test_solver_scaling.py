"""Solver accuracy and performance at scale (``make test-slow``)."""

from __future__ import annotations

import os
import time
from concurrent.futures import ProcessPoolExecutor

import numpy as np
import pytest

from paintmixer.solver.solve import SolveOptions, Target, solve
from tests.solver_helpers import pool_model, random_recipe_targets

pytestmark = pytest.mark.slow


def _compare(args: tuple[int, list[float]]) -> tuple[float, float]:
    n, lab = args
    m = pool_model(n)
    base = SolveOptions(gamut_check=False, top_n=1, refine_top=6)
    ex = solve(
        m, Target(lab=np.array(lab)), SolveOptions(**{**base.__dict__, "search": "exhaustive"})
    )
    st = solve(m, Target(lab=np.array(lab)), SolveOptions(**{**base.__dict__, "search": "staged"}))
    return ex.candidates[0].de2000_continuous, st.candidates[0].de2000_continuous


def test_staged_matches_exhaustive_n12_200_targets() -> None:
    m = pool_model(12)
    targets = [t[0].tolist() for t in random_recipe_targets(m, 200, seed=2024)]
    with ProcessPoolExecutor(max_workers=os.cpu_count() or 2) as ex:
        results = list(ex.map(_compare, [(12, t) for t in targets], chunksize=10))
    de_ex = np.array([r[0] for r in results])
    de_st = np.array([r[1] for r in results])
    gap = de_st - de_ex
    assert gap.max() < 0.2, f"worst staged-exhaustive gap {gap.max():.3f}"
    assert np.mean(de_ex) < 0.2


def test_known_recipes_pool9() -> None:
    m = pool_model(9)
    des = []
    for lab, _i, _c in random_recipe_targets(m, 40, seed=99):
        des.append(solve(m, Target(lab=lab), SolveOptions(gamut_check=False)).candidates[0].de2000)
    assert max(des) < 0.5, max(des)


@pytest.mark.parametrize(("n", "budget"), [(12, 3.0), (20, 5.0)])
def test_performance(n: int, budget: float) -> None:
    m = pool_model(n)
    targets = random_recipe_targets(m, 5, seed=n)
    solve(m, Target(lab=targets[0][0]), SolveOptions())  # warm caches (gamut, weights)
    times = []
    for lab, _i, _c in targets:
        t0 = time.perf_counter()
        res = solve(m, Target(lab=lab), SolveOptions())
        times.append(time.perf_counter() - t0)
        assert res.candidates[0].de2000 < 0.5
    assert max(times) < budget, times
