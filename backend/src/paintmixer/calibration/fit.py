"""Fit per-paint K(λ) and S(λ) from calibration samples.

Model (per sample, per band)::

    c        volume fractions of the fitted paints
    ks     = (c @ K) / (c @ S)
    SX     = (c @ S) * tau(λ) * gap_um
    R_g    = inverse_saunderson(measured substrate reflectance)
    R_pred = saunderson(r_layer(ks, SX, R_g))

Scale ambiguity: K-M only sees ratios, so multiplying every K and S at one wavelength by the
same factor changes nothing. We fix ``S_white(λ) = 1``; K and S of all other paints are then
expressed relative to white's scattering, and the per-band optical-thickness scale ``tau(λ)``
(white scattering per µm of wet gap) is fitted separately -- the white thickness series
(75/150/300 µm over black) is what makes it identifiable.

Solver: ``scipy.optimize.least_squares`` (TRF, ``soft_l1``) on log K, log S and log tau, with a
second-difference smoothness penalty across wavelength and a sparse finite-difference Jacobian
(each data residual only depends on the parameters of its own band). Initial values come from
masstone K/S and a per-band NNLS on white tints in K/S space.

Validation: samples flagged ``holdout`` are excluded from the fit and reported; when none are
flagged, k-fold cross-validation over whole mixture drawdowns is used.
"""

from __future__ import annotations

import time
from collections.abc import Callable, Sequence
from dataclasses import dataclass, field
from typing import Any

import numpy as np
from scipy.optimize import least_squares, nnls
from scipy.sparse import lil_matrix

from paintmixer.calibration.format import CalibrationSampleData, SampleType, Substrate
from paintmixer.colorsci.convert import reflectance_to_lab
from paintmixer.colorsci.delta_e import delta_e_2000
from paintmixer.colorsci.km import (
    DEFAULT_K1,
    DEFAULT_K2,
    KMModel,
    inverse_saunderson,
    ks_from_r,
    r_layer,
    saunderson,
)
from paintmixer.colorsci.spectral import N_BANDS
from paintmixer.colorsci.types import FloatArray
from paintmixer.domain import PaintInfo, PaintRole

ProgressFn = Callable[[float, str], None]

_LOG_MIN, _LOG_MAX = np.log(1e-5), np.log(1e3)


@dataclass(frozen=True)
class FitOptions:
    k1: float = DEFAULT_K1
    k2: float = DEFAULT_K2
    smoothness: float = 0.003
    loss: str = "soft_l1"
    f_scale: float = 0.01
    perceptual_weighting: bool = True
    max_nfev: int = 200
    k_folds: int = 5
    seed: int = 0
    outlier_rms: float = 0.006  # absolute floor (reflectance) for outlier flags
    outlier_factor: float = 4.0  # x median train RMS


@dataclass
class SampleResidual:
    sample_id: str
    type: str
    substrate: str
    holdout: bool
    rms: float
    de2000: float
    outlier: bool = False
    noise_floor_de: float = 0.0  # dE expected from measurement noise alone
    predicted: list[float] = field(default_factory=list)


@dataclass
class HoldoutReport:
    method: str  # "flagged" | "kfold" | "none"
    n_samples: int
    mean_de: float
    median_de: float
    p95_de: float
    max_de: float
    mean_rms: float
    noise_floor_mean_de: float = float("nan")

    def as_dict(self) -> dict[str, Any]:
        return self.__dict__.copy()


@dataclass
class FitResult:
    paint_ids: list[str]
    K: FloatArray
    S: FloatArray
    tau: FloatArray
    k1: float
    k2: float
    substrate_white: FloatArray
    substrate_black: FloatArray
    residuals: list[SampleResidual]
    holdout: HoldoutReport
    warnings: list[str]
    diagnostics: dict[str, Any]

    @property
    def model(self) -> KMModel:
        return KMModel(self.K, self.S, self.k1, self.k2)


class FitError(ValueError):
    pass


# ---------------------------------------------------------------------------------------------
# problem assembly


