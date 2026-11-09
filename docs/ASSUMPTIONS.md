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
