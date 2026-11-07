"""Calibration worksheet generation (JSON plan, CSV skeleton, printable HTML)."""

from __future__ import annotations

from fastapi import APIRouter
from fastapi.responses import HTMLResponse, PlainTextResponse
from sqlmodel import Session

from paintmixer.api.deps import SessionDep
from paintmixer.api.errors import ERROR_RESPONSES, bad_request
from paintmixer.api.schemas import WorksheetRequest, WorksheetResponse
from paintmixer.api.services import all_paints, load_settings, paint_info
from paintmixer.domain import PaintInfo
from paintmixer.worksheet.plan import WorksheetOptions, WorksheetPlan, plan_worksheet
from paintmixer.worksheet.render import plan_to_csv, plan_to_dict, plan_to_html

router = APIRouter(prefix="/worksheet", tags=["worksheet"], responses=ERROR_RESPONSES)


def _plan(body: WorksheetRequest, session: Session) -> tuple[WorksheetPlan, dict[str, PaintInfo]]:
    paints = {p.id: p for p in all_paints(session)}
    ids = (
        body.paint_ids
        if body.paint_ids is not None
        else [p.id for p in paints.values() if p.active]
    )
    unknown = [i for i in ids if i not in paints]
    if unknown:
        raise bad_request("unknown_paint", f"unknown paint ids: {', '.join(unknown)}")
    if not ids:
        raise bad_request("empty_pool", "no paints selected")
    s = load_settings(session)
    o = body.options
    opts = WorksheetOptions(
        batch_g=o.batch_g or s.worksheet_batch_g,
        scale_resolution_g=o.scale_resolution_g or s.worksheet_scale_resolution_g,
        standard_gap_um=o.standard_gap_um or s.worksheet_gap_um,
        white_gaps_um=tuple(o.white_gaps_um),
        holdout_every=o.holdout_every,
        n_neutral_per_level=o.n_neutral_per_level,
        n_dark=o.n_dark,
        n_random=o.n_random,
        max_paints=o.max_paints,
        seed=o.seed,
        spare_fraction=o.spare_fraction,
        include_pairs=o.include_pairs,
    )
    infos = {i: paint_info(paints[i]) for i in ids}
    return plan_worksheet([infos[i] for i in ids], opts), infos


@router.post("", response_model=WorksheetResponse)
def generate_worksheet(body: WorksheetRequest, session: SessionDep) -> WorksheetResponse:
    plan, infos = _plan(body, session)
    return WorksheetResponse.model_validate(plan_to_dict(plan, infos))


@router.post("/csv", response_class=PlainTextResponse)
def worksheet_csv(body: WorksheetRequest, session: SessionDep) -> PlainTextResponse:
    """Calibration CSV skeleton with blank spectra and weighed-mass columns."""
    plan, _ = _plan(body, session)
    return PlainTextResponse(
        plan_to_csv(plan),
        media_type="text/csv",
        headers={"Content-Disposition": 'attachment; filename="calibration_worksheet.csv"'},
    )


@router.post("/html", response_class=HTMLResponse)
def worksheet_html(body: WorksheetRequest, session: SessionDep) -> HTMLResponse:
    """Printable worksheet with blank actual-weight fields and reading tick boxes."""
    plan, infos = _plan(body, session)
    return HTMLResponse(plan_to_html(plan, infos, body.title))
