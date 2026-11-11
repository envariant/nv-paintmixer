# Assumptions and interpretations

Decisions taken without asking, so they can be reviewed. Each is tagged with the milestone that
introduced it.

- **M0** Python is pinned to 3.12 through uv (`requires-python >=3.12`). The container ships 3.13 as
  `python3`; uv provisions 3.12 for the venv.
- **M0** The colour-maths package is named `paintmixer.colorsci` so it never shadows the
  third-party `colour` package from colour-science.
- **M0** TypeScript is pinned to 5.9 because `openapi-typescript` 7 has a TypeScript 5 peer
  dependency.
- **M1** XYZ uses ASTM E2022 10 nm weighting factors computed by colour-science; weights outside
  400–700 nm are folded into the end bands (reflectance assumed constant beyond the range).
- **M1** Swatch sRGB is computed via D65 Lab so a perfect reflector is exactly sRGB white even
  though the 10 nm white point differs from the sRGB matrix white by ~0.01.
- **M1** Fluorescent and metallic/pearlescent paints are out of scope: K-M two-constant theory
  with 45/0 UV-cut measurement cannot model fluorescence or goniochromatic effects.
- **M2** Masstones are drawn over the black-and-white chart like everything else, so each masstone
  drawdown yields `MT-<paint>-W` and `MT-<paint>-B` rows (types `masstone_over_white/black`). The
  white thickness series uses ids `MT-<white>-<gap>-W/-B`.
- **M2** Mixture sample ids: `PR-<a>-<b>-<pct a>` (pair), `PW-<a>-<b>` (pair 20/20 + 60 % white),
  `NN-nnn` near-neutral, `DK-nnn` dark, `RN-nnn` random — each with `-W`/`-B`.
- **M2** The calibration CSV accepts optional `sd400..sd700` (spread of repeat readings),
  `measured_at` and `n_readings` columns so a measurement session can store spread in the same file.
- **M2** `holdout` is honoured on tints and mixtures; on other types it is ignored with a warning.
- **M2** Synthetic noise: each row is the mean of three readings with per-reading sigma
  0.002·√3, so the reported reflectance noise is sigma 0.002.
- **M2** Calibration samples are keyed by `sample_id`; uploading a file with an existing id
  replaces that sample (upsert), so re-measuring a drawdown is a re-upload.
- **M2** Costs in `sample_data/paints.csv` are invented SGD/ml figures for development.
- **M3** Hold-out acceptance (< 0.5 dE2000) is tested against the **noise-free** synthetic
  ground truth. Against the noisy synthetic measurements the hold-out mean is ~0.9 because
  sigma 0.002 reflectance noise alone produces ~0.9 dE2000 on dark drawdowns (L* is steep near
  black); the fit report therefore also prints the "measurement noise alone" dE estimated from
  each sample's spread. With low noise (sigma 0.0003) the reported hold-out mean is < 0.5.
- **M3** Fit residuals are weighted by `((0.52)/(R + 0.02))^(2/3)`, an approximation of L*
  sensitivity, so dark samples are not under-weighted relative to their visual importance.
- **M3** All drawdowns are modelled as finite layers over the measured substrate (thickness
  `tau(λ)·gap_um`). The solver predicts opaque (hiding) films with R∞. Film shrinkage on drying is
  absorbed into `tau`.
- **M3** Outliers are flagged on RMS reflectance residual (> max(0.006, 4× median)), not dE,
  because dE is dominated by noise on dark samples.
- **M4** `include_white` is tri-state: unset = white allowed, `true` = every candidate contains a
  white, `false` = white excluded.
- **M4** Min fraction is enforced as a hard bound during optimisation (the objective's penalty
  term only matters after quantisation, where a dose can fall below it).
- **M4** dE2000 in the objective is smoothed as `sqrt(dE² + 0.05²) − 0.05` so gradient-based
  refinement behaves at an exact match (dE is a cone at 0). Reported dE values are unsmoothed.
- **M4** Metamerism = dE2000 between the mixture and the target's reference spectrum under A and
  F11 (each with its own white). For Lab/sRGB targets the reference spectrum is reconstructed,
  so the figure is indicative only; the API reports which.
- **M4** Dose sensitivity = worst dE2000 when any one paint is over-dosed by 1 % of the batch.
- **M4** "Black helps" is demonstrated through dose sensitivity: the synthetic CMY pigments
  are strong enough to reach L* ≈ 5 without black, so the dE criterion alone does not separate
  the pools; recipes with black are markedly less sensitive to dosing errors on neutrals/darks.
