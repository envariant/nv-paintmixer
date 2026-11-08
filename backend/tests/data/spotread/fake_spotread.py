#!/usr/bin/env python3
"""Stand-in for ArgyllCMS spotread used to test the pexpect wrapper on a pty.

Replays the prompts and readings of ``session_colormunki.txt`` (same directory): a calibration
prompt, then one transcript reading per key press. 'q' exits.
"""

import os
import re
import sys
import termios
import time
import tty
from pathlib import Path

HERE = Path(__file__).parent
text = (HERE / "session_colormunki.txt").read_text()
blocks = re.findall(r"( Result is XYZ:.*?\nSpectrum from .*?\n.*?\n)", text, re.S)
fail_first = "--fail-once" in sys.argv
no_instrument = "--none" in sys.argv
fixed_block = os.environ.get("FAKE_SPOTREAD_BLOCK")

if "-?" in sys.argv:
    mode = os.environ.get("FAKE_SPOTREAD_PORTS", "colormunki")
    if mode == "hang":  # like a machine where port probing never finishes
        sys.stdout.write((HERE / "no_instrument.txt").read_text())
        sys.stdout.flush()
        time.sleep(60)
        sys.exit(1)
    sys.stdout.write((HERE / f"usage_{'no_ports' if mode == 'none' else mode}.txt").read_text())
    sys.stdout.flush()
    sys.exit(1)

READ = (
    "\nPlace instrument on spot to be measured,\n"
    "and hit [A-Z] to read white and setup FWA compensation (keyed to letter)\n"
    "Hit ESC or Q to exit, instrument switch or any other key to take a reading: "
)


def key() -> str:
    fd = sys.stdin.fileno()
    old = termios.tcgetattr(fd)
    try:
        tty.setraw(fd)
        return sys.stdin.read(1)
    finally:
        termios.tcsetattr(fd, termios.TCSADRAIN, old)


def out(s: str) -> None:
    sys.stdout.write(s)
    sys.stdout.flush()


out("Connecting to the instrument ..\n")
if no_instrument:
    out("Unknown, inappropriate or no instrument detected\n")
    sys.exit(1)
out(
    "Set instrument sensor to calibration position,\n and then hit any key to continue,\n or hit Esc or Q to abort: "
)
if key().lower() == "q":
    sys.exit(0)
out("\nCalibration complete\n")
i = 0
while True:
    out(READ)
    k = key()
    if k.lower() == "q":
        sys.exit(0)
    if fail_first and i == 0:
        fail_first = False
        out(
            "\nSpot read failed due to the sensor being in the wrong position\n"
            "Hit Esc or Q to give up, any other key to retry: "
        )
        key()
    out("\n" + blocks[int(fixed_block) if fixed_block is not None else i % len(blocks)])
    i += 1
