# spotread transcripts

Fixtures for `paintmixer.measurement.spotread`. No spectrophotometer is available in CI.

* `no_instrument.txt` is real output of `spotread -?` from ArgyllCMS 3.1.0 (Debian package)
  on a Linux machine with no instrument attached (captured verbatim up to the port list; the
  tool then keeps probing ports, which is why the wrapper uses timeouts).
* `session_colormunki.txt` is a **reconstructed** `spotread -s` session (ColorMunki, reflective):
  every prompt, result and header line uses the exact format strings found in the 3.1.0
  binary (`Set instrument sensor to calibration position,`, ` and then hit any key to continue,`,
  `Place instrument on spot to be measured,`, ` Result is XYZ: %f %f %f, %s Lab: %f %f %f`,
  `Spectrum from %.3f to %.3f nm in %d steps`, `Spot read failed due to the sensor being in the
  wrong position`). Spectral values are percent reflectance (ArgyllCMS reports reflective spectra
  in %), 36 bands 380-730 nm, comma separated. The values themselves are synthetic.
  Replace it with a real capture (`spotread -s log.txt`) when hardware is available.

* `usage_colormunki.txt`, `usage_no_ports.txt`, `usage_disabled.txt` are **reconstructed** `spotread
  -?` outputs for detection tests: the first eight lines are the real 3.1.0 capture above; the
  port lines use the binary's exact format strings (`    %d = '%s'`, `    %d = '%s' !! Disabled -
  no firmware !!`, `    ** No ports found **`). The instrument names inside the quotes are
  illustrative.
* `fake_spotread.py` replays these on a pty. Environment variables select behaviour:
  `FAKE_SPOTREAD_PORTS=colormunki|none|disabled|hang` (what `-?` lists, or hang while probing)
  and `FAKE_SPOTREAD_BLOCK=<i>` (always replay transcript reading `i`, e.g. 0 = the white tile).