- **M4** Multiprocessing: the staged-vs-exhaustive test parallelises across targets. Within one
  solve the batched NumPy screening was fast enough (< 1 s at n=20) that process start-up
  (~1 s with macOS `spawn`) would cost more than it saves, so `n_jobs` is reserved and unused.
- **M4** Out-of-gamut threshold: best quantised dE2000 > 1.0 (configurable `out_of_gamut_de`).
- **M5** A new fit is activated by default (`activate: false` keeps the current model).
- **M5** Paints referenced by calibration samples cannot be deleted (409); deactivate instead.
- **M5** `predicted_lab` in solve results is under the matching illuminant; swatch hex values are
  always rendered under D65. Lab/sRGB targets are always matched under D65 (an illuminant only
  makes sense with a target spectrum).
- **M5** The colour library sample (`sample_data/color_library.csv`) uses invented names and
  values, not a proprietary colour system.
- **M5** The backend also serves a minimal printable worksheet (`POST /worksheet/html`) so the
  calibration workflow is usable before the M6 UI exists; it is a plain document, not app UI.
- **M7** No spectrophotometer was available, so the spotread transcript fixture is
  reconstructed from the exact format strings in the ArgyllCMS 3.1.0 binary (installed from
  Debian in CI) with synthetic values; `no_instrument.txt` is real `spotread -?` output. Replace
  the transcript with a real capture when hardware is available.
- **M7** spotread reflective spectra are read as percent (ArgyllCMS documents reflective units
  as %/nm) and divided by 100.
- **M7** One "sample" in a session is one background of one drawdown; masses are asked once per
  drawdown and written to both rows.
- **M8** The correction assumes the model-vs-reality Lab bias is locally constant, so it solves
  `J Δc = target − measured` (not `target − predicted`). Corrections default to additions to the
  existing batch; remix (fresh batch) is available.
- **M8** Only a simulated dispenser exists; `POST /jobs/{id}/dispense` with `simulate: false`
  returns `no_dispenser`. Simulated measurements of a job use the job's model version with a
  configurable gain/offset bias and noise.
- **M8** The learned correction itself is not implemented; residuals are logged (`correction_log`
  table) with recipe, prediction, measurement and target.
- **M6** Blocked per instructions: no Claude Design handoff bundle exists, so no UI was designed.
  `frontend/src/App.vue` is a placeholder that only shows API health.
- **M9** Compute runs in a `spawn` process pool (2 workers by default). The first solve after
  start-up pays worker start-up (~1 s); gamut caches live per worker.
- **Self-test** Verdict thresholds are **my guesses, not manufacturer figures**: WARN if any
  reading's dE2000 vs the mean white-tile spectrum exceeds 0.5, FAIL above 1.0; drift (first vs
  last third) uses the same two thresholds. Sanity limits (also guesses): white-tile reflectance
  0.60–1.05 in every 10 nm band, adjacent-band step ≤ 0.05, RMS second difference ≤ 0.01,
  reference colour cast C*ab > 3. All are `selftest_*` app settings.
- **Self-test** Severity: negative values, an implausible white range, band jumps and wrong
  reference lightness order are FAIL (instrument fault or wrong sample); roughness and colour
  casts are WARN.
- **Self-test** CLI only (no API endpoint): every step needs an operator at the instrument, which
  the start-then-poll background-task pattern can't accommodate. See docs/measurement.md.
- **Self-test** Instrument detection gives `spotread -?` 30 s. On this Linux CI container it never
  finishes probing ports (it was still running after 100 s), so a timeout is reported as "not
  found". A port counts as an instrument only if it has a name in parentheses and isn't marked
  "Disabled - no firmware"; plain serial ports (e.g. `/dev/cu.Bluetooth-Incoming-Port`) are
  ignored.
- **Self-test** "No hidden state": each run prompts for and performs its own white calibration
  and stores nothing between runs except the output folder.
- **Self-test** Exit codes: 0 PASS, 3 WARN, 1 FAIL, 2 instrument not found / measurement error.
- **Self-test** Run outputs go to `sample_data/selftests/` (when run inside the repo) and are not
  git-ignored; commit them if you want an instrument history.