@dataclass
class _Problem:
    paint_ids: list[str]
    C: FloatArray  # (n_samples, n_paints)
    R: FloatArray  # (n_samples, 31) measured
    gap: FloatArray  # (n_samples,)
    rg: FloatArray  # (n_samples, 31) internal substrate reflectance
    weight: FloatArray  # (n_samples, 31)
    fixed_s: int  # index of the paint whose S is fixed to 1
    k1: float
    k2: float


def _substrates(
    samples: Sequence[CalibrationSampleData], warnings: list[str]
) -> tuple[FloatArray, FloatArray]:
    w = [s.reflectance for s in samples if s.type == SampleType.SUBSTRATE_WHITE]
    b = [s.reflectance for s in samples if s.type == SampleType.SUBSTRATE_BLACK]
    if not w:
        warnings.append("No SUB-W substrate measurement: assuming a flat 0.85 white substrate.")
    if not b:
        warnings.append("No SUB-B substrate measurement: assuming a flat 0.03 black substrate.")
    sw = np.mean(w, axis=0) if w else np.full(N_BANDS, 0.85)
    sb = np.mean(b, axis=0) if b else np.full(N_BANDS, 0.03)
    return np.asarray(sw, dtype=np.float64), np.asarray(sb, dtype=np.float64)


def _build(
    samples: Sequence[CalibrationSampleData],
    paint_ids: list[str],
    fixed_s: int,
    sub_w: FloatArray,
    sub_b: FloatArray,
    opts: FitOptions,
) -> _Problem:
    idx = {p: i for i, p in enumerate(paint_ids)}
    rows = [s for s in samples if s.components]
    C = np.zeros((len(rows), len(paint_ids)))
    for r, s in enumerate(rows):
        for pid, f in s.components.items():
            C[r, idx[pid]] = f
    C /= C.sum(axis=1, keepdims=True)
    R = np.stack([s.reflectance for s in rows])
    gap = np.array([s.effective_gap_um for s in rows])
    sub = np.stack([sub_w if s.substrate == Substrate.WHITE else sub_b for s in rows])
    rg = inverse_saunderson(sub, opts.k1, opts.k2)
    if opts.perceptual_weighting:
        weight = ((0.52) / (np.clip(R, 0, None) + 0.02)) ** (2.0 / 3.0)
    else:
        weight = np.ones_like(R)
    return _Problem(paint_ids, C, R, gap, rg, weight, fixed_s, opts.k1, opts.k2)


class _Packer:
    """Parameter vector layout, band-major: for each band [logK (n), logS (n-1), logtau]."""

    def __init__(self, n: int, fixed_s: int) -> None:
        self.n = n
        self.fixed_s = fixed_s
        self.free_s = [i for i in range(n) if i != fixed_s]
        self.per_band = n + len(self.free_s) + 1

    def pack(self, K: FloatArray, S: FloatArray, tau: FloatArray) -> FloatArray:
        blocks = [np.log(K), np.log(S[self.free_s]), np.log(tau)[None, :]]
        return np.concatenate(blocks, axis=0).T.reshape(-1)

    def unpack(self, x: FloatArray) -> tuple[FloatArray, FloatArray, FloatArray]:
        m = np.exp(np.clip(x.reshape(N_BANDS, self.per_band).T, _LOG_MIN, _LOG_MAX))
        K = m[: self.n]
        S = np.ones((self.n, N_BANDS))
        S[self.free_s] = m[self.n : self.n + len(self.free_s)]
        tau = m[-1]
        return K, S, tau

    def raw(self, x: FloatArray) -> FloatArray:
        return x.reshape(N_BANDS, self.per_band).T  # (per_band, 31) log-params


def _predict(p: _Problem, K: FloatArray, S: FloatArray, tau: FloatArray) -> FloatArray:
    s_mix = p.C @ S
    ks = (p.C @ K) / s_mix
    sx = s_mix * tau[None, :] * p.gap[:, None]
    return saunderson(r_layer(ks, sx, p.rg), p.k1, p.k2)


