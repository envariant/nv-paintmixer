from __future__ import annotations

from collections.abc import Sequence

import numpy as np

from paintmixer.calibration.synthetic import POOL_IDS, STARTER_IDS, random_paints, synthetic_paints
from paintmixer.colorsci import KMModel, reflectance_to_lab
from paintmixer.colorsci.types import FloatArray
from paintmixer.solver.model import PoolModel


def pool_model(n: int | None = None, ids: Sequence[str] | None = None, seed: int = 1) -> PoolModel:
    if ids is not None:
        ps = synthetic_paints(ids)
    else:
        assert n is not None
        ps = synthetic_paints(POOL_IDS if n > 5 else STARTER_IDS)
        if n > len(ps):
            ps = ps + random_paints(n - len(ps), seed=seed)
        ps = ps[:n]
    return PoolModel(
        [p.info for p in ps], KMModel(np.stack([p.K for p in ps]), np.stack([p.S for p in ps]))
    )


def random_recipe_targets(
    model: PoolModel, count: int, seed: int, k_range: tuple[int, int] = (2, 5), min_f: float = 0.05
) -> list[tuple[FloatArray, list[int], FloatArray]]:
    """Targets made from known recipes with every fraction >= ``min_f``."""
    rng = np.random.default_rng(seed)
    out = []
    for _ in range(count):
        k = int(rng.integers(k_range[0], k_range[1] + 1))
        idx = rng.choice(model.n, k, replace=False)
        c = min_f + rng.dirichlet(np.ones(k)) * (1 - k * min_f)
        lab = reflectance_to_lab(model.reflectance(idx[None], c[None])[0])
        out.append((lab, [int(i) for i in idx], c))
    return out