- **380–730 nm grid** The canonical grid is now 36 bands, 380–730 nm (was 31 bands, 400–700 nm),
  so the ColorMunki's full range is used. Files covering only 400–700 nm are still accepted:
  their edge bands are held flat, which is colorimetrically equivalent to the old end-folding.
  Migration `0002` extends stored spectra and K/S curves the same way (its downgrade slices them
  back). The white-tile sanity checks in the self-test still look only at 400–700 nm, because
  instruments are noisiest at the 380/730 nm ends.
- **Gamut-mapped swatches** Out-of-sRGB swatches are gamut-mapped with the CSS Color 4 algorithm
  (keep OKLab lightness and hue, bisect chroma, stop when clipping moves the colour by < 0.02
  ΔE_OK), implemented from the spec, not copied. Every `hex` the API returns uses it; the
  `out_of_gamut` / `in_srgb_gamut` flags still say when a swatch is only an approximation.
  `lab_to_srgb(..., method="clip")` keeps the old per-channel clipping.
- **Tinting strength** Defined ISO 787-24 style from the fitted model: K/S of a 10 % paint /
  90 % white (by volume) reduction at its absorption peak, searched over 400–700 nm. It is
  computed from K and S, not measured. The absolute value depends on the white used, so it is
  only comparable between paints reduced with the same white. Relative strength compares two
  model versions of the same paint at the reference's peak wavelength. Not defined for white
  (`null`).
- **Swatch ("try it") models** `POST /models/from-swatches` builds an uncalibrated model from
  swatch colours. Spectra come from Jakob-2019 reconstruction. K/S per band comes from the opaque
  masstone. Scattering is one value per paint, fitted so the model reproduces the tint swatch's
  colour, or assumed as 0.3 × white without one. Absorption is never adjusted to the tint:
  that kept masstones exact at a small cost in mixture accuracy. On the synthetic 5-paint set
  the mixture error is median ≈ 4, p90 ≈ 9 dE2000 with tints; median ≈ 5, p90 ≈ 16 without.
  Such models are stored with `source = "swatches"`, and every solve/predict reports it with
  a warning. They have no hold-out report. Their film-thickness scale and substrates are
  synthetic defaults, used only for worksheet previews.
- **Ramps / previews** Ramps are opaque-film predictions, like the solver's. Worksheet row
  previews use the finite-layer model at the drawdown's gap over the active model's substrates,
  so -W and -B rows differ wherever the film isn't hiding. Rows whose paints aren't in the
  active model have no preview.
- **Browser forward model** The TypeScript port covers prediction only (opaque films, D65/A/F11,
  dE2000, CSS gamut mapping, ramps); solving and fitting stay on the server. It reads the
  server's exact weighting tables (`GET /colorimetry`) rather than embedding its own, so the
  only parity risk is code drift. The generated `km.parity.json` fixture pins that: reflectance
  within 1e-9, Lab within 1e-6, swatch hex identical.
- **Multimix arrays** Simplex lattices are ordered lexicographically, first paint's parts
  descending, so cell 0 is pure paint 1. Grid arrays are in C order, last paint fastest. Grid
  arrays keep their all-zero cell (empty: no fractions, no swatch) and their proportional
  duplicates (1:1 and 2:2), so the N-D shape stays intact. Cap: 10,000 cells per request. The
  layout puts paint j at angle 90° + j·360°/k on the unit circle (two paints: a horizontal
  line), a display aid only. Predictions are opaque films, like ramps and the solver.
