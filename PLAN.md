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
| Spectral grid | 31 bands, 400–700 nm at 10 nm; inputs on other grids are linearly resampled. |
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
| M3 | Calibration fit + report | |
| M4 | Solver + gamut + scaling tests | |
| M5 | Worksheet generator + full API | |
| M6 | Frontend from the Claude Design handoff | blocked until `design/handoff/` exists |
| M7 | Measurement sources, spotread parser, `paintmixer measure session` | |
| M8 | Dispenser simulator, closed-loop correction, jobs | |
| M9 | Hardening + docs | |

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
