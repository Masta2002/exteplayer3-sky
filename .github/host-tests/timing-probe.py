#!/usr/bin/env python3
"""Runs tests/hls_switch.py of the tree under test in its timing mode and
reports the numbers behind its "within 100 ms of the source" assertion.

usage: timing-probe.py <tree under test> <log directory> <label> -- <arguments of hls_switch.py>

The test file in the tree is not changed. Its source is loaded, and in the
copy in memory the one line

    assert min(errors) <= 9000, (kind, pts, candidates, self.offset, errors)

is replaced by a call that records the deviation of every PES packet (PTS
written by the player minus the PTS the source media has for the same
payload, 90 kHz) and then asserts against TIMING_BOUND (default 9000, the
bound of the test). With a larger TIMING_BOUND the run continues past the
first deviation, so that all selections of a run are measured. The complete
stdout of each player process is kept in the log directory.
"""

import os
import sys
import time
import types

tree, logs, label = sys.argv[1:4]
assert sys.argv[4] == "--"
arguments = sys.argv[5:]
bound = int(os.environ.get("TIMING_BOUND") or 9000)
tests = os.path.join(tree, "tests")
sys.path.insert(0, tests)

import integration  # noqa: E402  (the tree's own helper)
import tempfile  # noqa: E402

players = []


def player_log():
    path = os.path.join(logs, f"{label}-player{len(players)}.log")
    players.append(path)
    return open(path, "w+b")


# integration.Player keeps the stdout of the player in an anonymous temporary
# file and prints its last 12000 characters after a failure; give it a named
# file instead, so that the whole log is there afterwards.
shim = types.ModuleType("tempfile")
shim.__dict__.update(tempfile.__dict__)
shim.TemporaryFile = player_log
integration.tempfile = shim

state = {"t0": None, "last": {}, "worst": {}, "count": {}, "rows": []}


def probe(kind, pts, candidates, offset, offsets, errors):
    now = time.monotonic()
    if state["t0"] is None:
        state["t0"] = now
    index = errors.index(min(errors))
    signed = (offsets[index] - offset + (1 << 32)) % (1 << 33) - (1 << 32)
    name = "video" if kind == -1 else f"audio{kind}"
    state["count"][name] = state["count"].get(name, 0) + 1
    if abs(signed) > abs(state["worst"].get(name, 0)):
        state["worst"][name] = signed
    key = "video" if kind == -1 else "audio"
    if state["last"].get(key) != (name, signed):
        state["last"][key] = (name, signed)
        row = (f"probe t={now - state['t0']:7.3f}s {name} deviation={signed:+6d} ticks "
               f"({signed / 90:+7.1f} ms) pts={pts} source_us={candidates[index]}")
        state["rows"].append(row)
        print(row, flush=True)
    assert min(errors) <= bound, (kind, pts, candidates, offset, errors)


path = os.path.join(tests, "hls_switch.py")
with open(path, encoding="utf-8") as stream:
    source = stream.read()
wanted = "assert min(errors) <= 9000, (kind, pts, candidates, self.offset, errors)"
assert source.count(wanted) == 1, "the assertion of the timing mode was not found"
source = source.replace(wanted, "_probe(kind, pts, candidates, self.offset, offsets, errors)")
module = {"__name__": "__main__", "__file__": path, "_probe": probe}
sys.argv = [path, *arguments]
result = "pass"
try:
    exec(compile(source, path, "exec"), module)
except AssertionError as error:
    result = f"FAIL {str(error)[:200]}"
    import traceback
    traceback.print_exc()
except BaseException as error:  # noqa: BLE001 - report, then fail
    result = f"ERROR {type(error).__name__}: {str(error)[:200]}"
    import traceback
    traceback.print_exc()

worst = max((abs(value) for value in state["worst"].values()), default=0)
changes = len([row for row in state["rows"] if " audio" in row])
print(f"probe-summary label={label} bound={bound} result={result.split()[0]} "
      f"worst_ticks={worst} worst_ms={worst / 90:.1f} audio_deviation_changes={changes} "
      f"packets={sum(state['count'].values())} worst_by_stream={state['worst']}", flush=True)
for number, name in enumerate(players):
    try:
        with open(name, errors="replace") as stream:
            for line in stream:
                if ("audio selection" in line or "live sync" in line or "first video" in line
                        or "first audio" in line or "video clock" in line
                        or "playback timing" in line):
                    print(f"player{number}: {line.rstrip()[:400]}")
    except OSError as error:
        print(f"player{number}: log not readable: {error}")
sys.exit(0 if result == "pass" else 1)
