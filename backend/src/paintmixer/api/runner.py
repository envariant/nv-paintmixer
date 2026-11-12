"""The machine: runs dispense jobs one at a time on a background thread.

``POST /jobs/{id}/dispense`` queues the job (``queued``) and returns. The runner then, per round:

1. ``pouring``: dispenses the recipe (or the pending correction additions) channel by
   channel through the dispenser protocol (:mod:`paintmixer.hardware.protocol`): the simulated
   firmware, or the real dispenser over the transport in settings;
2. ``measuring``: simulated runs read the cup with the simulated instrument. Real runs stop at
   ``dispensed`` until a measurement is entered (``POST /jobs/{id}/measurement``);
3. within ``accept_tolerance_de`` the job is ``done``; otherwise it corrects itself
   (``correcting``) and pours again while ``auto_correct_rounds`` last, then waits in
   ``measured`` for Accept or Correct again (``needs_attention`` at the iteration cap).

Pause and cancel act between channels: a pause waits before the next channel; a cancel stops
there, keeps what was poured in the cup and ends the job ``cancelled``. ``step`` and
``progress`` on the job say where it is. Jobs left running when the server stopped are marked
``needs_attention`` on the next start (:func:`recover_interrupted`).
"""

from __future__ import annotations

import logging
import threading
from collections import deque
from collections.abc import Callable
from dataclasses import dataclass, field
from typing import Any

from sqlmodel import Session, col, select

from paintmixer.api.jobs_core import (
    apply_correction,
    apply_measurement,
    apply_pour,
    channels_for,
    poured_ml,
    save,
    simulated_reading,
    to_dispense,
)
from paintmixer.api.schemas import AppSettings
from paintmixer.api.services import all_paints, load_settings
from paintmixer.colorsci.convert import reflectance_to_lab
from paintmixer.db import models as m
from paintmixer.db.models import utcnow
from paintmixer.db.session import get_engine
from paintmixer.hardware.dispenser import DispenserError, DispenseResult, SimulatedDispenser
from paintmixer.hardware.firmware_sim import LoopbackTransport, SimulatedFirmware
from paintmixer.hardware.protocol import ProtocolDispenser
from paintmixer.hardware.transports import open_transport

log = logging.getLogger(__name__)

RUNNING = ("queued", "pouring", "measuring")  # only while the runner holds the job
MAX_ITERATIONS = 5  # correction rounds before a job needs attention (as POST /correct)
POUR_SHARE = 0.85  # progress through a round when the pour is complete


@dataclass(frozen=True)
class RunOptions:
    simulate: bool = True
    seed: int | None = None
    rel_sigma: float = 0.01
    abs_sigma_ml: float = 0.01
    measure: bool = True
    auto_correct_rounds: int = 0
    ml_per_s: float | None = None
    gain: float = 1.0  # simulated measurement bias


@dataclass
class _Control:
    resume: threading.Event = field(default_factory=threading.Event)
    cancel: bool = False
    reason: str = ""

    def __post_init__(self) -> None:
        self.resume.set()


class _Cancelled(Exception):
    pass


class _Interrupted(Exception):
    pass


