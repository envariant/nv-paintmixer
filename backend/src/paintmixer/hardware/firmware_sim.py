"""A simulated dispenser *firmware*: the device side of the line protocol.

:class:`SimulatedFirmware` answers protocol lines the way the ESP32 firmware should, using
:class:`paintmixer.hardware.dispenser.SimulatedDispenser` for the dosing physics. Reached through
:class:`LoopbackTransport` (in memory) or a TCP server (tests), it lets the whole host stack
(:class:`paintmixer.hardware.protocol.ProtocolDispenser` and the job runner) run without
hardware, and documents the firmware's expected behaviour.
"""

from __future__ import annotations

import queue
import threading
import time
from dataclasses import dataclass, field

from paintmixer.hardware.dispenser import DispenserError, SimulatedDispenser
from paintmixer.hardware.protocol import PROTOCOL_VERSION


@dataclass
class SimulatedFirmware:
    dispenser: SimulatedDispenser = field(default_factory=SimulatedDispenser)
    channels: int = 10
    name: str = "DSP-01-sim"  # INFO values cannot contain spaces
    fw: str = "sim-1"
    ml_per_s: float | None = None  # pump speed; None = instant
    progress_every_ml: float = 5.0
    empty_channels: set[int] = field(default_factory=set)  # reservoirs that run dry

    def __post_init__(self) -> None:
        self._stop = threading.Event()

    def handle(self, line: str) -> list[str]:
        """Reply lines for one request line."""
        parts = line.strip().split()
        if not parts or not parts[0].startswith("#"):
            return ["! IGNORED " + line.strip()]
        tag, cmd, args = parts[0], (parts[1].upper() if len(parts) > 1 else ""), parts[2:]
        try:
            return [f"{tag} {r}" for r in self._command(cmd, args)]
        except _Err as e:
            return [f"{tag} ERR {e.code} {e.message}".rstrip()]

    def _command(self, cmd: str, args: list[str]) -> list[str]:
        if cmd == "PING":
            return ["OK"]
        if cmd == "INFO":
            return [
                f"OK name={self.name} fw={self.fw} proto={PROTOCOL_VERSION} "
                f"channels={self.channels} resolution={self.dispenser.resolution_ml:g}"
            ]
        if cmd == "STOP":
            self._stop.set()
            return ["OK"]
        if cmd == "DISPENSE":
            if len(args) != 2:
                raise _Err("ARGS", "DISPENSE <channel> <ml>")
            try:
                channel, ml = int(args[0]), float(args[1])
            except ValueError as e:
                raise _Err("ARGS", str(e)) from e
            if not 1 <= channel <= self.channels:
                raise _Err("CHANNEL", f"no channel {channel}")
            if ml < 0:
                raise _Err("ARGS", "volume must be >= 0")
            if channel in self.empty_channels:
                raise _Err("EMPTY", f"channel {channel} is empty")
            self._stop.clear()
            out = []
            if self.ml_per_s:
                poured = 0.0
                while poured < ml:
                    step = min(self.progress_every_ml, ml - poured)
                    time.sleep(step / self.ml_per_s)
                    poured += step
                    if self._stop.is_set():
                        raise _Err("STOPPED", f"{poured:.4f}")
                    if poured < ml:
                        out.append(f"PROGRESS {poured:.4f}")
            try:
                actual = self.dispenser.dispense(channel, ml)
            except DispenserError as e:
                raise _Err("PUMP", str(e)) from e
            return [*out, f"OK {actual:.4f}"]
        raise _Err("UNKNOWN", cmd or "empty command")


class _Err(Exception):
    def __init__(self, code: str, message: str = "") -> None:
        self.code, self.message = code, message


class LoopbackTransport:
    """In-memory transport to a :class:`SimulatedFirmware` (a write is answered at once)."""

    def __init__(self, firmware: SimulatedFirmware) -> None:
        self.firmware = firmware
        self._replies: queue.Queue[str] = queue.Queue()

    def write_line(self, line: str) -> None:
        for r in self.firmware.handle(line):
            self._replies.put(r)

    def read_line(self, timeout: float) -> str | None:
        try:
            return self._replies.get(timeout=max(timeout, 0.0))
        except queue.Empty:
            return None

    def close(self) -> None:
        pass
