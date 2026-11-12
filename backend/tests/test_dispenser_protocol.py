"""The dispenser line protocol (host side), the simulated firmware and the transports."""

from __future__ import annotations

import sys

import pytest

from paintmixer.hardware.dispenser import DispenserError, SimulatedDispenser
from paintmixer.hardware.firmware_sim import LoopbackTransport, SimulatedFirmware
from paintmixer.hardware.protocol import ProtocolDispenser, ProtocolError
from paintmixer.hardware.transports import TcpTransport, open_transport
from tests.hardware_helpers import firmware_over_pty, firmware_over_tcp


def _disp(**fw: object) -> ProtocolDispenser:
    return ProtocolDispenser(LoopbackTransport(SimulatedFirmware(**fw)))  # type: ignore[arg-type]


def test_info_and_dispense() -> None:
    d = _disp(dispenser=SimulatedDispenser(rel_sigma=0, abs_sigma_ml=0))
    info = d.info()
    assert info["proto"] == "1" and info["channels"] == "10" and d.name == "DSP-01-sim"
    assert d.dispense(3, 12.52) == pytest.approx(12.5)  # quantised to 0.05 ml
    assert d.dispense(3, 0) == 0.0


@pytest.mark.parametrize(
    ("command", "code"),
    [
        ("DISPENSE 99 1", "CHANNEL"),
        ("DISPENSE 4 1", "EMPTY"),
        ("DISPENSE 1", "ARGS"),
        ("FOO", "UNKNOWN"),
    ],
)
def test_device_errors(command: str, code: str) -> None:
    d = _disp(empty_channels={4})
    with pytest.raises(ProtocolError) as e:
        d.call(command)
    assert e.value.code == code


class _Scripted:
    """A transport that answers from a script (to test the host's parsing)."""

    def __init__(self, replies: list[str]) -> None:
        self.replies, self.sent = list(replies), []  # type: list[str], list[str]

    def write_line(self, line: str) -> None:
        self.sent.append(line)

    def read_line(self, timeout: float) -> str | None:
        return self.replies.pop(0) if self.replies else None

    def close(self) -> None:
        pass


def test_stale_replies_events_and_progress_are_handled() -> None:
    t = _Scripted(["#0 OK 1.0", "! LOW 3", "#1 PROGRESS 2.5", "#1 OK 5.0000"])
    events, progress = [], []  # type: list[str], list[float]
    d = ProtocolDispenser(t, on_event=events.append, on_progress=progress.append)
    assert d.dispense(2, 5.0) == 5.0
    assert t.sent == ["#1 DISPENSE 2 5.0000"] and events == ["LOW 3"] and progress == [2.5]


def test_timeout_and_protocol_version() -> None:
    with pytest.raises(ProtocolError) as e:
        ProtocolDispenser(_Scripted([]), timeout_s=0.05).call("PING")
    assert e.value.code == "TIMEOUT"
    with pytest.raises(ProtocolError) as e:
        ProtocolDispenser(_Scripted(["#1 OK name=x proto=9"])).info()
    assert e.value.code == "PROTOCOL"


def test_slow_pump_reports_progress() -> None:
    progress: list[float] = []
    d = ProtocolDispenser(
        LoopbackTransport(SimulatedFirmware(ml_per_s=1000.0, progress_every_ml=5.0)),
        on_progress=progress.append,
    )
    d.dispense(1, 12.0)
    assert progress == [5.0, 10.0]


def test_tcp_transport_end_to_end() -> None:
    fw = SimulatedFirmware(dispenser=SimulatedDispenser(rel_sigma=0, abs_sigma_ml=0))
    with firmware_over_tcp(fw) as port:
        d = ProtocolDispenser(open_transport("tcp", f"127.0.0.1:{port}"))
        assert d.info()["name"] == "DSP-01-sim"
        assert d.dispense(1, 7.5) == pytest.approx(7.5)
        assert [c for c, _req, _act in fw.dispenser.log] == [1]
        d.close()
    with pytest.raises(DispenserError, match="cannot connect"):
        TcpTransport("127.0.0.1", port, connect_timeout=0.5)


def test_open_transport_checks_its_address() -> None:
    with pytest.raises(DispenserError, match="host"):
        open_transport("tcp", "")
    with pytest.raises(DispenserError, match="serial port"):
        open_transport("serial", "")
    with pytest.raises(DispenserError, match="unknown"):
        open_transport("carrier-pigeon", "x")


@pytest.mark.skipif(sys.platform == "win32", reason="needs a pseudo-terminal")
def test_serial_transport_end_to_end() -> None:
    """A pseudo-terminal pair stands in for the USB / Bluetooth serial link: the simulated
    firmware answers on one end, SerialTransport talks on the other."""
    fw = SimulatedFirmware(dispenser=SimulatedDispenser(rel_sigma=0, abs_sigma_ml=0))
    with firmware_over_pty(fw) as port:
        d = ProtocolDispenser(open_transport("serial", f"{port}@115200"))
        assert d.info()["name"] == "DSP-01-sim"
        assert d.dispense(2, 3.25) == pytest.approx(3.25)
        d.close()
    with pytest.raises(DispenserError, match="cannot open"):
        open_transport("serial", "/dev/no-such-port")