class MachineRunner:
    def __init__(self, database_url: str) -> None:
        self.url = database_url
        self._cv = threading.Condition()
        self._queue: deque[tuple[int, RunOptions]] = deque()
        self._controls: dict[int, _Control] = {}
        self._current: int | None = None
        self._thread: threading.Thread | None = None
        self._stopping = False

    # -- control (any thread) --------------------------------------------------------------------

    def submit(self, job_id: int, opts: RunOptions) -> None:
        with self._cv:
            self._queue.append((job_id, opts))
            self._controls[job_id] = _Control()
            if self._thread is None or not self._thread.is_alive():
                self._thread = threading.Thread(target=self._loop, name="machine", daemon=True)
                self._thread.start()
            self._cv.notify()

    def holds(self, job_id: int) -> bool:
        with self._cv:
            return job_id in self._controls

    def pause(self, job_id: int, record: Callable[[], None] | None = None) -> bool:
        """Pause before the next channel. ``record`` (persisting the paused flag) runs while
        the runner still holds the job, so it cannot land after the job has finished. False
        if the runner does not hold the job."""
        with self._cv:
            c = self._controls.get(job_id)
            if c is None:
                return False
            c.resume.clear()
            if record is not None:
                record()
        return True

    def resume(self, job_id: int) -> bool:
        with self._cv:
            c = self._controls.get(job_id)
        if c is None:
            return False
        c.resume.set()
        return True

    def cancel(self, job_id: int, reason: str) -> bool:
        """Cancel a queued job now, or a running one at its next channel. False if the runner
        does not hold the job."""
        with self._cv:
            c = self._controls.get(job_id)
            if c is None:
                return False
            queued = next((q for q in self._queue if q[0] == job_id), None)
            if queued is not None:
                self._queue.remove(queued)
                del self._controls[job_id]
        if queued is not None:
            with Session(get_engine(self.url)) as s:
                j = s.get(m.Job, job_id)
                if j is not None:
                    _cancelled(j, reason)
                    save(s, j)
            return True
        c.cancel, c.reason = True, reason
        c.resume.set()  # a paused job wakes up to stop
        return True

    def stop(self, timeout: float = 10.0) -> None:
        with self._cv:
            self._stopping = True
            for c in self._controls.values():
                c.resume.set()
            self._cv.notify_all()
            t = self._thread
        if t is not None:
            t.join(timeout)

    # -- the machine thread -----------------------------------------------------------------------

    def _loop(self) -> None:
        while True:
            with self._cv:
                while not self._queue and not self._stopping:
                    self._cv.wait()
                if self._stopping:
                    return
                job_id, opts = self._queue.popleft()
                self._current = job_id
                ctl = self._controls[job_id]
            try:
                self._run(job_id, opts, ctl)
            except Exception as e:  # pragma: no cover - logged, the job needs attention
                log.exception("job %s failed on the machine", job_id)
                self._update(job_id, status="needs_attention", step=f"Machine error: {e}")
            finally:
                # let go of the job first: once it reads running=false, pause / resume /
                # cancel are refused, and a pause recorded before this is cleared below
                with self._cv:
                    self._controls.pop(job_id, None)
                    self._current = None
                self._update(job_id, running=False, paused=False)

    def _update(self, job_id: int, **fields: Any) -> None:
        with Session(get_engine(self.url)) as s:
            j = s.get(m.Job, job_id)
            if j is None:
                return
            for k, v in fields.items():
                setattr(j, k, v)
            save(s, j)

    def _checkpoint(self, job_id: int, ctl: _Control) -> None:
        """Between channels: wait out a pause, stop on cancel or shutdown."""
        if not ctl.resume.is_set() and not ctl.cancel:
            self._update(job_id, paused=True, step="Paused")
            while not ctl.resume.wait(0.1):
                if self._stopping:
                    break
            self._update(job_id, paused=False)
        if ctl.cancel:
            raise _Cancelled
        if self._stopping:
            raise _Interrupted

    def _dispenser(self, s: Session, j: m.Job, opts: RunOptions) -> ProtocolDispenser:
        settings = load_settings(s)
        if opts.simulate:
            seed = opts.seed if opts.seed is not None else (j.id or 0) * 100 + len(j.corrections)
            fw = SimulatedFirmware(
                SimulatedDispenser(
                    resolution_ml=settings.dispenser_resolution_ml,
                    rel_sigma=opts.rel_sigma,
                    abs_sigma_ml=opts.abs_sigma_ml,
                    seed=seed,
                ),
                channels=max(settings.dispenser_channels, *channels_for(s, j).values()),
                ml_per_s=opts.ml_per_s,
            )
            return ProtocolDispenser(LoopbackTransport(fw))
        return ProtocolDispenser(
            open_transport(settings.dispenser_transport, settings.dispenser_address)
        )

    def _run(self, job_id: int, opts: RunOptions, ctl: _Control) -> None:
        with Session(get_engine(self.url)) as s:
            j = s.get(m.Job, job_id)
            if j is None:
                return
            try:
                disp = self._dispenser(s, j, opts)
                name = disp.name
            except DispenserError as e:
                j.status, j.step = "needs_attention", f"Dispenser unavailable: {e}"
                save(s, j)
                return
            settings = load_settings(s)
        rounds_left = opts.auto_correct_rounds
        try:
            while True:
                if not self._pour(job_id, ctl, disp, name):
                    return
                if not (opts.simulate and opts.measure):
                    self._update(job_id, step="Waiting for a measurement", progress=1.0)
                    return
                self._checkpoint(job_id, ctl)
                if not self._measure_and_decide(job_id, opts, settings, rounds_left):
                    return
                rounds_left -= 1
        except _Cancelled:
            with Session(get_engine(self.url)) as s:
                j = s.get(m.Job, job_id)
                if j is not None:
                    _cancelled(j, ctl.reason)
                    save(s, j)
        except _Interrupted:
            self._update(
                job_id,
                status="needs_attention",
                step="Interrupted: the server stopped while this job was running",
                paused=False,
            )
        finally:
            disp.close()

    def _pour(self, job_id: int, ctl: _Control, disp: ProtocolDispenser, name: str) -> bool:
        """Pour the round channel by channel; False if it ended the job (dispenser error)."""
        with Session(get_engine(self.url)) as s:
            j = s.get(m.Job, job_id)
            assert j is not None
            items = [(p, v) for p, v in to_dispense(j).items() if v > 0]
            chans = channels_for(s, j)
            names = {p.id: p.name for p in all_paints(s)}
            j.status, j.progress, j.step = "pouring", 0.0, "Pouring"
            save(s, j)
        total = sum(v for _p, v in items) or 1.0
        results: list[DispenseResult] = []
        done = 0.0
        try:
            for i, (pid, v) in enumerate(items):
                self._checkpoint(job_id, ctl)
                self._update(
                    job_id,
                    step=f"Pouring {names.get(pid, pid)} · {i + 1} of {len(items)}",
                    progress=round(POUR_SHARE * done / total, 4),
                )
                actual = disp.dispense(chans[pid], v)
                results.append(DispenseResult(pid, chans[pid], float(v), actual))
                done += v
        except (_Cancelled, _Interrupted):
            self._record_pour(job_id, results, name)
            raise
        except DispenserError as e:
            self._record_pour(job_id, results, name)
            self._update(job_id, status="needs_attention", step=f"Dispenser error: {e}")
            return False
        self._record_pour(job_id, results, name)
        self._update(job_id, progress=POUR_SHARE, step="Poured")
        return True

    def _record_pour(self, job_id: int, results: list[DispenseResult], name: str) -> None:
        if not results:
            return
        with Session(get_engine(self.url)) as s:
            j = s.get(m.Job, job_id)
            assert j is not None
            apply_pour(s, j, results, name)
            save(s, j)

    def _measure_and_decide(
        self, job_id: int, opts: RunOptions, settings: AppSettings, rounds_left: int
    ) -> bool:
        """Measure the cup and decide; True to pour another (correction) round."""
        self._update(job_id, status="measuring", step="Measuring", progress=0.9)
        with Session(get_engine(self.url)) as s:
            j = s.get(m.Job, job_id)
            assert j is not None
            seed = None if opts.seed is None else opts.seed * 1000 + len(j.corrections)
            spectrum = simulated_reading(s, j, seed=seed, gain=opts.gain)
            de = apply_measurement(s, j, reflectance_to_lab(spectrum), spectrum, simulated=True)
            tol = settings.accept_tolerance_de
            j.progress = 1.0
            if de <= tol or rounds_left > 0:
                apply_correction(
                    s,
                    j,
                    tolerance=tol,
                    max_iterations=MAX_ITERATIONS,
                    resolution_ml=settings.dispenser_resolution_ml,
                )
            j.step = {
                "done": f"Within tolerance (dE {de:.2f}): done",
                "needs_attention": f"dE {de:.2f} after {MAX_ITERATIONS} corrections",
                "correcting": f"dE {de:.2f}: correcting",
                "measured": f"dE {de:.2f}: accept or correct again",
            }.get(j.status, j.step)
            save(s, j)
            return j.status == "correcting"


def _cancelled(j: m.Job, reason: str) -> None:
    j.corrections = [
        *j.corrections,
        {
            "iteration": j.recipe.get("iteration", 0),
            "result": "cancelled",
            "poured_ml": poured_ml(j),
            "reason": reason,
            "at": utcnow().isoformat(),
        },
    ]
    j.status, j.step, j.paused, j.running = "cancelled", "Cancelled", False, False


def recover_interrupted(database_url: str) -> int:
    """Jobs the runner held when the server stopped need attention; returns how many."""
    with Session(get_engine(database_url)) as s:
        jobs = s.exec(
            select(m.Job).where(col(m.Job.running) | col(m.Job.status).in_(RUNNING))
        ).all()
        for j in jobs:
            j.status, j.paused, j.running = "needs_attention", False, False
            j.step = "Interrupted: the server stopped while this job was running"
            save(s, j)
        return len(jobs)
