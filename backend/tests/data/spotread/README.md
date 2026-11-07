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
