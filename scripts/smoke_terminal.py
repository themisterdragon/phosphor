#!/usr/bin/env python3
"""Run Phosphor Terminal in a pseudo-terminal (Linux/macOS), press a few keys, and check it
draws its screens and quits cleanly: python3 scripts/smoke_terminal.py COMMAND [ARGS...]"""
import os
import pty
import re
import select
import sys
import tempfile
import time

home = tempfile.mkdtemp(prefix="phosphor-smoke-")
env = dict(os.environ, TERM="xterm-256color", LINES="30", COLUMNS="100",
           XDG_CONFIG_HOME=os.path.join(home, "config"), XDG_DATA_HOME=os.path.join(home, "data"))
cmd = sys.argv[1:] + ["--no-boot"]
pid, fd = pty.fork()
if pid == 0:
    os.execvpe(cmd[0], cmd, env)

seen = ""


def read_until(pattern, timeout=40):
    global seen
    end = time.time() + timeout
    while time.time() < end:
        r, _, _ = select.select([fd], [], [], 0.5)
        if r:
            try:
                chunk = os.read(fd, 65536).decode("utf-8", "replace")
            except OSError:
                break
            seen += chunk
            plain = re.sub(r"\x1b\[[0-9;?]*[A-Za-z]|\x1b[()][A-Z0-9]|\x1b[=>]", "", seen)
            if re.search(pattern, plain):
                return True
    sys.exit(f"smoke test: never saw {pattern!r}; screen so far:\n"
             + re.sub(r"\x1b\[[0-9;?]*[A-Za-z]", " ", seen)[-1500:])


read_until(r"MAIN MENU")
os.write(fd, b"2")
read_until(r"ALL STORIES")
os.write(fd, b"\x1b")
time.sleep(0.5)
os.write(fd, b"5")
read_until(r"SAVE FOR OFFLINE")
os.write(fd, b"\x1b")
time.sleep(0.5)
os.write(fd, b"q")
read_until(r"BYE")
_, status = os.waitpid(pid, 0)
code = os.waitstatus_to_exitcode(status) if hasattr(os, "waitstatus_to_exitcode") else status >> 8
if code != 0:
    sys.exit(f"smoke test: exited with {code}")
print("terminal smoke test passed: main menu, stories, settings, quit")
