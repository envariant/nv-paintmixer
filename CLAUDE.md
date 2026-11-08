# CLAUDE.md — working notes for agents and contributors

## Layout

- `backend/` — Python 3.12 package `paintmixer` (uv project, `src/` layout)
  - `colorsci/` pure colour maths: spectral grid, XYZ/Lab/sRGB, dE2000, Kubelka-Munk. No web/DB imports.
  - `calibration/` CSV format + validator, JSON schema, synthetic data generator, K/S fit.
  - `solver/` recipe search, quantisation, metamerism, gamut.
  - `worksheet/` calibration drawdown planner.
  - `measurement/` `MeasurementSource` protocol + FileImport / Simulated / ArgyllSpotread / Camera stub, measure session.
  - `hardware/` dispenser protocol + simulator. `correction.py` closed-loop recipe correction.
  - `db/` SQLModel tables, engine/session, Alembic migrations (`backend/alembic/`).
  - `api/` FastAPI app (`api/app.py:create_app`), routers under `api/routers/`, all under `/api/v1`.
    Heavy work (solve, gamut, fit) goes through `api/compute.py` (process pool; `compute_workers=0`
    runs it in the thread pool instead, which the tests use).
  - `cli.py` Typer CLI (`uv run paintmixer --help`).
- `frontend/` Vue 3 + TS + Vite + Tailwind + Pinia. `src/api/schema.d.ts` is generated — do not edit.
- `design/` Claude Design handoff bundle goes in `design/handoff/` (needed before building UI pages).
- `docs/` format specs, assumptions, measurement setup. `sample_data/` synthetic calibration + library CSVs.

## Commands

```bash
make install        # uv sync + npm install
make dev            # FastAPI :8000 + Vite :5173 (proxies /api)
make test           # backend (not slow) + vitest
make test-slow      # solver accuracy/performance suites
make lint           # ruff check, ruff format --check, mypy --strict, vue-tsc
make gen-api        # export OpenAPI -> regenerate frontend client types
make sample-data    # regenerate sample_data/ from the synthetic generator
make e2e            # Playwright smoke test
```

Instrument tools (inside `backend/`): `uv run paintmixer measure selftest` (add `--source simulated`
without hardware) and `uv run paintmixer measure session --worksheet ... --out ...`.

Inside `backend/`: `uv run pytest tests/test_x.py -k name`, `uv run paintmixer ...`.

## Conventions

- Reflectance arrays are float64, shape `(..., 31)`, 0–1, on `colorsci.WAVELENGTHS` (400–700/10).
  Batch dimensions go first; functions are vectorised — never loop over bands in Python.
- Mixture fractions are **volume** fractions summing to 1. Masses are converted with density.
- Lab is CIE 1976 relative to the illuminant's perfect reflector; default D65 / CIE 1931 2°.
- Determinism: everything stochastic takes an explicit `seed` / `np.random.Generator`.
- Errors from the API use `{"error": {"code", "message", "details"}}`.
- Money is SGD by default (`settings.currency`); costs are per ml.
- mypy runs in strict mode; NumPy arrays are typed `NDArray[np.float64]` (`colorsci.types.FloatArray`).
- Tests: unit tests next to the concern in `backend/tests/test_<module>.py`; mark >5 s tests `@pytest.mark.slow`.
- Do **not** use Mixbox (non-commercial licence).
- Verify by running: after a change run the relevant tests and `make lint`.
- Record judgement calls in `docs/ASSUMPTIONS.md`; update the progress log in `PLAN.md` per milestone.
