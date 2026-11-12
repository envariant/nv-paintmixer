"""A simulated dispenser firmware served the way the ESP32 serves it: over TCP (Wi-Fi) or a
serial line (a pseudo-terminal standing in for USB / Bluetooth serial)."""

from __future__ import annotations

import os
import socketserver
import threading
import tty
from collections.abc import Iterator
from contextlib import contextmanager

from paintmixer.hardware.firmware_sim import SimulatedFirmware


@contextmanager
def firmware_over_tcp(fw: SimulatedFirmware) -> Iterator[int]:
    """Serve ``fw`` on 127.0.0.1; yields the port."""

    class Handler(socketserver.StreamRequestHandler):
        def handle(self) -> None:
            for raw in self.rfile:
                for out in fw.handle(raw.decode("ascii").strip()):
                    self.wfile.write(out.encode("ascii") + b"\n")

    srv = socketserver.ThreadingTCPServer(("127.0.0.1", 0), Handler)
    srv.daemon_threads = True
    t = threading.Thread(target=srv.serve_forever, daemon=True)
    t.start()
    try:
        yield int(srv.server_address[1])
    finally:
        srv.shutdown()
        srv.server_close()


@contextmanager
def firmware_over_pty(fw: SimulatedFirmware) -> Iterator[str]:
    """Serve ``fw`` on the device end of a pseudo-terminal; yields the host end's path."""
    device, host = os.openpty()
    tty.setraw(device)
    tty.setraw(host)
    path = os.ttyname(host)
    stop = threading.Event()

    def serve() -> None:
        buf = b""
        while not stop.is_set():
            try:
                chunk = os.read(device, 1024)
            except OSError:
                return
            buf += chunk
            while b"\n" in buf:
                line, buf = buf.split(b"\n", 1)
                for out in fw.handle(line.decode("ascii").strip()):
                    os.write(device, out.encode("ascii") + b"\n")

    t = threading.Thread(target=serve, daemon=True)
    t.start()
    try:
        yield path
    finally:
        stop.set()
        os.close(device)
        os.close(host)
