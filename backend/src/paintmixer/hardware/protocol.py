"""Host side of the dispenser line protocol (docs/dispenser_protocol.md).

The dispenser firmware (ESP32) speaks one ASCII, newline-delimited request/response protocol
over any of its links (USB serial, Bluetooth SPP serial, TCP). This module holds that protocol;
a :class:`Transport` only moves lines. :class:`ProtocolDispenser` implements
:class:`paintmixer.hardware.dispenser.Dispenser` on top of any transport.

Requests: ``#<seq> <COMMAND> [args]``. Replies carry the same ``#<seq>``: ``OK [values]`` ends
a request, ``ERR <CODE> [message]`` fails it, and ``PROGRESS <ml>`` may come before the end of a
long ``DISPENSE``. Lines starting with ``!`` are unsolicited device events.
"""

from __future__ import annotations

import time
from collections.abc import Callable
from typing import Protocol

from paintmixer.hardware.dispenser import DispenserError

PROTOCOL_VERSION = 1


class Transport(Protocol):
    """Moves protocol lines to and from the device (no line endings in the strings)."""

    def write_line(self, line: str) -> None: ...

    def read_line(self, timeout: float) -> str | None:
        """The next line, or None if none arrives within ``timeout`` seconds."""
        ...

    def close(self) -> None: ...


class ProtocolError(DispenserError):
    """The device answered with ``ERR`` (``code`` is its error code) or not at all."""

    def __init__(self, code: str, message: str) -> None:
        super().__init__(f"{code}: {message}" if message else code)
        self.code = code


def parse_kv(tokens: list[str]) -> dict[str, str]:
    return dict(t.split("=", 1) for t in tokens if "=" in t)


class ProtocolDispenser:
    """A dispenser reached through the line protocol over ``transport``.

    ``timeout_s`` bounds every request; a ``DISPENSE`` also gets ``volume / min_ml_per_s`` on
    top, for the time the pump needs. ``on_event`` receives unsolicited ``!`` lines and
    ``on_progress`` the ``PROGRESS`` volume of a running ``DISPENSE``.
    """

    def __init__(
        self,
        transport: Transport,
        *,
        timeout_s: float = 5.0,
        min_ml_per_s: float = 0.5,
        on_event: Callable[[str], None] | None = None,
        on_progress: Callable[[float], None] | None = None,
    ) -> None:
        self.transport = transport
        self.timeout_s = timeout_s
        self.min_ml_per_s = min_ml_per_s
        self.on_event = on_event
        self.on_progress = on_progress
        self._seq = 0
        self._info: dict[str, str] | None = None

    # -- requests -------------------------------------------------------------------------------

    def call(self, command: str, timeout: float | None = None) -> list[str]:
        """Send one request and return the tokens after ``OK``."""
        self._seq += 1
        tag = f"#{self._seq}"
        self.transport.write_line(f"{tag} {command}")
        deadline = time.monotonic() + (self.timeout_s if timeout is None else timeout)
        while True:
            left = deadline - time.monotonic()
            line = self.transport.read_line(max(left, 0.0)) if left > 0 else None
            if line is None:
                raise ProtocolError("TIMEOUT", f"no reply to {command!r}")
            line = line.strip()
            if line.startswith("!"):
                if self.on_event is not None:
                    self.on_event(line[1:].strip())
                continue
            parts = line.split()
            if not parts or parts[0] != tag:
                continue  # a stale reply to an earlier, timed-out request
            kind, rest = (parts[1] if len(parts) > 1 else ""), parts[2:]
            if kind == "OK":
                return rest
            if kind == "PROGRESS":
                if self.on_progress is not None and rest:
                    self.on_progress(float(rest[0]))
                continue
            if kind == "ERR":
                raise ProtocolError(rest[0] if rest else "ERR", " ".join(rest[1:]))
            raise ProtocolError("BAD_REPLY", line)

    def info(self) -> dict[str, str]:
        """``INFO``: name, fw, proto, channels, resolution (cached)."""
        if self._info is None:
            self._info = parse_kv(self.call("INFO"))
            proto = int(self._info.get("proto", "0"))
            if proto != PROTOCOL_VERSION:
                raise ProtocolError(
                    "PROTOCOL", f"device speaks protocol {proto}, expected {PROTOCOL_VERSION}"
                )
        return self._info

    @property
    def name(self) -> str:
        return self.info().get("name", "dispenser")

    def dispense(self, channel: int, volume_ml: float) -> float:
        """Dispense ``volume_ml`` from ``channel``; return the volume actually delivered."""
        if volume_ml < 0:
            raise DispenserError("volume must be >= 0")
        if volume_ml == 0:
            return 0.0
        timeout = self.timeout_s + volume_ml / self.min_ml_per_s
        out = self.call(f"DISPENSE {channel} {volume_ml:.4f}", timeout)
        return float(out[0])

    def stop(self) -> None:
        self.call("STOP")

    def close(self) -> None:
        self.transport.close()
