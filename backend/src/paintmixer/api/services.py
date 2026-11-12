"""Glue between DB rows and the pure libraries."""

from __future__ import annotations

from typing import Any

import numpy as np
from sqlmodel import Session, col, select

from paintmixer.api.errors import ApiError, bad_request, not_found
from paintmixer.api.schemas import AppSettings, GamutResponse, GamutSliceOut, TargetIn
from paintmixer.calibration.accuracy import PaintQuality, paint_quality
from paintmixer.calibration.format import CalibrationSampleData, SampleType, Substrate
from paintmixer.calibration.strength import PaintStrength, tinting_strengths
from paintmixer.colorsci.convert import (
    hex_to_srgb,
    lab_to_srgb,
    reflectance_to_lab,
    srgb_to_hex,
    srgb_to_lab,
)
from paintmixer.colorsci.km import KMModel
from paintmixer.colorsci.spectral import Illuminant
from paintmixer.db import models as m
from paintmixer.domain import PaintInfo, PaintRole
from paintmixer.measurement.selftest import SelftestThresholds
from paintmixer.solver.gamut import Gamut
from paintmixer.solver.gamut_chart import boundary_hex
from paintmixer.solver.model import PoolModel
from paintmixer.solver.refine import Weights
from paintmixer.solver.solve import SolveOptions, Target

SETTINGS_KEY = "app"


# --- settings -------------------------------------------------------------------------------


def load_settings(session: Session) -> AppSettings:
    row = session.get(m.Setting, SETTINGS_KEY)
    if row is None or not isinstance(row.value, dict):
        return AppSettings()
    merged = {**AppSettings().model_dump(), **row.value}
    # Settings saved before machine_max_batch_ml existed may hold a larger batch than the
    # default maximum (250 ml). Raise the maximum to that batch rather than refuse to load;
    # PATCH /settings still refuses a new batch above the maximum.
    if merged["batch_volume_ml"] > merged["machine_max_batch_ml"]:
        merged["machine_max_batch_ml"] = merged["batch_volume_ml"]
    return AppSettings.model_validate(merged)


def check_max_paints(max_paints: int | None, fm: m.FittedModel | None) -> None:
    """A requested ``max_paints`` may be at most the model's paint count (the UI stepper is
    1..N). Values taken from settings are not checked: the solver uses min(max_paints, pool)."""
    if max_paints is None or fm is None:
        return
    n = len(fm.paint_ids)
    if max_paints > n:
        raise bad_request(
            "bad_constraints",
            f"max_paints ({max_paints}) is more than the paints in model v{fm.version} ({n})",
            {"max_paints": max_paints, "paints_in_model": n},
        )


def save_settings(session: Session, settings: AppSettings) -> AppSettings:
    row = session.get(m.Setting, SETTINGS_KEY)
    data = settings.model_dump(mode="json")
    if row is None:
        session.add(m.Setting(key=SETTINGS_KEY, value=data))
    else:
        row.value = data
        session.add(row)
    session.commit()
    return settings


def selftest_thresholds(s: AppSettings) -> SelftestThresholds:
    return SelftestThresholds(
        warn_de=s.selftest_warn_de,
        fail_de=s.selftest_fail_de,
        white_min=s.selftest_white_min,
        white_max=s.selftest_white_max,
        max_band_jump=s.selftest_max_band_jump,
        smoothness_rms=s.selftest_smoothness_rms,
        cast_chroma=s.selftest_cast_chroma,
    )


def settings_from_db(url: str) -> AppSettings:
    """App settings stored at ``url``, or defaults if that database does not exist yet."""
    from pathlib import Path

    from sqlalchemy.exc import OperationalError

    from paintmixer.db.session import get_engine

    if url.startswith("sqlite:///") and not Path(url.removeprefix("sqlite:///")).exists():
        return AppSettings()
    try:
        with Session(get_engine(url)) as session:
            return load_settings(session)
    except OperationalError:
        return AppSettings()


# --- paints ---------------------------------------------------------------------------------


def paint_info(p: m.Paint) -> PaintInfo:
    return PaintInfo(
        id=p.id,
        role=PaintRole(p.role),
        density_g_per_ml=p.density_g_per_ml,
        name=p.name,
        cost_per_ml=p.cost_per_ml,
        min_dose_ml=p.min_dose_ml,
    )


def all_paints(session: Session) -> list[m.Paint]:
    return list(session.exec(select(m.Paint).order_by(col(m.Paint.id))).all())


def paint_infos(session: Session) -> dict[str, PaintInfo]:
    return {p.id: paint_info(p) for p in all_paints(session)}


# --- models ---------------------------------------------------------------------------------


