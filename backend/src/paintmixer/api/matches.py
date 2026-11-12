"""Library match summaries: the closest recipe for every library colour under the active
model, cached in ``color_match`` and recomputed in the background.

A cached row is *fresh* while three things match what a solve would use now: the active model
version, the settings hash (solver options + loaded paint pool, :func:`settings_hash`) and the
colour hash (its Lab / spectrum). Anything else that changes makes the row stale, so no hook has
to delete rows; :func:`request_refresh` only makes sure a refresh runs.

The refresh is one asyncio task per app: it plans the stale colours, solves them through
:func:`paintmixer.api.compute.run_compute` (process pool, as many at a time as there are
workers), stores each result, and plans again until nothing is stale, so inputs that change
while it runs are picked up.
"""

from __future__ import annotations

import asyncio
import contextlib
import dataclasses
import hashlib
import json
import logging
from collections.abc import Iterator
from dataclasses import dataclass
from typing import Any, Literal

from anyio import to_thread
from fastapi import Depends, FastAPI, Request
from sqlmodel import Session, col, select

from paintmixer.api import events
from paintmixer.api.compute import run_compute
from paintmixer.api.errors import ApiError
from paintmixer.api.schemas import ColorMatchOut
from paintmixer.api.services import default_solve_options, load_settings, pool_model
from paintmixer.db import models as m
from paintmixer.db.models import utcnow
from paintmixer.db.session import get_engine
from paintmixer.solver.model import PoolModel
from paintmixer.solver.solve import SolveOptions, SolveResult, Target, solve

log = logging.getLogger(__name__)

Reach = Literal["within", "uncertain", "out"]


def _hash(obj: Any) -> str:
    return hashlib.sha256(json.dumps(obj, sort_keys=True, default=str).encode()).hexdigest()[:32]


def color_hash(e: m.ColorLibraryEntry) -> str:
    return _hash({"lab": e.lab, "spectrum": e.spectrum})


def settings_hash(opts: SolveOptions, model: PoolModel) -> str:
    pool = [
        (p.id, p.role.value, p.cost_per_ml, p.min_dose_ml, p.density_g_per_ml) for p in model.paints
    ]
    return _hash({"options": dataclasses.asdict(opts), "pool": pool})


def target_of(e: m.ColorLibraryEntry) -> Target:
    import numpy as np

    spec = np.array(e.spectrum) if e.spectrum else None
    return Target(np.array(e.lab), spec, e.name, "library")


@dataclass
class Plan:
    """What a solve would use now, and the colours whose cached match is not fresh."""

    version: int
    settings_hash: str
    model: PoolModel
    opts: SolveOptions
    todo: list[tuple[int, str, Target]]  # colour id, colour hash, target


def current(session: Session) -> tuple[int, str, PoolModel, SolveOptions] | None:
    """Model version, settings hash, model and options a library solve uses now; None when
    nothing can be solved (no active model, no loaded paints)."""
    try:
        model, fm = pool_model(session, None)
    except ApiError:
        return None
    opts = default_solve_options(session, load_settings(session), fm)
    return fm.version, settings_hash(opts, model), model, opts


def is_fresh(row: m.ColorMatch | None, e: m.ColorLibraryEntry, version: int, h: str) -> bool:
    return (
        row is not None
        and row.model_version == version
        and row.settings_hash == h
        and row.color_hash == color_hash(e)
    )


# (colour id, colour hash, model version, settings hash): a solve that failed with these
# inputs is not retried until one of them changes
FailKey = tuple[int, str, int, str]


def plan(session: Session, skip: set[FailKey] | None = None) -> Plan | None:
    cur = current(session)
    if cur is None:
        return None
    version, h, model, opts = cur
    rows = {r.color_id: r for r in session.exec(select(m.ColorMatch)).all()}
    todo = []
    for e in session.exec(select(m.ColorLibraryEntry).order_by(col(m.ColorLibraryEntry.id))):
        assert e.id is not None
        ch = color_hash(e)
        if (e.id, ch, version, h) in (skip or set()):
            continue
        if not is_fresh(rows.get(e.id), e, version, h):
            todo.append((e.id, ch, target_of(e)))
    return Plan(version, h, model, opts, todo)


def summarise(res: SolveResult, accept_tolerance_de: float) -> dict[str, Any] | None:
    """The cached fields for a solve result: its closest mix, and the colour's reach. ``out``
    when out of gamut; ``uncertain`` when inside but nearer the gamut's edge than the closest
    mix's uncertainty (or the accept tolerance, without one); ``within`` otherwise."""
    if not res.candidates:
        return None
    best = next((c for c in res.candidates if "closest" in c.tags), res.candidates[0])
    reach: Reach = "within"
    if res.in_gamut is False:
        reach = "out"
    elif res.gamut_margin_de is not None:
        edge = best.uncertainty_de if best.uncertainty_de is not None else accept_tolerance_de
        if res.gamut_margin_de < edge:
            reach = "uncertain"
    return {
        "de": round(best.de2000, 4),
        "n_paints": len(best.paint_ids),
        "cost_per_250ml": round(best.cost_per_ml * 250.0, 4),
        "reach": reach,
        "uncertainty_de": None if best.uncertainty_de is None else round(best.uncertainty_de, 3),
        "best_components": [
            {"paint_id": p, "fraction": round(f, 6)}
            for p, f in zip(best.paint_ids, best.fractions_quantised, strict=True)
        ],
    }


