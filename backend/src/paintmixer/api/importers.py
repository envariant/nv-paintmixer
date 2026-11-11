"""Import, upload, fit and model-storage operations shared by the API routers and the CLI
(``paintmixer seed-demo``). They work on a DB session and raise :class:`ApiError` for bad input.
"""

from __future__ import annotations

import csv
import io
import traceback
from collections.abc import Collection

import numpy as np
from pydantic import ValidationError
from sqlmodel import Session, col, delete, select

from paintmixer.api.errors import ApiError, bad_request, conflict
from paintmixer.api.lines import (
    DEFAULT_LINE,
    find_line,
    line_for_new_model,
    model_ref,
    place_model,
    set_active,
)
from paintmixer.api.schemas import (
    ColorImportResult,
    FitRequest,
    PaintCreate,
    PaintImportResult,
    UploadResult,
    ValidationIssueOut,
    ValidationReportOut,
)
from paintmixer.api.services import (
    all_paints,
    clean_floats,
    color_from_input,
    current_batches,
    data_to_sample,
    load_settings,
    paint_infos,
    sample_to_data,
)
from paintmixer.calibration.fit import FitError, FitOptions, fit_calibration
from paintmixer.calibration.format import SPECTRUM_COLUMNS, ValidationReport, parse_calibration_csv
from paintmixer.calibration.report import fit_result_to_dict
from paintmixer.calibration.swatch import SwatchModel, SwatchPaint
from paintmixer.colorsci.convert import hex_to_srgb, srgb_to_lab
from paintmixer.db import models as m
from paintmixer.db.models import utcnow
from paintmixer.db.session import get_engine
from paintmixer.domain import PaintRole

# --- paints ---------------------------------------------------------------------------------


def validate_paint(session: Session, p: m.Paint) -> None:
    """Loaded paints need a free channel in range; diluted stocks need an existing parent."""
    if p.loaded:
        if p.dispenser_channel is None:
            raise bad_request("channel_required", "a loaded paint needs a dispenser_channel")
        n_ch = load_settings(session).dispenser_channels
        if p.dispenser_channel > n_ch:
            raise bad_request(
                "channel_out_of_range", f"dispenser_channel must be 1-{n_ch} (settings)"
            )
        clash = session.exec(
            select(m.Paint).where(
                col(m.Paint.loaded),
                m.Paint.dispenser_channel == p.dispenser_channel,
                m.Paint.id != p.id,
            )
        ).first()
        if clash is not None:
            raise conflict(
                f"channel {p.dispenser_channel} is already used by loaded paint {clash.id!r}",
                {"paint_id": clash.id},
            )
    if (p.parent_paint_id is None) != (p.dilution is None):
        raise bad_request(
            "bad_dilution", "parent_paint_id and dilution must be given together for a stock"
        )
    if p.parent_paint_id is not None:
        if p.parent_paint_id == p.id:
            raise bad_request("bad_dilution", "a paint cannot be its own parent")
        if session.get(m.Paint, p.parent_paint_id) is None:
            raise bad_request("unknown_paint", f"parent paint {p.parent_paint_id!r} not found")


def import_paints_csv(
    session: Session, text: str, only: Collection[str] | None = None
) -> PaintImportResult:
    """Upsert paints from CSV text (columns as in ``sample_data/paints.csv``).

    ``only`` restricts the import to those paint ids (other rows are ignored).
    """
    created: list[str] = []
    updated: list[str] = []
    errors: list[str] = []
    rows = list(csv.DictReader(io.StringIO(text)))
    if only is not None:
        rows = [r for r in rows if r.get("id") in set(only)]
    # place unloaded rows first so channel moves inside one file do not clash
    rows.sort(key=lambda r: (r.get("loaded", "").strip().lower() in ("1", "true", "yes"),))
    for n, r in enumerate(rows, start=2):
        data: dict[str, object] = {k: v for k, v in r.items() if k and v not in (None, "")}
        for b in ("loaded", "active"):
            if b in data:
                data[b] = str(data[b]).strip().lower() in ("1", "true", "yes")
        try:
            body = PaintCreate.model_validate(data)
            existing = session.get(m.Paint, body.id)
            p = existing or m.Paint(id=body.id, name=body.name)
            for k, v in body.model_dump().items():
                setattr(p, k, v)
            validate_paint(session, p)
            session.add(p)
            session.commit()
            (updated if existing else created).append(body.id)
        except ValidationError as e:
            session.rollback()
            errors.append(f"row {n}: {e.errors()[0]['loc']}: {e.errors()[0]['msg']}")
        except Exception as e:  # ApiError from _check
            session.rollback()
            errors.append(f"row {n}: {getattr(e, 'message', str(e))}")
    return PaintImportResult(created=created, updated=updated, errors=errors)


# --- colour library -------------------------------------------------------------------------


def _f(v: str | None) -> float | None:
    return float(v) if v not in (None, "") else None


