"""Transports for the dispenser line protocol: TCP (Wi-Fi) and serial (USB, Bluetooth SPP).

Bluetooth serial (SPP) shows up as a serial port (``/dev/rfcommN``, ``/dev/cu.*`` or ``COMn``),
so :class:`SerialTransport` (pyserial) covers both USB and Bluetooth.
"""

from __future__ import annotations

import socket
import time

import serial

from paintmixer.hardware.dispenser import DispenserError
from paintmixer.hardware.protocol import Transport

DEFAULT_TCP_PORT = 3333
DEFAULT_BAUD = 115200


class TcpTransport:
    """Lines over a TCP connection (``host:port``)."""

    def __init__(self, host: str, port: int = DEFAULT_TCP_PORT, connect_timeout: float = 5.0):
        try:
            self._sock = socket.create_connection((host, port), timeout=connect_timeout)
        except OSError as e:
            raise DispenserError(f"cannot connect to the dispenser at {host}:{port}: {e}") from e
        self._buf = b""

    def write_line(self, line: str) -> None:
        self._sock.sendall(line.encode("ascii") + b"\n")

    def read_line(self, timeout: float) -> str | None:
        deadline = time.monotonic() + timeout
        while b"\n" not in self._buf:
            left = deadline - time.monotonic()
            if left <= 0:
                return None
            self._sock.settimeout(left)
            try:
                chunk = self._sock.recv(4096)
            except TimeoutError:
                return None
            if not chunk:
                raise DispenserError("the dispenser closed the connection")
            self._buf += chunk
        line, self._buf = self._buf.split(b"\n", 1)
        return line.decode("ascii", errors="replace").rstrip("\r")

    def close(self) -> None:
        self._sock.close()


class SerialTransport:
    """Lines over a serial port (USB CDC or Bluetooth SPP), 8N1."""

    def __init__(self, port: str, baudrate: int = DEFAULT_BAUD):
        try:
            self._ser = serial.Serial(port, baudrate=baudrate, timeout=0.1)
        except serial.SerialException as e:
            raise DispenserError(f"cannot open {port}: {e}") from e
        self._buf = b""

    def write_line(self, line: str) -> None:
        self._ser.write(line.encode("ascii") + b"\n")
        self._ser.flush()

    def read_line(self, timeout: float) -> str | None:
        deadline = time.monotonic() + timeout
        while b"\n" not in self._buf:
            if time.monotonic() >= deadline:
                return None
            self._buf += self._ser.read(self._ser.in_waiting or 1)
        line, self._buf = self._buf.split(b"\n", 1)
        return line.decode("ascii", errors="replace").rstrip("\r")

    def close(self) -> None:
        self._ser.close()


def open_transport(kind: str, address: str) -> Transport:
    """``tcp`` with ``host[:port]``, or ``serial`` with ``port[@baud]`` (USB or Bluetooth)."""
    if kind == "tcp":
        host, _, port = address.partition(":")
        if not host:
            raise DispenserError("dispenser address must be host[:port] for tcp")
        return TcpTransport(host, int(port) if port else DEFAULT_TCP_PORT)
    if kind == "serial":
        port, _, baud = address.partition("@")
        if not port:
            raise DispenserError("dispenser address must be a serial port[@baud]")
        return SerialTransport(port, int(baud) if baud else DEFAULT_BAUD)
    raise DispenserError(f"unknown dispenser transport {kind!r}")