- **Ramp vs multimix** `/ramp` is kept as the shortcut for two-paint previews (it defaults to the
  model's white and offers log tint ladders), but it is computed by the multimix code, so there
  is one prediction path. A linear ramp of n steps is identical to a two-paint simplex with
  n − 1 divisions; a test checks this.
- **Demo seed** The demo is the 5-paint starter set, renamed after its role (White/Black/Cyan/
  Magenta/Yellow, with the pigment in brackets), on the synthetic `calibration_starter5.csv`.
  The ids stay pigment-based (`phthalo-blue`, ...), so data keyed on them keeps working. The
  seed never deletes: it upserts paints, colours and samples, and adds a model only when none of
  that source exists (or with `--refit`). The calibrated model is activated and the swatch
  model is not. Auto-seeding (`PAINTMIXER_SEED_DEMO`) only fires on a database with no paints
  and no models, so it can't overwrite a user's work.
- **Gamut sampling of light colours** Besides singles, pairs and random 3–5 paint mixes, the
  sampler now lets every chromatic pair and triple down with the lightest paint (normally white)
  at 50–99.5 %. Random mixes rarely land above L* 70, so the light slices used to show only the
  two-paint tint lines, as spikes, even though the colours between those hues were mixable.
  This only adds samples, so the gamut can only grow. It changes the solver's out-of-gamut
  pre-check the same way, but the achieved dE is still the final word.
- **Gamut charts** Each panel is one L* slice (±5). Wedges are filled radially from the neutral
  axis to the boundary, which assumes each slice is star-shaped around neutral. That holds for
  pools with white and black but is not proven in general. Fills are D65 sRGB with CSS Color 4
  gamut mapping, so very chromatic wedges look duller than the paint. The outline is the
  boundary in Lab. By default a chart's scale is its own maximum C*, rounded up to 20;
  `chroma_scale` fixes it so versions can be compared. Hue bins with no samples get `hex: null`.
- **Model lines** Names belong to *lines* (series of versions), not to individual versions.
  A version gets an editable `label` instead of a unique name, so a ref like `studio` has only
  one meaning. The global `version` is kept and stays the stable key: solve results, jobs and
  caches record it. Revisions are counted per line and never reused: the line stores the
  highest revision it has issued, so a ref like `studio@2` can never come to mean a different
  model after one is moved out. A bare line id resolves to the newest *calibrated* revision,
  so adding an uncalibrated swatch model to a line does not silently replace its calibrated
  model (`@latest` gives the newest of any kind). "One active model" stays global across lines,
  since the dispenser holds one paint set at a time. A fit's line must exist before the fit,
  so a typo is an error rather than a new line. The exception is `default`, created on first
  use and by the migration for existing models. Line ids are immutable (lower case, digits and
  `-`, starting with a letter, so they can't be mistaken for versions). `active` and
  `from-swatches` are reserved. Lines can be deleted only when empty; models are never deleted.
- **Illuminant catalogue** 17 illuminants in five series (D, A, F, LED, ID), each with a
  default member and a nominal CCT. Spectra come from `colour.SDS_ILLUMINANTS`; D93 is not
  tabulated there, so it is synthesised from the CIE daylight model at 9300 K (rescaled to the
  modern c2, like the tabulated D illuminants). Switching series keeps the member closest in
  CCT. Previews under another light are chromatically adapted to D65 with CAT02, full
  adaptation, before conversion to sRGB, so the display shows what the eye adapted to that
  light would see. The UI shows those values and never shifts hues itself.
- **Checked lights and machine maximum** `check_illuminants` defaults to A and F11, the lights
  metamerism was reported under before, so solve results don't change. The design's default
  (A, D50) is left for the Settings screen to set. `machine_max_batch_ml` is 250 ml; solve and
  job creation refuse larger batches (`batch_too_large`). Settings saved before the maximum
  existed may hold a larger batch: on load the maximum is raised to that batch instead of
  refusing to load, and the next settings change saves it. `PATCH /settings` still refuses a
  batch above the maximum.
- **Paint inventory** The reservoir level is tracked only for paints that have one
  (`level_ml` set, normally by a refill), so existing paints are unaffected. A refill fills to
  `capacity_ml` unless a level is given, and stamps the time; a new `batch_code` there means a
  new lot. Dispensing subtracts the volume actually delivered, never below 0. `model_lab` /
  `model_hex` are the active model's masstone under D65, gamut-mapped for display.
- **Palettes** Ordered lists of colour-library ids: order is kept, repeats are dropped,
  unknown ids are refused. Deleting a colour removes its id from every palette in the same
  transaction: SQLite can give a later colour the same id, so a stale id would bring an
  unrelated colour into old palettes. Reads also filter out ids that are no longer in the
  library.
- **Machine status and job outcomes** The pill's state is derived from the newest open job:
  dispensed → measuring, measured → correcting, correcting → pouring, needs_attention →
  attention; no open job → ready. The machine name is fixed ("DSP-01 (simulated)") until a real
  dispenser adapter exists. Accept is allowed once a job has a measurement (measured,
  needs_attention or done) and ends it as `accepted` whatever its dE. Cancel works from any open
  state and logs the volume already poured. Correction without an explicit tolerance uses
  `accept_tolerance_de` (default 1.0; it was a fixed 0.5).

