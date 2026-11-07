"""ArgyllCMS ``spotread -s`` wrapper and output parser.

spotread is interactive: it asks for a white-tile calibration (ColorMunki: turn the dial to the
calibration position and press a key), then for each reading prints::

    Place instrument on spot to be measured,
    ...
    Hit ESC or Q to exit, instrument switch or any other key to take a reading:
     Result is XYZ: 31.204411 22.117420 30.556010, D50 Lab: 54.148802 47.215507 -14.006313
    Spectrum from 380.000 to 730.000 nm in 36 steps
       55.000,    54.981, ...

Reflective spectra are in percent. The wrapper drives this with pexpect; the parser is a pure
function tested against transcripts in ``tests/data/spotread``.

macOS setup: ``brew install argyll-cms`` (no driver needed). If the instrument is not found,
quit X-Rite / i1Profiler helper daemons that may hold the USB device, then run ``spotread -?`` to
check that the instrument is listed on the port list.
"""

from __future__ import annotations

import re
import shutil
from collections.abc import Callable
from dataclasses import dataclass

from paintmixer.measurement.base import MeasurementError, MeasureRequest, Reading

_HEADER = re.compile(r"Spectrum from\s+([\d.]+)\s+to\s+([\d.]+)\s+nm in\s+(\d+)\s+steps")
_F = r"([-\d.]+)"
_RESULT = re.compile(rf"Result is XYZ:\s*{_F}\s+{_F}\s+{_F},\s*(\w+)\s+Lab:\s*{_F}\s+{_F}\s+{_F}")
_NUM = re.compile(r"[-+]?\d+(?:\.\d+)?(?:[eE][-+]?\d+)?")

READ_PROMPT = re.compile(r"any other key to take a reading:\s*")
CAL_PROMPT = re.compile(r"and then hit any key to continue,")
RETRY_PROMPT = re.compile(r"Hit Esc or Q to give up, any other key to retry:\s*")
FATAL = re.compile(
    r"(Unknown, inappropriate or no instrument detected|Finding instrument paths failed|"
    r"Instrument initialisation failed[^\n]*)"
)


@dataclass(frozen=True)
class SpotreadSpectrum:
    wavelengths: list[float]
    values: list[float]  # as printed (percent for reflective)
    xyz: tuple[float, float, float] | None = None
    lab: tuple[float, float, float] | None = None
    lab_white: str | None = None

    def reading(self, *, percent: bool = True) -> Reading:
        return Reading.from_raw(
            self.wavelengths, self.values, scale=0.01 if percent else 1.0, source="spotread"
        )


def parse_spotread_output(text: str) -> list[SpotreadSpectrum]:
    """Extract every spectrum (with its preceding XYZ/Lab result line, if any)."""
    out: list[SpotreadSpectrum] = []
    last_result: re.Match[str] | None = None
    pos = 0
    while True:
        h = _HEADER.search(text, pos)
        r = _RESULT.search(text, pos)
        if h is None:
            break
        if r is not None and r.start() < h.start():
            last_result = r
        start, end, n = float(h.group(1)), float(h.group(2)), int(h.group(3))
        values: list[float] = []
        for m in _NUM.finditer(text, h.end()):
            values.append(float(m.group(0)))
            if len(values) == n:
                pos = m.end()
                break
        else:
            raise MeasurementError(f"spectrum truncated: expected {n} values, got {len(values)}")
        step = (end - start) / (n - 1) if n > 1 else 0.0
        wl = [start + i * step for i in range(n)]
        xyz = lab = white = None
        if last_result is not None:
            g = last_result.groups()
            xyz = (float(g[0]), float(g[1]), float(g[2]))
            white = g[3]
            lab = (float(g[4]), float(g[5]), float(g[6]))
            last_result = None
        out.append(SpotreadSpectrum(wl, values, xyz, lab, white))
    return out


def check_fatal(text: str) -> str | None:
    m = FATAL.search(text)
    return m.group(1) if m else None


class ArgyllSpotread:
    """Drive ``spotread -s`` through pexpect.

    ``prompt(message)`` is called whenever the operator must act (calibrate, place the
    instrument); it should return when they are ready. Readings are triggered by sending a key
    (the instrument button also works).
    """

    name = "spotread"

    def __init__(
        self,
        executable: str = "spotread",
        extra_args: tuple[str, ...] = (),
        prompt: Callable[[str], None] = lambda _m: None,
        timeout: float = 60.0,
    ) -> None:
        self.executable = executable
        self.extra_args = extra_args
        self.prompt = prompt
        self.timeout = timeout
        self._child: object | None = None

    def open(self) -> None:
        import pexpect

        if shutil.which(self.executable) is None:
            raise MeasurementError(
                f"{self.executable!r} not found: install ArgyllCMS (macOS: brew install argyll-cms)"
            )
        child = pexpect.spawn(
            self.executable, ["-s", *self.extra_args], encoding="utf-8", timeout=self.timeout
        )
        self._child = child
        while True:
            i = child.expect([CAL_PROMPT, READ_PROMPT, FATAL, pexpect.EOF, pexpect.TIMEOUT])
            if i == 0:
                self.prompt(
                    "Set the instrument to the calibration position (white tile), then continue."
                )
                child.send(" ")
            elif i == 1:
                return
            elif i == 2:
                raise MeasurementError(
                    f"spotread: {child.after!s}. Check the USB connection, quit X-Rite helper "
                    "daemons, and run `spotread -?` to list instruments."
                )
            else:
                raise MeasurementError(
                    f"spotread exited or timed out during start-up: {child.before}"
                )

    def read(self, request: MeasureRequest) -> Reading:
        import pexpect

        child = self._child
        if child is None:
            raise MeasurementError("source not open")
        assert isinstance(child, pexpect.spawn)
        self.prompt(f"Place the instrument on {request.sample_id} and take a reading.")
        child.send(" ")
        buf = ""
        while True:
            i = child.expect([READ_PROMPT, CAL_PROMPT, RETRY_PROMPT, pexpect.EOF, pexpect.TIMEOUT])
            buf += str(child.before or "")
            if i == 0:
                spectra = parse_spotread_output(buf)
                if not spectra:
                    raise MeasurementError(f"no spectrum in spotread output: {buf[-300:]}")
                return spectra[-1].reading()
            if i == 1:
                self.prompt("spotread requests a calibration: set the calibration position.")
                child.send(" ")
            elif i == 2:
                self.prompt("Reading failed (sensor position?). Fix it, then continue to retry.")
                child.send(" ")
            else:
                raise MeasurementError(f"spotread stopped responding: {buf[-300:]}")

    def close(self) -> None:
        child = self._child
        if child is not None:
            import pexpect

            assert isinstance(child, pexpect.spawn)
            if child.isalive():
                child.send("q")
                child.close(force=True)
        self._child = None