def import_colors_csv(session: Session, text: str, source: str | None = None) -> ColorImportResult:
    """Upsert colour-library entries from CSV text: ``name``, ``source`` (optional) and one of
    ``hex`` | ``r,g,b`` (0-255) | ``L,a,b`` (D65) | ``r380..r730`` spectra. ``source`` overrides
    the column; existing (source, name) pairs are updated."""
    reader = csv.DictReader(io.StringIO(text))
    created = updated = 0
    errors: list[str] = []
    for n, r in enumerate(reader, start=2):
        name = (r.get("name") or "").strip()
        if not name:
            errors.append(f"row {n}: name is empty")
            continue
        src = source if source is not None else (r.get("source") or "").strip()
        try:
            spectrum = None
            if all(r.get(c) not in (None, "") for c in SPECTRUM_COLUMNS):
                spectrum = [float(r[c]) for c in SPECTRUM_COLUMNS]
            lab = None
            if all(_f(r.get(k)) is not None for k in ("L", "a", "b")):
                lab = [float(r["L"]), float(r["a"]), float(r["b"])]
            srgb = None
            if all(_f(r.get(k)) is not None for k in ("r", "g", "b")) and lab is None:
                srgb = [float(r["r"]) / 255, float(r["g"]) / 255, float(r["b"]) / 255]
            hx = (r.get("hex") or "").strip() or None
            if spectrum is None and lab is None and srgb is None and hx is None:
                raise ValueError("no colour columns (hex | r,g,b | L,a,b | r400..r700)")
            lab_v, rgb_v, hex_v, _ = color_from_input(hx, srgb, lab, spectrum)
        except (ValueError, ApiError) as exc:
            errors.append(f"row {n}: {getattr(exc, 'message', str(exc))}")
            continue
        e = session.exec(
            select(m.ColorLibraryEntry).where(
                m.ColorLibraryEntry.name == name, m.ColorLibraryEntry.source == src
            )
        ).first()
        if e is None:
            e = m.ColorLibraryEntry(name=name, source=src)
            created += 1
        else:
            updated += 1
        e.lab, e.srgb, e.hex, e.spectrum = lab_v, rgb_v, hex_v, spectrum
        e.notes = (r.get("notes") or "").strip()
        session.add(e)
    session.commit()
    return ColorImportResult(created=created, updated=updated, errors=errors)


# --- calibration ----------------------------------------------------------------------------


def report_out(rep: ValidationReport) -> ValidationReportOut:
    return ValidationReportOut(
        ok=rep.ok,
        n_rows=rep.n_rows,
        n_valid=len(rep.samples),
        n_errors=len(rep.errors),
        n_warnings=len(rep.warnings),
        issues=[ValidationIssueOut.model_validate(i.__dict__) for i in rep.issues],
        wavelengths_in=rep.wavelengths_in,
    )


def store_calibration(
    session: Session,
    text: str,
    filename: str = "upload.csv",
    mode: str = "append",
    allow_partial: bool = False,
) -> UploadResult:
    """Validate calibration CSV text and store its samples (upsert by sample_id).

    ``mode="replace"`` deletes every stored sample first. Nothing is stored when the file has
    errors unless ``allow_partial``.
    """
    rep = parse_calibration_csv(text, paint_infos(session))
    out = report_out(rep)
    if not rep.ok and not allow_partial:
        return UploadResult(report=out, upload_id=None, stored=0, replaced=0)
    if mode == "replace":
        session.exec(delete(m.CalibrationSample))
    up = m.CalibrationUpload(
        filename=filename,
        n_samples=len(rep.samples),
        issues=[i.__dict__ for i in rep.issues[:500]],
    )
    session.add(up)
    session.flush()
    replaced = 0
    for d in rep.samples:
        existing = session.get(m.CalibrationSample, d.sample_id)
        if existing is not None:
            session.delete(existing)
            session.flush()
            replaced += 1
        session.add(data_to_sample(d, up.id))
    session.commit()
    return UploadResult(report=out, upload_id=up.id, stored=len(rep.samples), replaced=replaced)


def create_fit_run(session: Session, body: FitRequest) -> m.FitRun:
    """Record a queued fit; the caller runs :func:`run_fit` (background or inline)."""
    if session.exec(select(m.CalibrationSample)).first() is None:
        raise bad_request("no_samples", "upload calibration samples before fitting")
    line = line_for_new_model(session, body.line)
    run = m.FitRun(options={**body.model_dump(), "line": line.slug})
    session.add(run)
    session.commit()
    session.refresh(run)
    return run