def _residual_fn(p: _Problem, pk: _Packer, smooth: float) -> Callable[[FloatArray], FloatArray]:
    def fn(x: FloatArray) -> FloatArray:
        K, S, tau = pk.unpack(x)
        data = (_predict(p, K, S, tau) - p.R) * p.weight
        raw = pk.raw(x)
        d2 = raw[:, :-2] - 2.0 * raw[:, 1:-1] + raw[:, 2:]
        return np.concatenate([data.reshape(-1), smooth * d2.reshape(-1)])

    return fn


def _sparsity(p: _Problem, pk: _Packer) -> lil_matrix:
    n_s = p.R.shape[0]
    n_par = pk.per_band * N_BANDS
    n_rows = n_s * N_BANDS + pk.per_band * (N_BANDS - 2)
    sp = lil_matrix((n_rows, n_par), dtype=np.int8)
    # data rows: sample i, band j -> params of band j used by sample i
    for i in range(n_s):
        used = np.flatnonzero(p.C[i] > 0)
        for j in range(N_BANDS):
            base = j * pk.per_band
            r = i * N_BANDS + j
            for k in used:
                sp[r, base + int(k)] = 1
            for q in range(len(pk.free_s)):
                if pk.free_s[q] in used:
                    sp[r, base + pk.n + q] = 1
            sp[r, base + pk.per_band - 1] = 1
    # smoothness rows: param q, interior band j -> bands j-1..j+1 of param q
    r0 = n_s * N_BANDS
    for q in range(pk.per_band):
        for j in range(N_BANDS - 2):
            r = r0 + q * (N_BANDS - 2) + j
            for dj in range(3):
                sp[r, (j + dj) * pk.per_band + q] = 1
    return sp


# ---------------------------------------------------------------------------------------------
# initialisation


def _initial_guess(
    samples: Sequence[CalibrationSampleData],
    paint_ids: list[str],
    roles: dict[str, PaintRole],
    fixed_s: int,
    sub_b: FloatArray,
    opts: FitOptions,
    warnings: list[str],
) -> tuple[FloatArray, FloatArray, FloatArray]:
    n = len(paint_ids)
    K = np.full((n, N_BANDS), 1.0)
    S = np.full((n, N_BANDS), 0.3)
    S[fixed_s] = 1.0
    white = paint_ids[fixed_s]

    def ks_meas(s: CalibrationSampleData) -> FloatArray:
        return ks_from_r(inverse_saunderson(s.reflectance, opts.k1, opts.k2))

    def masstones(pid: str, sub: Substrate | None = None) -> list[CalibrationSampleData]:
        return [
            s
            for s in samples
            if s.type in (SampleType.MASSTONE_OVER_WHITE, SampleType.MASSTONE_OVER_BLACK)
            and list(s.components) == [pid]
            and (sub is None or s.substrate == sub)
        ]

    # white: thickest masstone over white ~ opaque
    w_mt = sorted(masstones(white, Substrate.WHITE), key=lambda s: -s.effective_gap_um)
    ks_w = ks_meas(w_mt[0]) if w_mt else np.full(N_BANDS, 0.01)
    K[fixed_s] = np.maximum(ks_w, 1e-4)

    # tau: per-band grid search on white over black
    tau_grid = np.logspace(-4, 0.5, 120)
    w_b = masstones(white, Substrate.BLACK)
    if w_b:
        rg = inverse_saunderson(sub_b, opts.k1, opts.k2)
        err = np.zeros((tau_grid.size, N_BANDS))
        for s in w_b:
            sx = tau_grid[:, None] * s.effective_gap_um
            pred = saunderson(r_layer(ks_w[None, :], sx, rg[None, :]), opts.k1, opts.k2)
            err += (pred - s.reflectance[None, :]) ** 2
        tau = tau_grid[np.argmin(err, axis=0)]
        tau = np.convolve(np.pad(tau, 2, mode="edge"), np.ones(5) / 5, mode="valid")
    else:
        warnings.append(
            f"No masstone of {white} over black: the optical-thickness scale is poorly "
            "determined (add a white thickness series)."
        )
        tau = np.full(N_BANDS, 0.05)

    for i, pid in enumerate(paint_ids):
        if i == fixed_s:
            continue
        mt = masstones(pid, Substrate.WHITE) or masstones(pid)
        ks_m = ks_meas(mt[0]) if mt else None
        tints = [
            s
            for s in samples
            if s.type == SampleType.TINT
            and s.substrate == Substrate.WHITE
            and pid in s.components
            and white in s.components
        ]
        if tints:
            for j in range(N_BANDS):
                rows, rhs = [], []
                for t in tints:
                    cp, cw = t.components[pid], t.components[white]
                    y = ks_meas(t)[j]
                    rows.append([cp, -y * cp])
                    rhs.append(y * cw - cw * K[fixed_s, j])
                if ks_m is not None:
                    rows.append([0.2, -0.2 * ks_m[j]])
                    rhs.append(0.0)
                sol, _ = nnls(np.array(rows), np.array(rhs))
                K[i, j] = max(sol[0], 1e-3)
                S[i, j] = max(sol[1], 1e-3)
        elif ks_m is not None:
            S[i] = 0.3
            K[i] = np.maximum(ks_m * 0.3, 1e-3)
    return K, np.clip(S, 1e-3, 50), np.clip(tau, 1e-4, 3)


