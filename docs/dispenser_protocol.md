# Dispenser line protocol (v1)

The dispenser firmware (ESP32) and the PaintMixer backend talk with one text protocol over any
of the dispenser's links. The protocol is the same on every link; only the transport differs:

| Transport | Backend setting (`dispenser_transport`, `dispenser_address`) | Notes |
|---|---|---|
| Wi-Fi (TCP) | `tcp`, `host[:port]` | default port **3333**; one client connection at a time |
| USB serial | `serial`, `port[@baud]` (e.g. `/dev/ttyUSB0`, `COM3`) | default 115200 baud, 8N1 |
| Bluetooth serial (SPP) | `serial`, the RFCOMM port (`/dev/rfcomm0`, `/dev/cu.DSP-01`, `COM5`) | same as USB once paired |

Serial needs the `pyserial` package on the backend. The host side is
`backend/src/paintmixer/hardware/protocol.py`; `hardware/firmware_sim.py` is a reference
implementation of the device side, which the backend uses as its simulator.

## Framing

* ASCII, one message per line, terminated by `\n` (a preceding `\r` is ignored).
* Tokens are separated by single spaces. Values never contain spaces.
* The host sends one request at a time and waits for its end before sending the next.

## Requests and replies

A request is `#<seq> <COMMAND> [args]`. `<seq>` is a positive integer the host increases with
every request. Every reply line to that request starts with the same `#<seq>`:

| Reply | Meaning |
|---|---|
| `#<seq> OK [values]` | the request succeeded; ends the request |
| `#<seq> ERR <CODE> [message]` | the request failed; ends the request |
| `#<seq> PROGRESS <ml>` | optional, during `DISPENSE`: volume poured so far |

Lines starting with `!` are unsolicited device events (e.g. `! LOW 3` for a low reservoir on
channel 3, `! DOOR OPEN`). The host logs them; they never end a request. A reply whose `<seq>`
is not the current request's (a late reply to a request the host gave up on) is ignored.

## Commands

| Command | Reply | Notes |
|---|---|---|
| `PING` | `OK` | liveness |
| `INFO` | `OK name=<name> fw=<version> proto=1 channels=<n> resolution=<ml>` | `key=value` tokens; the host checks `proto` |
| `DISPENSE <channel> <ml>` | `OK <actual_ml>` | channels are 1-based; `<ml>` has up to 4 decimals. Reply when the pour is complete, with the volume actually delivered (e.g. measured by the pump's step count or a load cell) |
| `STOP` | `OK` | stop the pump at once; a running `DISPENSE` ends with `ERR STOPPED <poured_ml>` |

Error codes: `ARGS` (bad arguments), `CHANNEL` (no such channel), `EMPTY` (reservoir empty),
`PUMP` (pump fault), `STOPPED`, `BUSY`, `UNKNOWN` (unknown command).

## Timing

The host waits 5 s for a reply, plus `ml / 0.5` s for a `DISPENSE` (a pump slower than
0.5 ml/s needs a longer timeout on the host). The host pauses and cancels jobs only between
`DISPENSE` requests, so the firmware never has to handle a second request during a pour, but it
should accept `STOP` at any time for safety.

## Example

```
> #1 INFO
< #1 OK name=DSP-01 fw=1.2.0 proto=1 channels=10 resolution=0.05
> #2 DISPENSE 3 42.5000
< #2 PROGRESS 20.0000
< #2 OK 42.4500
> #3 DISPENSE 9 1.2000
< #3 ERR EMPTY channel 9 is empty
```