def active_model(session: Session) -> m.FittedModel:
    fm = session.exec(select(m.FittedModel).where(col(m.FittedModel.active))).first()
    if fm is None:
        raise ApiError(
            409, "no_active_model", "No fitted model is active: upload calibration data and fit."
        )
    return fm


def active_model_or_none(session: Session) -> m.FittedModel | None:
    return session.exec(select(m.FittedModel).where(col(m.FittedModel.active))).first()


def km_of(fm: m.FittedModel) -> KMModel:
    return KMModel(np.array(fm.K), np.array(fm.S), fm.k1, fm.k2)


def pool_model(
    session: Session, pool: list[str] | None, fm: m.FittedModel | None = None
) -> tuple[PoolModel, m.FittedModel]:
    """Forward model of ``pool`` under ``fm`` (default: the active model).

    With no pool: the loaded paints for the active model, or every paint of ``fm`` when a
    specific model is given."""
    explicit = fm is not None
    fm = fm if fm is not None else active_model(session)
    paints = {p.id: p for p in all_paints(session)}
    if pool is None:
        if explicit:
            pool = [p for p in fm.paint_ids if p in paints]
        else:
            pool = [p.id for p in paints.values() if p.loaded and p.active]
        if not pool:
            raise bad_request(
                "empty_pool", "No loaded paints: mark paints as loaded or pass an explicit pool."
            )
    unknown = [p for p in pool if p not in paints]
    if unknown:
        raise bad_request("unknown_paint", f"unknown paint ids: {', '.join(unknown)}")
    uncal = [p for p in pool if p not in fm.paint_ids]
    if uncal:
        which = f"model v{fm.version}" if explicit else f"the active model (v{fm.version})"
        raise bad_request(
            "uncalibrated_paint",
            f"paints not in {which}: {', '.join(uncal)}",
            {"paint_ids": uncal},
        )
    seen: list[str] = []
    for p in pool:
        if p not in seen:
            seen.append(p)
    infos = [paint_info(paints[p]) for p in seen]
    return PoolModel.from_model(km_of(fm), fm.paint_ids, infos), fm


def gamut_response(model: PoolModel, fm: m.FittedModel, g: Gamut, max_paints: int) -> GamutResponse:
    return GamutResponse(
        pool=model.ids,
        L_min=g.L_min,
        L_max=g.L_max,
        n_samples=g.n_samples,
        model_version=fm.version,
        model_source=fm.source,
        max_paints=max_paints,
        slices=[
            GamutSliceOut(
                L=sl.L,
                hue_deg=sl.hue_deg.tolist(),
                chroma=np.round(sl.chroma, 3).tolist(),
                a=np.round(sl.a, 3).tolist(),
                b=np.round(sl.b, 3).tolist(),
                hex=boundary_hex(sl),
            )
            for sl in g.slices
        ],
    )


def current_batches(session: Session, paint_ids: list[str]) -> dict[str, str]:
    """Each paint's batch code now (recorded on a model when it is made)."""
    return {p.id: p.batch_code for p in all_paints(session) if p.id in paint_ids}


def model_paint_quality(session: Session, fm: m.FittedModel) -> dict[str, PaintQuality]:
    """Per-paint coverage and residuals of a fitted model (residuals joined with the samples
    they came from; samples deleted since the fit are skipped)."""
    residuals = list(fm.diagnostics.get("residuals", []))
    ids = [r["sample_id"] for r in residuals]
    rows = session.exec(
        select(m.CalibrationSample).where(col(m.CalibrationSample.id).in_(ids))
    ).all()
    samples = {r.id: sample_to_data(r) for r in rows}
    roles = {p.id: PaintRole(p.role) for p in all_paints(session)}
    whites = [p for p in fm.paint_ids if roles.get(p) == PaintRole.WHITE]
    return paint_quality(residuals, samples, fm.paint_ids, roles, whites[0] if whites else None)


def model_paint_errors(session: Session, fm: m.FittedModel) -> dict[str, float] | None:
    """Per-paint calibration error (dE2000) for the solver's ``uncertainty_de``; None for
    models without residuals (swatch models)."""
    if fm.source != "calibration":
        return None
    errors = {
        pid: e
        for pid, q in model_paint_quality(session, fm).items()
        if (e := q.error_de) is not None
    }
    return errors or None