def run_fit(db_url: str, run_id: int) -> None:
    """Background job: fit, store a new model version, update the run row."""
    engine = get_engine(db_url)

    def update(**kw: object) -> None:
        with Session(engine) as s:
            run = s.get(m.FitRun, run_id)
            assert run is not None
            for k, v in kw.items():
                setattr(run, k, v)
            s.add(run)
            s.commit()

    update(status="running", started_at=utcnow(), message="loading samples", progress=0.01)
    try:
        with Session(engine) as s:
            run = s.get(m.FitRun, run_id)
            assert run is not None
            req = FitRequest.model_validate(run.options)
            settings = load_settings(s)
            paints = paint_infos(s)
            samples = [sample_to_data(x) for x in s.exec(select(m.CalibrationSample)).all()]
        opts = FitOptions(
            k1=req.k1 if req.k1 is not None else settings.saunderson_k1,
            k2=req.k2 if req.k2 is not None else settings.saunderson_k2,
            smoothness=req.smoothness,
            k_folds=req.k_folds,
        )
        result = fit_calibration(
            samples,
            paints,
            opts,
            progress=lambda f, msg: update(progress=0.02 + 0.93 * f, message=msg),
        )
        d = fit_result_to_dict(result)
        with Session(engine) as s:
            # the line was checked when the run was queued; recreate it if it was deleted since
            line = find_line(s, req.line or DEFAULT_LINE) or line_for_new_model(s, None)
            fm = m.FittedModel(
                version=0,
                line_id=0,
                label=req.label,
                paint_ids=d["paint_ids"],
                K=d["K"],
                S=d["S"],
                tau=d["tau"],
                k1=opts.k1,
                k2=opts.k2,
                substrate_white=d["substrate_white"],
                substrate_black=d["substrate_black"],
                diagnostics=clean_floats(
                    {**d["diagnostics"], "warnings": d["warnings"], "residuals": d["residuals"]}
                ),
                holdout_report=d["holdout"],
                n_samples=len(samples),
                fit_run_id=run_id,
                notes=req.notes,
            )
            place_model(s, fm, line)
            fm.paint_batches = current_batches(s, fm.paint_ids)
            if req.activate:
                set_active(s, fm)
            s.add(fm)
            s.commit()
            s.refresh(fm)
            model_id = fm.id
            created = f"model v{fm.version} ({model_ref(line.slug, fm.revision)}) created"
        update(
            status="succeeded",
            progress=1.0,
            finished_at=utcnow(),
            model_id=model_id,
            message=created + (" and activated" if req.activate else ""),
        )
    except FitError as e:
        update(status="failed", error=str(e), finished_at=utcnow(), message="fit failed")
    except Exception as e:  # pragma: no cover - unexpected
        update(
            status="failed",
            error=f"{type(e).__name__}: {e}\n{traceback.format_exc(limit=5)}",
            finished_at=utcnow(),
            message="fit crashed",
        )


# --- models ---------------------------------------------------------------------------------


def swatch_inputs(session: Session, paint_ids: list[str] | None) -> list[SwatchPaint]:
    """Swatch colours of ``paint_ids`` (default: every active paint with a ``swatch_hex``)."""
    paints = {p.id: p for p in all_paints(session)}
    if paint_ids is None:
        ids = [p.id for p in paints.values() if p.active and p.swatch_hex]
    else:
        ids = paint_ids
    unknown = [i for i in ids if i not in paints]
    if unknown:
        raise bad_request("unknown_paint", f"unknown paint ids: {', '.join(unknown)}")
    missing = [i for i in ids if not paints[i].swatch_hex]
    if missing:
        raise bad_request(
            "missing_swatch", f"paints without swatch_hex: {', '.join(missing)}", missing
        )
    if not ids:
        raise bad_request("empty_pool", "no paints with swatch colours")
    swatches = [
        SwatchPaint(
            p.id,
            PaintRole(p.role),
            srgb_to_lab(hex_to_srgb(p.swatch_hex or "")),
            srgb_to_lab(hex_to_srgb(p.tint_hex)) if p.tint_hex else None,
            p.tint_fraction or 0.1,
        )
        for p in (paints[i] for i in ids)
    ]
    return swatches


def store_swatch_model(
    session: Session,
    sm: SwatchModel,
    activate: bool,
    notes: str = "",
    *,
    line: m.ModelLine | None = None,
    label: str = "",
) -> m.FittedModel:
    """Store an uncalibrated swatch model as the next version of ``line`` (default line if
    omitted), optionally activating it."""
    fm = m.FittedModel(
        version=0,
        line_id=0,
        label=label,
        source="swatches",
        paint_ids=sm.paint_ids,
        K=np.round(sm.K, 7).tolist(),
        S=np.round(sm.S, 7).tolist(),
        tau=np.round(sm.tau, 9).tolist(),
        k1=sm.k1,
        k2=sm.k2,
        substrate_white=np.round(sm.substrate_white, 6).tolist(),
        substrate_black=np.round(sm.substrate_black, 6).tolist(),
        diagnostics={
            "warnings": sm.warnings,
            "scattering_source": sm.scattering_source,
            "tint_match_de": sm.tint_match_de,
        },
        holdout_report={
            "method": "none",
            "n_samples": 0,
            "mean_de": None,
            "median_de": None,
            "p95_de": None,
            "max_de": None,
            "mean_rms": None,
            "noise_floor_mean_de": None,
        },
        notes=notes or "uncalibrated: built from swatch colours",
    )
    place_model(session, fm, line or line_for_new_model(session, None))
    fm.paint_batches = current_batches(session, fm.paint_ids)
    if activate:
        set_active(session, fm)
    session.add(fm)
    session.commit()
    session.refresh(fm)
    return fm