# ---------------------------------------------------------------------------------------------
# public API


def _data_warnings(
    samples: Sequence[CalibrationSampleData],
    paint_ids: list[str],
    roles: dict[str, PaintRole],
    white: str | None,
) -> list[str]:
    out = []
    mixtures = [s for s in samples if s.type == SampleType.MIXTURE and not s.holdout]
    for pid in paint_ids:
        has_mt = any(
            s.type in (SampleType.MASSTONE_OVER_WHITE, SampleType.MASSTONE_OVER_BLACK)
            and list(s.components) == [pid]
            for s in samples
        )
        if not has_mt:
            out.append(f"{pid}: no masstone measured.")
        if roles.get(pid) != PaintRole.WHITE and white is not None:
            has_tint = any(
                s.type == SampleType.TINT and pid in s.components and white in s.components
                for s in samples
            )
            if not has_tint:
                out.append(f"{pid}: no tint with white measured; its scattering is uncertain.")
        n_mix = len({s.drawdown_id for s in mixtures if pid in s.components})
        if n_mix < 3:
            out.append(f"{pid}: only {n_mix} mixture drawdown(s) in the fit (recommend >= 3).")
    n_drawdowns = len({s.drawdown_id for s in mixtures})
    if n_drawdowns < 2 * len(paint_ids):
        out.append(
            f"Too few mixtures: {n_drawdowns} drawdowns for {len(paint_ids)} paints "
            f"(recommend >= {2 * len(paint_ids)})."
        )
    return out


def _evaluate(
    samples: Sequence[CalibrationSampleData],
    model: KMModel,
    paint_ids: list[str],
    tau: FloatArray,
    sub_w: FloatArray,
    sub_b: FloatArray,
) -> tuple[FloatArray, FloatArray, FloatArray]:
    """Predicted reflectance, RMS and dE2000 for samples with components."""
    idx = {p: i for i, p in enumerate(paint_ids)}
    C = np.zeros((len(samples), len(paint_ids)))
    for r, s in enumerate(samples):
        for pid, f in s.components.items():
            C[r, idx[pid]] = f
    C /= C.sum(axis=1, keepdims=True)
    gap = np.array([s.effective_gap_um for s in samples])
    sub = np.stack([sub_w if s.substrate == Substrate.WHITE else sub_b for s in samples])
    pred = model.reflectance_layer(C, tau[None, :] * gap[:, None], sub)
    R = np.stack([s.reflectance for s in samples])
    rms = np.sqrt(np.mean((pred - R) ** 2, axis=1))
    de = delta_e_2000(reflectance_to_lab(pred), reflectance_to_lab(R))
    return pred, rms, de


