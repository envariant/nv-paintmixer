"""Glue between DB rows and the pure libraries."""

from __future__ import annotations

from typing import Any

import numpy as np
from sqlmodel import Session, col, select

from paintmixer.api.errors import ApiError, bad_request, not_found
from paintmixer.api.schemas import AppSettings, TargetIn
from paintmixer.calibration.format import CalibrationSampleData, SampleType, Substrate
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
from paintmixer.solver.model import PoolModel
from paintmixer.solver.solve import Target

SETTINGS_KEY = "app"


# --- settings -------------------------------------------------------------------------------


def load_settings(session: Session) -> AppSettings:
    row = session.get(m.Setting, SETTINGS_KEY)
    if row is None or not isinstance(row.value, dict):
        return AppSettings()
    return AppSettings.model_validate({**AppSettings().model_dump(), **row.value})


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


def km_of(fm: m.FittedModel) -> KMModel:
    return KMModel(np.array(fm.K), np.array(fm.S), fm.k1, fm.k2)


def pool_model(session: Session, pool: list[str] | None) -> tuple[PoolModel, m.FittedModel]:
    fm = active_model(session)
    paints = {p.id: p for p in all_paints(session)}
    if pool is None:
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
        raise bad_request(
            "uncalibrated_paint",
            f"paints not in the active model (v{fm.version}): {', '.join(uncal)}",
            {"paint_ids": uncal},
        )
    seen: list[str] = []
    for p in pool:
        if p not in seen:
            seen.append(p)
    infos = [paint_info(paints[p]) for p in seen]
    return PoolModel.from_model(km_of(fm), fm.paint_ids, infos), fm


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