def default_solve_options(session: Session, s: AppSettings, fm: m.FittedModel) -> SolveOptions:
    """Solver options from the settings, as ``POST /solve`` uses them when the request sets
    nothing (and the library match cache always)."""
    w = s.weights
    return SolveOptions(
        max_paints=s.max_paints,
        min_fraction=s.min_fraction,
        illuminant=s.illuminant,
        check_illuminants=tuple(s.check_illuminants),
        batch_volume_ml=s.batch_volume_ml,
        resolution_ml=s.dispenser_resolution_ml,
        weights=Weights(de=w.de, n_paints=w.n_paints, cost=w.cost, metamerism=w.metamerism),
        top_n=s.top_n,
        seed=s.seed,
        out_of_gamut_de=s.out_of_gamut_de,
        accept_tolerance_de=s.accept_tolerance_de,
        paint_error_de=model_paint_errors(session, fm),
    )


def model_strengths(session: Session, fm: m.FittedModel) -> dict[str, PaintStrength]:
    """Tinting strength of each non-white paint in ``fm``, reduced with the model's white."""
    roles = {p.id: p.role for p in all_paints(session)}
    whites = [p for p in fm.paint_ids if roles.get(p) == PaintRole.WHITE.value]
    if not whites:
        return {}
    return tinting_strengths(km_of(fm), fm.paint_ids, whites[0])


# --- colours / targets ----------------------------------------------------------------------


def color_from_input(
    hex_: str | None,
    srgb: list[float] | None,
    lab: list[float] | None,
    spectrum: list[float] | None,
) -> tuple[list[float], list[float], str, bool]:
    """Return (lab, srgb, hex, in_srgb_gamut) from whichever representation was given."""
    try:
        if spectrum is not None:
            lab_a = reflectance_to_lab(np.array(spectrum))
        elif lab is not None:
            lab_a = np.array(lab, dtype=np.float64)
        elif srgb is not None:
            lab_a = srgb_to_lab(np.array(srgb))
        elif hex_ is not None:
            lab_a = srgb_to_lab(hex_to_srgb(hex_))
        else:
            raise bad_request("missing_colour", "no colour given")
    except ValueError as e:
        raise bad_request("bad_colour", str(e)) from e
    s = lab_to_srgb(lab_a)
    rgb = srgb if (srgb is not None and spectrum is None and lab is None) else s.rgb.tolist()
    return (
        [round(float(x), 4) for x in lab_a],
        [round(float(x), 5) for x in rgb],
        srgb_to_hex(np.array(rgb)),
        not bool(s.out_of_gamut),
    )


def resolve_target(session: Session, t: TargetIn) -> Target:
    if t.library_id is not None:
        e = session.get(m.ColorLibraryEntry, t.library_id)
        if e is None:
            raise not_found("colour", t.library_id)
        spec = np.array(e.spectrum) if e.spectrum else None
        return Target(np.array(e.lab), spec, t.name or e.name, "library")
    lab, _rgb, _hex, _ok = color_from_input(t.hex, t.srgb, t.lab, t.spectrum)
    spec = np.array(t.spectrum) if t.spectrum is not None else None
    source = next(k for k in ("lab", "srgb", "hex", "spectrum") if getattr(t, k) is not None)
    return Target(np.array(lab), spec, t.name, source)


# --- calibration samples --------------------------------------------------------------------


def sample_to_data(s: m.CalibrationSample) -> CalibrationSampleData:
    return CalibrationSampleData(
        sample_id=s.id,
        type=SampleType(s.type),
        substrate=Substrate(s.substrate),
        components=dict(s.components),
        reflectance=np.array(s.reflectance),
        gap_um=s.gap_um,
        holdout=s.holdout,
        spread=np.array(s.spread) if s.spread else None,
        planned_components=s.planned_components,
        masses_g=s.masses_g,
        measured_at=s.measured_at,
        n_readings=s.n_readings,
        notes=s.notes,
    )


def data_to_sample(d: CalibrationSampleData, upload_id: int | None) -> m.CalibrationSample:
    return m.CalibrationSample(
        id=d.sample_id,
        type=d.type.value,
        substrate=d.substrate.value,
        components=d.components,
        planned_components=d.planned_components,
        masses_g=d.masses_g,
        gap_um=d.gap_um,
        holdout=d.holdout,
        reflectance=[round(float(x), 6) for x in d.reflectance],
        spread=[round(float(x), 6) for x in d.spread] if d.spread is not None else None,
        n_readings=d.n_readings,
        measured_at=d.measured_at,
        notes=d.notes,
        upload_id=upload_id,
    )


def clean_floats(v: Any) -> Any:
    if isinstance(v, float) and not np.isfinite(v):
        return None
    if isinstance(v, dict):
        return {k: clean_floats(x) for k, x in v.items()}
    if isinstance(v, list):
        return [clean_floats(x) for x in v]
    return v


ILLUMINANTS_REPORTED = (Illuminant.D65, Illuminant.A, Illuminant.F11)