def _noise_floor(
    samples: Sequence[CalibrationSampleData], default_sigma: float, seed: int, draws: int = 16
) -> FloatArray:
    """Mean dE2000 between each measurement and itself perturbed by its own noise level.

    Uses the per-band spread / sqrt(n_readings) when present, else ``default_sigma``. This is
    the dE a perfect model would still show against the measurement.
    """
    rng = np.random.default_rng(seed)
    R = np.stack([s.reflectance for s in samples])
    sig = np.stack(
        [
            (s.spread / np.sqrt(s.n_readings or 1))
            if s.spread is not None
            else np.full(N_BANDS, default_sigma)
            for s in samples
        ]
    )
    lab = reflectance_to_lab(R)
    noisy = R[None] + rng.normal(size=(draws, *R.shape)) * sig[None]
    de: FloatArray = delta_e_2000(reflectance_to_lab(noisy), lab[None]).mean(axis=0)
    return de


def _solve(
    train: Sequence[CalibrationSampleData],
    paint_ids: list[str],
    roles: dict[str, PaintRole],
    fixed_s: int,
    sub_w: FloatArray,
    sub_b: FloatArray,
    opts: FitOptions,
    warnings: list[str],
    x0: FloatArray | None = None,
) -> tuple[FloatArray, FloatArray, FloatArray, Any]:
    prob = _build(train, paint_ids, fixed_s, sub_w, sub_b, opts)
    pk = _Packer(len(paint_ids), fixed_s)
    if x0 is None:
        K0, S0, tau0 = _initial_guess(train, paint_ids, roles, fixed_s, sub_b, opts, warnings)
        x0 = pk.pack(K0, S0, tau0)
    res = least_squares(
        _residual_fn(prob, pk, opts.smoothness),
        x0,
        jac_sparsity=_sparsity(prob, pk),
        method="trf",
        loss=opts.loss,
        f_scale=opts.f_scale,
        x_scale="jac",
        tr_solver="lsmr",
        max_nfev=opts.max_nfev,
        xtol=1e-10,
        ftol=1e-10,
    )
    K, S, tau = pk.unpack(res.x)
    return K, S, tau, res


