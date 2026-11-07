"""Off-event-loop execution of heavy NumPy/SciPy work.

Solver, gamut and fit calls run in a process pool (``Settings.compute_workers`` > 0) so they
neither block the event loop nor compete with request handling for the GIL; with 0 workers they
run in the default thread pool (used by the tests).
"""

from __future__ import annotations

import asyncio
import multiprocessing as mp
from collections.abc import Callable
from concurrent.futures import Executor, Future, ProcessPoolExecutor
from functools import partial
from typing import Any

from fastapi import FastAPI
from starlette.concurrency import run_in_threadpool


def make_executor(workers: int) -> Executor | None:
    if workers <= 0:
        return None
    # spawn: safe on macOS and with threads; workers stay alive for the app's lifetime
    return ProcessPoolExecutor(max_workers=workers, mp_context=mp.get_context("spawn"))


async def run_compute[T](app: FastAPI, fn: Callable[..., T], *args: Any, **kwargs: Any) -> T:
    ex: Executor | None = getattr(app.state, "executor", None)
    call = partial(fn, *args, **kwargs)
    if ex is None:
        return await run_in_threadpool(call)
    return await asyncio.get_running_loop().run_in_executor(ex, call)


def submit_background(app: FastAPI, fn: Callable[..., Any], *args: Any) -> Future[Any] | None:
    """Fire-and-forget in the process pool; returns None when no pool (caller uses threads)."""
    ex: Executor | None = getattr(app.state, "executor", None)
    if ex is None:
        return None
    return ex.submit(fn, *args)
