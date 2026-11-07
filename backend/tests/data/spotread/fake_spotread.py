#!/usr/bin/env python3
"""Stand-in for ArgyllCMS spotread used to test the pexpect wrapper on a pty.

Replays the prompts and readings of ``session_colormunki.txt`` (same directory): a calibration
prompt, then one transcript reading per key press. 'q' exits.
"""

import re
import sys
import termios
import tty
from pathlib import Path

text = (Path(__file__).parent / "session_colormunki.txt").read_text()
blocks = re.findall(r"( Result is XYZ:.*?\nSpectrum from .*?\n.*?\n)", text, re.S)
fail_first = "--fail-once" in sys.argv
no_instrument = "--none" in sys.argv

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
    out("\n" + blocks[i % len(blocks)])
    i += 1