def fit_calibration(
    samples: Sequence[CalibrationSampleData],
    paints: dict[str, PaintInfo],
    options: FitOptions | None = None,
    progress: ProgressFn | None = None,
) -> FitResult:
    """Fit K/S for every paint that appears in ``samples``."""
    opts = options or FitOptions()
    t0 = time.perf_counter()

    def report(f: float, msg: str) -> None:
        if progress is not None:
            progress(f, msg)

    warnings: list[str] = []
    used = sorted({p for s in samples for p in s.components})
    unknown = [p for p in used if p not in paints]
    if unknown:
        raise FitError(f"samples reference unknown paints: {', '.join(unknown)}")
    if not used:
        raise FitError("no samples with components to fit")
    roles = {p: paints[p].role for p in used}
    whites = [p for p in used if roles[p] == PaintRole.WHITE]
    # order: whites first so the reference white is index 0
    paint_ids = whites + [p for p in used if p not in whites]
    if not whites:
        warnings.append(
            f"No white paint in the samples: fixing S of {paint_ids[0]} to 1 instead; "
            "pale colours cannot be predicted."
        )
    fixed_s = 0
    missing = [p for p, info in paints.items() if p not in used and info.role is not None]
    if missing:
        warnings.append(f"Paints without calibration samples (not fitted): {', '.join(missing)}")
    sub_w, sub_b = _substrates(samples, warnings)
    with_comp = [s for s in samples if s.components]
    train = [s for s in with_comp if not s.holdout]
    hold = [s for s in with_comp if s.holdout]
    warnings += _data_warnings(samples, paint_ids, roles, whites[0] if whites else None)

    report(0.05, f"fitting {len(paint_ids)} paints on {len(train)} samples")
    K, S, tau, res = _solve(train, paint_ids, roles, fixed_s, sub_w, sub_b, opts, warnings)
    model = KMModel(K, S, opts.k1, opts.k2)
    report(0.6 if not hold else 0.9, "evaluating")

    pred_all, rms_all, de_all = _evaluate(with_comp, model, paint_ids, tau, sub_w, sub_b)
    is_hold = np.array([s.holdout for s in with_comp])
    train_de = de_all[~is_hold]
    threshold = max(opts.outlier_rms, opts.outlier_factor * float(np.median(rms_all[~is_hold])))
    floor_all = _noise_floor(with_comp, float(np.median(rms_all[~is_hold])), opts.seed)

    method = "flagged"
    eval_de, eval_rms, eval_floor = de_all[is_hold], rms_all[is_hold], floor_all[is_hold]
    if not hold:
        method = "kfold"
        drawdowns = sorted({s.drawdown_id for s in train if s.type == SampleType.MIXTURE})
        if len(drawdowns) < 2:
            method = "none"
            eval_de = eval_rms = eval_floor = np.array([])
        else:
            rng = np.random.default_rng(opts.seed)
            order = rng.permutation(len(drawdowns))
            k = min(opts.k_folds, len(drawdowns))
            folds = [set(np.array(drawdowns)[order[f::k]].tolist()) for f in range(k)]
            des, rmss, floors = [], [], []
            pk = _Packer(len(paint_ids), fixed_s)
            x_full = pk.pack(K, S, tau)
            for f, fold in enumerate(folds):
                report(0.6 + 0.35 * f / k, f"cross-validation fold {f + 1}/{k}")
                tr = [s for s in train if s.drawdown_id not in fold]
                te = [s for s in train if s.drawdown_id in fold]
                Kf, Sf, tf, _ = _solve(
                    tr, paint_ids, roles, fixed_s, sub_w, sub_b, opts, [], x0=x_full
                )
                _, r_, d_ = _evaluate(
                    te, KMModel(Kf, Sf, opts.k1, opts.k2), paint_ids, tf, sub_w, sub_b
                )
                des.append(d_)
                rmss.append(r_)
                floors.append(floor_all[[s.drawdown_id in fold for s in with_comp]])
            eval_de, eval_rms = np.concatenate(des), np.concatenate(rmss)
            eval_floor = np.concatenate(floors)

    def stats(a: FloatArray) -> tuple[float, float, float, float]:
        if a.size == 0:
            return (float("nan"),) * 4
        return (
            float(a.mean()),
            float(np.median(a)),
            float(np.percentile(a, 95)),
            float(a.max()),
        )

    mean_de, med_de, p95_de, max_de = stats(eval_de)
    hold_report = HoldoutReport(
        method,
        int(eval_de.size),
        mean_de,
        med_de,
        p95_de,
        max_de,
        float(eval_rms.mean()) if eval_rms.size else float("nan"),
        float(eval_floor.mean()) if eval_floor.size else float("nan"),
    )
    residuals = [
        SampleResidual(
            s.sample_id,
            s.type.value,
            s.substrate.value,
            s.holdout,
            float(rms_all[i]),
            float(de_all[i]),
            bool(rms_all[i] > threshold and not s.holdout),
            float(floor_all[i]),
            pred_all[i].round(6).tolist(),
        )
        for i, s in enumerate(with_comp)
    ]
    n_out = sum(r.outlier for r in residuals)
    if n_out:
        warnings.append(
            f"{n_out} sample(s) flagged as outliers (RMS reflectance residual > {threshold:.4f})."
        )
    diagnostics = {
        "n_train": len(train),
        "n_holdout": len(hold),
        "n_paints": len(paint_ids),
        "cost": float(res.cost),
        "nfev": int(res.nfev),
        "status": int(res.status),
        "message": str(res.message),
        "train_mean_de": float(train_de.mean()) if train_de.size else float("nan"),
        "train_max_de": float(train_de.max()) if train_de.size else float("nan"),
        "train_mean_rms": float(rms_all[~is_hold].mean()) if train_de.size else float("nan"),
        "outlier_threshold_rms": threshold,
        "duration_s": time.perf_counter() - t0,
        "options": {k: v for k, v in opts.__dict__.items()},
    }
    report(1.0, "done")
    return FitResult(
        paint_ids,
        K,
        S,
        tau,
        opts.k1,
        opts.k2,
        sub_w,
        sub_b,
        residuals,
        hold_report,
        warnings,
        diagnostics,
    )
