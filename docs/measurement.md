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
380–730 nm to 400–700 nm / 10 nm and converts percent to 0–1. If spotread asks to recalibrate or
reports "sensor in the wrong position", the session tells the operator what to do and retries.

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
