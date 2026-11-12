"""A simulated dispenser firmware served over local TCP, as the ESP32 would serve it on Wi-Fi."""

from __future__ import annotations

import socketserver
import threading
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
