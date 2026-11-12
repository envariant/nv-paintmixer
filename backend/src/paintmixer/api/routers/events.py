"""GET /events: live events as server-sent events (see :mod:`paintmixer.api.events`)."""

from __future__ import annotations

import asyncio
import json
from collections.abc import AsyncIterator
from typing import Any

from fastapi import APIRouter, Header, Query, Request
from fastapi.responses import StreamingResponse
from starlette.concurrency import run_in_threadpool

from paintmixer.api.deps import SessionDep
from paintmixer.api.errors import ERROR_RESPONSES, bad_request
from paintmixer.api.events import TYPES, Event, EventHub
from paintmixer.api.machine_state import machine_snapshot

router = APIRouter(tags=["events"], responses=ERROR_RESPONSES)

KEEPALIVE_S = 15.0
RETRY_MS = 3000

DESCRIPTION = """Live events (``text/event-stream``), for an ``EventSource``. Polling
``GET /jobs/{id}`` and ``GET /machine`` stays available and returns the same data.

Event types (``event:`` field; ``data:`` is JSON):

* ``job``: a job changed: a ``JobBrief`` (status, step, progress, paused, running, round, last
  dE and colour);
* ``machine``: the machine status (as ``GET /machine``); also sent once on connect;
* ``match``: a library colour's cached match: ``{color_id, match}``;
* ``matches``: the library refresh: ``{state: refreshing | idle, pending}``;
* ``model``: ``{event: created | activated, model}``;
* ``hello``: first, on connect: ``{boot, last_event_id, types}``;
* ``reset``: the stream cannot say what was missed (resumed from an unknown or expired id, or the
  client fell too far behind): refetch the state you show, then keep listening.

Every event except ``hello``, ``reset`` and the connect snapshot has an ``id``; the browser
sends the last one back as ``Last-Event-ID`` when it reconnects, and missed events are
replayed. Comments (``: keepalive``) are sent every 15 s.
"""


def _plain(type_: str, data: dict[str, Any]) -> str:
    return f"event: {type_}\ndata: {json.dumps(data, separators=(',', ':'), default=str)}\n\n"


@router.get(
    "/events",
    response_class=StreamingResponse,
    responses={200: {"content": {"text/event-stream": {}}, "description": "Event stream"}},
    description=DESCRIPTION,
)
async def event_stream(
    request: Request,
    session: SessionDep,
    types: str | None = Query(None, description="Comma-separated event types; default: all"),
    job_id: int | None = Query(None, description="Only job events of this job"),
    limit: int | None = Query(None, ge=1, description="Close after this many events"),
    last_event_id: str | None = Query(
        None, description="Resume after this event (the Last-Event-ID header takes precedence)"
    ),
    last_event_id_header: str | None = Header(None, alias="Last-Event-ID"),
) -> StreamingResponse:
    wanted = set(types.split(",")) if types else set(TYPES)
    unknown = sorted(wanted - set(TYPES))
    if unknown:
        raise bad_request("unknown_event_type", f"unknown event types: {', '.join(unknown)}")
    hub: EventHub = request.app.state.events
    resume = last_event_id_header or last_event_id
    snapshot = None
    if resume is None and "machine" in wanted:
        snapshot = (await run_in_threadpool(machine_snapshot, session)).model_dump(mode="json")
    sub, backlog, reset = hub.subscribe(resume)

    def wants(ev: Event) -> bool:
        if ev.type not in wanted:
            return False
        return job_id is None or ev.type != "job" or ev.data.get("id") == job_id

    async def stream() -> AsyncIterator[str]:
        sent = 0
        try:
            yield f"retry: {RETRY_MS}\n\n"
            yield _plain(
                "hello", {"boot": hub.boot, "last_event_id": hub.last_id, "types": sorted(wanted)}
            )
            if reset:
                yield _plain("reset", {"reason": "unknown or expired Last-Event-ID"})
            if snapshot is not None:
                yield _plain("machine", snapshot)
                sent += 1
            for ev in backlog:
                if limit is not None and sent >= limit:
                    return
                if wants(ev):
                    yield ev.sse()
                    sent += 1
            while limit is None or sent < limit:
                if sub.overflow:
                    yield _plain("reset", {"reason": "the client fell behind"})
                    return
                try:
                    ev = await asyncio.wait_for(sub.queue.get(), KEEPALIVE_S)
                except TimeoutError:
                    yield ": keepalive\n\n"
                    continue
                if wants(ev):
                    yield ev.sse()
                    sent += 1
        finally:
            hub.unsubscribe(sub)

    return StreamingResponse(
        stream(),
        media_type="text/event-stream",
        headers={"Cache-Control": "no-cache", "X-Accel-Buffering": "no"},
    )