def store(session: Session, color_id: int, p: Plan, ch: str, fields: dict[str, Any]) -> None:
    if session.get(m.ColorLibraryEntry, color_id) is None:
        return  # deleted while it was being solved
    row = session.get(m.ColorMatch, color_id) or m.ColorMatch(color_id=color_id, **fields)
    for k, v in fields.items():
        setattr(row, k, v)
    row.model_version, row.settings_hash, row.color_hash = p.version, p.settings_hash, ch
    row.updated_at = utcnow()
    session.add(row)
    session.commit()
    session.refresh(row)
    events.publish(
        session,
        "match",
        {"color_id": color_id, "match": ColorMatchOut.model_validate(row, from_attributes=True)},
    )


async def refresh(app: FastAPI) -> None:
    """Solve every stale library colour, until none is left."""
    url = app.state.settings.database_url
    failed: set[FailKey] = app.state.match_failed  # kept across refreshes
    while True:

        def _plan() -> Plan | None:
            with Session(get_engine(url)) as s:
                return plan(s, failed)

        p = await to_thread.run_sync(_plan)
        hub: events.EventHub | None = getattr(app.state, "events", None)
        if p is None or not p.todo:
            if hub is not None:
                hub.publish("matches", {"state": "idle", "pending": 0})
            return
        if hub is not None:
            hub.publish("matches", {"state": "refreshing", "pending": len(p.todo)})
        tolerance = p.opts.accept_tolerance_de
        sem = asyncio.Semaphore(max(1, app.state.settings.compute_workers))

        async def one(
            cid: int,
            ch: str,
            target: Target,
            p: Plan = p,
            sem: asyncio.Semaphore = sem,
            tolerance: float = tolerance,
        ) -> None:
            try:
                async with sem:
                    res = await run_compute(
                        app, solve, p.model, target, p.opts, gamut_cache_key=p.version
                    )
                fields = summarise(res, tolerance)
            except Exception:  # pragma: no cover - logged, retried when its inputs change
                log.exception("library match for colour %s failed", cid)
                fields = None
            if fields is None:
                failed.add((cid, ch, p.version, p.settings_hash))
                return

            def _store() -> None:
                with Session(get_engine(url)) as s:
                    store(s, cid, p, ch, fields)

            await to_thread.run_sync(_store)

        await asyncio.gather(*(one(cid, ch, t) for cid, ch, t in p.todo))


def refresh_after(request: Request) -> Iterator[None]:
    """Route dependency: once the endpoint has run, refresh the library matches proactively
    (see :func:`request_refresh`). Nothing happens when nothing became stale."""
    yield
    request_refresh(request.app, proactive=True)


REFRESH_AFTER = [Depends(refresh_after)]


def _ensure(app: FastAPI) -> None:
    task: asyncio.Task[None] | None = getattr(app.state, "match_task", None)
    if task is None or task.done():
        app.state.match_task = asyncio.ensure_future(refresh(app))


def request_refresh(app: FastAPI, *, proactive: bool = False) -> None:
    """Make sure a refresh runs (safe from any thread). ``proactive`` refreshes (a model was
    activated, inputs changed) only run with ``Settings.match_cache_auto``; demand refreshes
    (someone asked for matches) always do. A refresh already running re-plans when it finishes
    its batch, so it picks the change up."""
    if proactive and not app.state.settings.match_cache_auto:
        return
    loop: asyncio.AbstractEventLoop | None = getattr(app.state, "loop", None)
    if loop is None or loop.is_closed():
        return
    loop.call_soon_threadsafe(_ensure, app)


async def stop(app: FastAPI) -> None:
    task: asyncio.Task[None] | None = getattr(app.state, "match_task", None)
    if task is not None and not task.done():
        task.cancel()
        with contextlib.suppress(asyncio.CancelledError):
            await task


def fresh_matches(
    session: Session, entries: list[m.ColorLibraryEntry]
) -> tuple[dict[int, m.ColorMatch], int]:
    """Fresh cached matches of ``entries`` and how many are still missing."""
    cur = current(session)
    if cur is None:
        return {}, 0
    version, h, _model, _opts = cur
    ids = [e.id for e in entries if e.id is not None]
    rows = {
        r.color_id: r
        for r in session.exec(select(m.ColorMatch).where(col(m.ColorMatch.color_id).in_(ids)))
    }
    fresh = {
        e.id: rows[e.id]
        for e in entries
        if e.id is not None and is_fresh(rows.get(e.id), e, version, h)
    }
    return fresh, len(ids) - len(fresh)
