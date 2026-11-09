# Measuring calibration drawdowns

## Hardware and software

* X-Rite ColorMunki Photo / Design or i1Studio, driven by ArgyllCMS `spotread`.
* Geometry 45/0, UV-cut (M2-like) measurement only. Fluorescent and metallic paints are out of scope.

### macOS setup

```bash
brew install argyll-cms
```

```bash
spotread -?
```

No driver is needed on macOS. `spotread -?` prints the usage and, at the end, the list of
detected instruments ("-c listno ... from the following list"). If the instrument is not listed:

1. Quit X-Rite / i1Profiler / ColorMunki helper applications and daemons that hold the USB device
   (check Activity Monitor for `X-Rite` processes; some installers leave a background service).
2. Re-plug the instrument and run `spotread -?` again.
3. If several instruments are attached, pass `-c <n>` via `paintmixer measure session --spotread`.

### How spotread is used

`spotread -s` is interactive. It first asks for a white-tile calibration (ColorMunki: turn the dial
to the calibration position, then press a key). Afterwards, for each reading, it prompts
"Place instrument on spot to be measured, ... any other key to take a reading"; a key press or the
instrument button takes the reading and prints `Result is XYZ: …, D50 Lab: …` followed by
`Spectrum from 380.000 to 730.000 nm in 36 steps` and the values in percent. PaintMixer resamples
in percent; PaintMixer converts it to 0–1 and keeps the full 380–730 nm, which is its canonical grid. If spotread asks to recalibrate or
reports "sensor in the wrong position", the session tells the operator what to do and retries.

## Instrument self-test

Run this before calibrating with a new (or newly reconnected) instrument:

```bash
cd backend && uv run paintmixer measure selftest --replace --reference-check
```

1. **Detection.** Runs `spotread -?` (30 s timeout, `--detect-timeout`) and parses the `-c`
   port list. Plain serial ports and entries marked "Disabled - no firmware" don't count. With no
   instrument it prints macOS help (brew install, USB port/cable, old X-Rite daemons, sudo) and
   exits with code 2. Use `--port N` to pick one of several instruments.
2. **White calibration.** Prompts you to put the instrument on its base/calibration tile
   (ColorMunki: dial to the calibration position), then spotread's own calibration runs. Every
   run calibrates afresh; nothing is carried over from earlier sessions.
3. **White-tile readings.** `--n` readings (default 10, minimum 3). With `--replace` you are
   asked to lift the instrument and put it back between readings, so repeatability includes
   placement. Use a white reference tile that the instrument can read in measurement mode (an
   external ceramic or Spectralon-type tile; the ColorMunki's internal calibration tile is only
   readable in the calibration position).
4. **Analysis**, with all colour maths from `paintmixer.colorsci` (D65, CIE 1931 2°):
   * per-band mean and standard deviation (reflectance);
   * repeatability: mean and max dE2000 of each reading vs the mean spectrum;
   * drift: dE2000 between the mean of the first and last third of the readings, plus the
     per-reading trend;
   * sanity checks on the white spectrum: every band within 0.60–1.05, no negative values
     in any reading, no adjacent-band step > 0.05, and a smooth spectrum (RMS second
     difference ≤ 0.01).
5. **`--reference-check`** (optional). Three readings each of a matte white, a mid-grey and a
   matte black reference. Reports L*, C*ab and hue, warns on a colour cast (C* > 3), and fails if
   L* is not white > grey > black.
6. **Verdict.**

   | Check | WARN | FAIL |
   |---|---|---|
   | repeatability (max dE2000 vs mean) | > 0.5 | > 1.0 |
   | drift (first vs last third) | > 0.5 | > 1.0 |
   | negative values, white range, band jumps | — | any |
   | smoothness, reference colour cast | any | — |
   | reference lightness order | — | not white > grey > black |

   The thresholds live in the app settings (`selftest_*` fields, editable with `PATCH
   /api/v1/settings`). The CLI reads them from the PaintMixer database (defaults if it doesn't
   exist yet); `--warn-de` / `--fail-de` override them for one run. **These defaults are
   PaintMixer's guesses, not manufacturer specifications** (see docs/ASSUMPTIONS.md); tune them
   once you have a few runs from your own instrument.
7. **Output.** A console report, plus a folder `sample_data/selftests/<UTC timestamp>/` with
   `report.json` (all statistics, checks and thresholds), `spectra.csv` (every reading on the
   canonical 380–730 nm grid, replayable with `--source file --file spectra.csv`) and, for spotread,
   `spectra_raw.csv` (values as reported, e.g. 380–730 nm in %). `--out-dir` changes the root.

Exit codes: 0 PASS, 3 WARN, 1 FAIL, 2 instrument not found or measurement error.

`--source simulated` (with `--sim-noise`, `--sim-drift`) rehearses the procedure without
hardware. `--source file --file spectra.csv` re-analyses saved spectra.

**CLI only.** There is no `POST /api/v1/instrument/selftest`. The test needs an operator at the
instrument for every step (turning the dial to calibrate, placing and lifting the instrument,
swapping references), and the API's background-task pattern (start, then poll a status
endpoint) has no way to pause for those confirmations. Adding it would need a step-wise session
API (start → status shows the pending prompt → confirm), plus a server running on the machine
the instrument is plugged into. Revisit when the UI exists.

## Measure session

1. Generate the worksheet (UI or `POST /api/v1/worksheet/csv`) and print it
   (`POST /api/v1/worksheet/html`). Make the drawdowns on a black-and-white chart (e.g. Leneta),
   recording actual weighed masses on the sheet. Let them dry fully.
2. Run the session:

```bash
cd backend && uv run paintmixer measure session --worksheet worksheet.csv --out calibration.csv --ask-masses
```

For each sample (one background of one drawdown) the session prompts the operator, takes three
readings (`--readings`), stores their mean and per-band standard deviation (`sd400…sd700`), and
warns when the readings differ by more than 0.5 dE2000 (`--max-de`), offering a re-measure. Each
finished row is appended immediately, so interrupting with `q` (or Ctrl-C) and rerunning the same
command resumes where it stopped. `s` skips a sample. Expect repeatability warnings on near-black
samples: L* is very steep near black, so ±0.001 reflectance is already ~1 dE.

3. Upload `calibration.csv` (Calibration page or `POST /api/v1/calibration/upload`) and fit.

Other sources: `--source file --file spectra.csv` replays spectra by `sample_id`; `--source
simulated` uses the synthetic K/S truth (for rehearsing the workflow without hardware).
`CameraSource` is a stub for a future camera-based measurement.

## Testing without hardware

The spotread parser is tested against transcripts in `backend/tests/data/spotread/` (see the
README there for provenance) and the pexpect wrapper is exercised against `fake_spotread.py`, a
pty program that replays those prompts.
