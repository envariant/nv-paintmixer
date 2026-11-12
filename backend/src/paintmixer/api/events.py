"""Live events for ``GET /events`` (server-sent events).

One :class:`EventHub` per app collects what changes: a job's progress, the machine status, a
library match, the active model. Code that commits such a change publishes it with
:func:`publish`, from any thread (the job runner has its own). Code without the app at hand
finds the hub through the database engine its session uses (:func:`register`), since the
endpoints, the runner and the match cache all share it.

Every event gets an id ``<boot>:<n>``. The hub keeps the last :data:`BUFFER` events, so a client
that reconnects with ``Last-Event-ID`` gets what it missed. If those events are gone, or the
id comes from an earlier server run (another ``boot``), the client is told to ``reset``:
refetch its state, then follow the stream.

The stream is in-process: the server must run as a single worker, which the job runner
needs anyway (one machine).
"""

from __future__ import annotations

import asyncio
import json
import secrets
import threading
from collections import deque
from dataclasses import dataclass, field
from typing import Any

from pydantic import BaseModel
from pydantic_core import to_jsonable_python
from sqlalchemy.engine import Engine
from sqlmodel import Session

BUFFER = 1000  # events kept for resuming
QUEUE = 1000  # events a slow client may fall behind before it is reset
TYPES = ("job", "machine", "match", "matches", "model")


@dataclass(frozen=True)
class Event:
    id: str
    type: str
    data: dict[str, Any]
    seq: int

    def sse(self) -> str:
        payload = json.dumps(self.data, separators=(",", ":"), default=str)
        return f"id: {self.id}\nevent: {self.type}\ndata: {payload}\n\n"


@dataclass(eq=False)
class Subscriber:
    queue: asyncio.Queue[Event] = field(default_factory=lambda: asyncio.Queue(QUEUE))
    overflow: bool = False

    def offer(self, ev: Event) -> None:  # on the event loop
        try:
            self.queue.put_nowait(ev)
        except asyncio.QueueFull:
            self.overflow = True


class EventHub:
    def __init__(self) -> None:
        self.boot = secrets.token_hex(4)
        self.loop: asyncio.AbstractEventLoop | None = None
        self._lock = threading.Lock()
        self._seq = 0
        self._buffer: deque[Event] = deque(maxlen=BUFFER)
        self._subscribers: set[Subscriber] = set()

    @property
    def last_id(self) -> str:
        return f"{self.boot}:{self._seq}"

    def publish(self, type_: str, data: BaseModel | dict[str, Any]) -> Event:
        """Record an event and deliver it to every subscriber (safe from any thread)."""
        body: dict[str, Any] = to_jsonable_python(data)  # nested models too
        with self._lock:
            self._seq += 1
            ev = Event(f"{self.boot}:{self._seq}", type_, body, self._seq)
            self._buffer.append(ev)
            subscribers = list(self._subscribers)
        loop = self.loop
        if loop is not None and not loop.is_closed():
            for s in subscribers:
                loop.call_soon_threadsafe(s.offer, ev)
        return ev

    def subscribe(self, last_event_id: str | None) -> tuple[Subscriber, list[Event], bool]:
        """A new subscriber, the buffered events after ``last_event_id`` and whether the
        client must reset (its id is unknown, from another boot, or no longer buffered)."""
        s = Subscriber()
        with self._lock:
            self._subscribers.add(s)
            if last_event_id is None:
                return s, [], False
            boot, _, n = last_event_id.partition(":")
            if boot != self.boot or not n.isdigit() or int(n) > self._seq:
                return s, [], True
            after = int(n)
            oldest = self._buffer[0].seq if self._buffer else self._seq + 1
            if after < oldest - 1:
                return s, [], True
            return s, [e for e in self._buffer if e.seq > after], False

    def unsubscribe(self, s: Subscriber) -> None:
        with self._lock:
            self._subscribers.discard(s)

    @property
    def n_subscribers(self) -> int:
        with self._lock:
            return len(self._subscribers)


_HUBS: dict[int, EventHub] = {}  # id(engine) -> hub
_HUBS_LOCK = threading.Lock()


def register(engine: Engine, hub: EventHub | None) -> None:
    with _HUBS_LOCK:
        if hub is None:
            _HUBS.pop(id(engine), None)
        else:
            _HUBS[id(engine)] = hub


def hub_for(session: Session) -> EventHub | None:
    with _HUBS_LOCK:
        return _HUBS.get(id(session.get_bind()))


def publish(session: Session, type_: str, data: BaseModel | dict[str, Any]) -> None:
    """Publish to the hub of the app ``session`` belongs to (no-op without one, e.g. CLI)."""
    hub = hub_for(session)
    if hub is not None:
        hub.publish(type_, data)
