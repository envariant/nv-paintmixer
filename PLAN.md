# PaintMixer — implementation plan

PaintMixer computes paint-mixing recipes that reproduce a target colour. It models paints with
two-constant Kubelka-Munk (K-M) theory fitted from spectrophotometer drawdowns, searches subsets
of the available paints for the best match, and will later drive a dispensing machine.

## Architecture

```
frontend (Vue 3 + Vite)  ──/api/v1──▶  FastAPI app  ──▶  services  ──▶  pure libraries
                                         │                    │          colorsci  (colour maths, K-M)
                                         │                    │          calibration (format, fit, synthetic)
                                         ▼                    │          solver    (subset search, gamut)
                                  SQLite (SQLModel/Alembic)   │          worksheet (drawdown planner)
                                                              ▼
                                               hardware abstractions (protocols + simulators)
                                               measurement: FileImport | Simulated | ArgyllSpotread | Camera
                                               dispenser:   Simulated (real driver later)
```

Dependency rule: `colorsci` imports only NumPy/SciPy/colour-science. `calibration`, `solver`,
`worksheet`, `measurement`, `hardware` import `colorsci` but never the web or DB layers. The API
layer (`api/`) and the persistence layer (`db/`) sit on top and convert between DB rows and plain
dataclasses/arrays.

## Key technical decisions

| Topic | Decision |
|---|---|
| Spectral grid | 36 bands, 380–730 nm at 10 nm (the ColorMunki/i1Studio range; was 400–700 nm until the "380–730" change, migration `0002`); inputs must cover 400–700 nm, other grids are linearly resampled and edge-held. |
| Colorimetry | Weighting matrix `W[3,31]` per illuminant from colour-science CMFs (CIE 1931 2°) and SPDs, normalised so a perfect reflector has Y = 100. Lab white = that reflector. |
| dE2000 | Own vectorised implementation, verified against Sharma et al. (2005) data and cross-checked with `colour.delta_E`. |
| K-M | `k = Σc K / Σc S`, `R∞ = 1 + k − √(k² + 2k)`, Saunderson with configurable k1, k2. Finite-thickness (Kubelka 1948 hyperbolic) form for drawdowns over the black/white substrates. |
| Scale ambiguity | `S_white(λ) = 1`. A per-band optical-thickness scale `τ(λ)` (white scattering per µm of wet gap) is fitted from the white thickness series. |
| Fit | `scipy.optimize.least_squares` (TRF, soft_l1) on log-K/log-S, sparse finite-difference Jacobian (bands are nearly independent), second-difference smoothness penalty. |
| Solver | All subsets screened at once with a batched, vectorised Levenberg–Marquardt on Lab; top subsets refined with multi-start SLSQP on the full objective (dE2000 + secondary terms); quantised by local integer search. Staged greedy/swap search for large pools. |
| Compute off the event loop | Fits run as background tasks with a status row; `/solve` and friends run in the threadpool. |
| Hardware | `typing.Protocol` interfaces with simulators; spotread via pexpect, parser tested on a committed transcript. |

## Milestones

| | Scope | Status |
|---|---|---|
| M0 | Scaffold, make targets, docs skeleton | done |
| M1 | Colour science + K-M + tests | done |
| M2 | Data model, calibration format + validator + JSON schema, synthetic data | done |
| M3 | Calibration fit + report | done |
| M4 | Solver + gamut + scaling tests | done |
| M5 | Worksheet generator + full API | done |
| M6 | Frontend from the Claude Design handoff | **blocked**: no `design/handoff/` bundle; API client, stores, composables + Vitest done |
| M7 | Measurement sources, spotread parser, `paintmixer measure session` | done |
| M8 | Dispenser simulator, closed-loop correction, jobs | done |
| M9 | Hardening + docs | done |

Progress notes per milestone are appended below as work completes.

## Progress log
- **M0** Scaffold: uv backend with `/api/v1/health`, Vite/Vue/Tailwind frontend with the `/api` proxy, Makefile.
- **M1** `paintmixer.colorsci`: ASTM E2022 10 nm weights (D65/D50/A/F11), XYZ/Lab/sRGB with
  out-of-gamut flag, dE2000 matching all 34 Sharma pairs (pair 14 included) and colour-science on
  2000 random pairs, K-M R∞ / finite layer / Saunderson with analytic derivatives, Jakob-2019
  spectral recovery.
- **M2** SQLModel tables + Alembic `0001` (migrations verified against models in tests), calibration
  CSV parser/validator with line+column issues, JSON Schema (`docs/calibration_row.schema.json`),
  worksheet planner (pure), synthetic generator with known K/S, `sample_data/` (5- and 9-paint sets).
- **M3** `calibration.fit`: joint TRF/soft_l1 fit of log K, log S, log τ (S_white = 1) with
  second-difference smoothness and a sparse FD Jacobian; masstone + white-tint NNLS initialisation;
  flagged hold-out or k-fold CV; per-sample RMS/dE2000, RMS-based outlier flags, data-sufficiency
  warnings, and a measurement-noise floor so hold-out dE can be read in context. 9 paints / 234
  samples fit in ~1 s. `paintmixer fit` CLI prints the report.
- **M4** `solver`: analytic Lab Jacobian; batched LM screening of all subsets (softmax-simplex
  with min fraction; starts at equal fractions and K/S-space NNLS on the target spectrum, measured
  or Jakob-2019 reconstructed); staged greedy-beam + swap search for pools > 14; multi-start
  SLSQP on dE2000 + paints + cost + metamerism; quantisation by local integer search; dose
  sensitivity; log-uniform sampled a*b* gamut slices. Measured: 12 paints ~0.7 s, 20 paints
  ~0.8 s; staged within 0.15 dE of exhaustive over 200 targets (n=12).
- **M5** Worksheet JSON / CSV skeleton / printable HTML; `/api/v1` with paints (loaded/channel
  rules, diluted stocks, CSV import), settings, colour library (+CSV import), worksheet,
  calibration validate/upload/samples, background fit with status, model versions (activate,
  spectra), `/solve`, `/predict`, `/gamut`; error envelope; OpenAPI exported to
  `backend/openapi.json` and the typed frontend client generated from it.
- **M7** `MeasurementSource` protocol; FileImport, Simulated (noise + gain/offset bias), Camera
  stub; ArgyllSpotread pexpect wrapper (calibration, retry and no-instrument handling) with a
  pure parser; resumable `paintmixer measure session` (3 readings, mean + spread, 0.5 dE repeat
  warning, optional weighed masses). Format strings were checked against the ArgyllCMS 3.1.0
  binary; the wrapper is tested end-to-end against a pty fake (`tests/data/spotread`).
- **M8** `Dispenser` protocol + `SimulatedDispenser` (bias, relative/absolute error, pump
  resolution); damped Gauss-Newton correction on the simplex tangent space with step cap;
  "additions" mode (paint can only be added to the cup) and "remix" mode; closed loop converges
  in tests against a deliberately biased model; jobs API (create → dispense → measure → correct,
  iteration cap → `needs_attention`); every measurement logged to `correction_log` as training
  data for a later learned correction.
- **M6 (partial)** No design handoff bundle was found in `design/handoff/` (or the session), so
  no UI pages or design tokens were built. Done without inventing a design: OpenAPI-generated
  typed client, Pinia stores (paints with loaded-set warnings, mixer, calibration), polling
  composable, dE tier helper (text + icon, not colour alone), Vitest specs. Remaining once the
  bundle exists: Tailwind theme from its tokens, the seven pages, print view, ECharts plots,
  loading/empty/error states, a11y, and the Playwright smoke test.
- **M9** Solve/gamut/fit moved to a process pool (`/health` stays at ~10 ms while a solve or fit
  runs; it was ~280 ms with threads); alembic CLI creates the data dir; CI workflow; README with
  architecture diagram and a walkthrough checked against a live server.
- **Instrument self-test** `paintmixer measure selftest`: spotread port-list detection with
  macOS help, guided white calibration, N white-tile readings (optional lift/replace),
  per-band mean/std, repeatability and drift in dE2000, white-spectrum sanity checks, optional
  white/grey/black reference check, PASS/WARN/FAIL from `selftest_*` settings, JSON + CSV output
  under `sample_data/selftests/`. CLI only (operator-driven). Also fixed: `PATCH /settings` now
  returns a 422 error envelope for cross-field violations instead of a 500.
- **380–730 nm grid** Canonical grid widened to 36 bands (380–730 nm). 400–700 nm inputs are
  edge-held; data migration `0002` converts stored spectra; sample data and JSON schema
  regenerated (r400–r700 are the required minimum).
- **Gamut-mapped swatches** `colorsci.oklab`: OKLab/OKLCh (checked against Ottosson's table and
  colour-science) and vectorised CSS Color 4 gamut mapping, now the default for every swatch.
- **Tinting strength** `calibration.strength`: reduction K/S at peak absorption per paint,
  relative % against another model version; on `GET /paints` (active model) and
  `GET /models/{v}/spectra?reference_version=`.
- **Swatch models** `calibration.swatch` + `POST /models/from-swatches`: uncalibrated model from
  masstone/tint swatch colours (migration `0003`: paint `swatch_hex`/`tint_hex`/`tint_fraction`,
  model `source`); solve/predict/health report the model source and warn.
- **Ramps and worksheet preview** `solver.ramp` + `POST /ramp` (linear or log tint ladders
  between two paints, default into white); `POST /worksheet` rows carry `predicted_hex/lab`
  from the active model (finite film at the drawdown's gap over the model's substrates).
- **Browser forward model** `frontend/src/lib/km.ts` + `useRecipePreview` composable;
  `GET /colorimetry`; parity fixture generated by the backend (`paintmixer parity-fixture`,
  checked by a backend test) and verified by Vitest.
- **Multimix arrays** `solver.multimix` + `POST /multimix`: simplex lattices or N-D level grids
  of 2–6 paints with predicted swatches and polygon layout; mirrored in `km.ts`, with parity
  pinned by the fixture.
- **Demo seed + gamut per model** `paintmixer seed-demo` / `make seed-demo` /
  `PAINTMIXER_SEED_DEMO`: CMYKW starter set, colour library, calibrated model v1 (active) and
  swatch model v2. Shared import/fit/swatch logic moved from the routers to `api/importers.py`.
  `GET /models/{v}/gamut` and `/gamut.svg` (`solver.gamut_chart`) work for any version; gamut
  responses gained per-point `hex`, `model_source` and `max_paints`. The gamut sampler adds
  white let-downs of chromatic pairs and triples, so the light slices are filled.
- **Model lines** `model_line` table (migration `0004`; existing models go into `default`),
  `fitted_model.line_id/revision/label`, refs (`12`, `line`, `line@3`, `line@latest`) on every
  `/models/{ref}` endpoint, `/model-lines` CRUD, `PATCH /models/{ref}` (label, notes, move),
  `line`/`label` on fits and swatch models. The demo seeds into `cmykw-demo`.
- **Frontend support, items 1–5** (backend plan for the new frontend, branch
  `frontend-support`):
  1. Illuminant catalogue (17 lights in D/A/F/LED/ID series), `GET /illuminants`,
     `POST /appearance` (CAT02-adapted preview colours and dE2000 per light).
  2. Settings `accept_tolerance_de`, `check_illuminants`, `machine_max_batch_ml`,
     `low_level_warn_pct`; `batch_too_large` on solve and job create; metamerism under the
     checked lights. Old settings with a larger batch raise the maximum on load.
  3. Paint inventory (migration `0005`): batch code, body type, capacity, level, last refill;
     `POST /paints/{id}/refill`; level decremented on dispense; model masstone on `PaintRead`.
  4. Palettes (migration `0006`) and `/palettes` CRUD.
  5. `GET /machine`, `POST /jobs/{id}/accept` and `/cancel`; correction tolerance defaults to
     `accept_tolerance_de`.
  6. Mix candidates that differ in kind: `CandidateOut.tags` (closest, fewest paints, cheapest;
     the plan's no black / no white roles dropped), `CandidateOut.uncertainty_de` (per-paint hold-out error, doubled
     for under-sampled paints, plus dosing), `SolveResponse.gamut_margin_de`;
     `calibration.accuracy` (per-paint coverage and residuals, shared with the fit's data
     warnings and with item 7).
  7. Per-paint calibration accuracy: `GET /models/{ref}/paint-accuracy` (samples, median,
     grade, status ok / review / needs_samples / stale / uncalibrated, calibrated_at, batch at
     fit and now, coverage; only samples the paint is a big part of can set `review`); `fitted_model.paint_batches` recorded at fit time (migration
     `0007`).

