#!/usr/bin/env python3
"""Leak sites of the LeakSanitizer host tests.

usage: lsan_report.py <reports directory> [--json <file>]

Reads every ASan/LSan log file below the directory (run-tsan-tests.sh with
SAN=lsan writes <reports>/<test>/lsan.<pid>), takes each "Direct/Indirect
leak of N byte(s) in K object(s)" block and counts it per leak site: the
kind and the first two frames of the allocation stack that are in the
player's own sources (the allocator below them, e.g. av_malloc, is shown
apart). Prints a Markdown summary with bytes and objects per site; "most in
one process" is the highest object count one player process left: a site
that leaks once per segment, switch or seek has a count that grows with
the length of the test, a one-time leak stays at 1. Other ASan errors in
the logs (they end the process) are listed too.
"""

import argparse
import json
import re
import sys
from pathlib import Path

SOURCE_DIRS = ("container/", "main/", "output/", "manager/", "playback/", "tools/", "external/")
LEAK = re.compile(r"^(Direct|Indirect) leak of (\d+) byte\(s\) in (\d+) object\(s\) allocated from:")
FRAME = re.compile(r"^\s+#\d+ 0x[0-9a-f]+ in (\S+)(?: (\S+?:\d+|\S+?)(?::\d+)?)?(?: \((\S+)\))?\s*$")
ERROR = re.compile(r"^==\d+==ERROR: AddressSanitizer: (\S+)")
ALLOCATORS = ("malloc", "calloc", "realloc", "posix_memalign", "memalign", "aligned_alloc",
              "strdup", "strndup", "__interceptor_", "operator")


def source(path):
    if not path:
        return None
    for d in SOURCE_DIRS:
        i = path.rfind("/" + d)
        if i >= 0:
            return path[i + 1:]
        if path.startswith(d):
            return path
    return None


def site(frames):
    own = [f"{fn} {source(p)}" for fn, p in frames if source(p)]
    lib = next((fn for fn, p in frames
                if not source(p) and not fn.startswith(ALLOCATORS)), "")
    return tuple(own[:2]) or (f"(no player frame) {lib}",), lib


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("reports")
    ap.add_argument("--json")
    args = ap.parse_args()
    root = Path(args.reports)
    sites, errors = {}, {}
    files = sorted(p for p in root.rglob("*") if p.is_file())
    procs = 0
    for f in files:
        test = f.relative_to(root).parts[0] if f.parent != root else "?"
        lines = f.read_text(errors="replace").splitlines()
        procs += 1
        per_proc = {}
        i = 0
        while i < len(lines):
            m = ERROR.match(lines[i])
            if m and m.group(1) != "":
                e = errors.setdefault(m.group(1), {"count": 0, "tests": set(), "text": ""})
                e["count"] += 1
                e["tests"].add(test)
                if not e["text"]:
                    e["text"] = "\n".join(lines[i:i + 40])
            m = LEAK.match(lines[i])
            if not m:
                i += 1
                continue
            kind, nbytes, nobj = m.group(1), int(m.group(2)), int(m.group(3))
            frames, j = [], i + 1
            while j < len(lines) and lines[j].strip().startswith("#"):
                fm = FRAME.match(lines[j])
                if fm:
                    frames.append((fm.group(1), fm.group(2) or fm.group(3) or ""))
                j += 1
            own, lib = site(frames)
            k = (kind,) + own
            s = sites.get(k)
            if s is None:
                s = sites[k] = {"kind": kind, "site": list(own), "allocator": lib, "bytes": 0,
                                "objects": 0, "processes": 0, "max_objects": 0, "tests": set(),
                                "text": "\n".join(lines[i:j])}
            s["bytes"] += nbytes
            s["objects"] += nobj
            s["tests"].add(test)
            per_proc[k] = per_proc.get(k, 0) + nobj
            i = j
        for k, n in per_proc.items():
            sites[k]["processes"] += 1
            sites[k]["max_objects"] = max(sites[k]["max_objects"], n)
    items = sorted(sites.values(), key=lambda s: (s["kind"] != "Direct", -s["max_objects"], -s["bytes"]))
    print("### LeakSanitizer: leak sites")
    print()
    print(f"{procs} player processes with a log file, **{len(items)} leak sites** "
          "(by kind and the first two allocation frames in the player).")
    print()
    if items:
        print("| # | kind | bytes | objects | processes | most in one process | allocated in | via | tests |")
        print("|---|---|---|---|---|---|---|---|---|")
        for n, s in enumerate(items, 1):
            where = " &larr; ".join(f"`{x}`" for x in s["site"])
            print(f"| {n} | {s['kind']} | {s['bytes']} | {s['objects']} | {s['processes']} | "
                  f"{s['max_objects']} | {where} | {s['allocator']} | {', '.join(sorted(s['tests']))} |")
    if errors:
        print()
        print("Other AddressSanitizer errors (each ends that player process):")
        print()
        for name, e in sorted(errors.items()):
            print(f"- {name}: {e['count']} ({', '.join(sorted(e['tests']))})")
    if args.json:
        for s in items:
            s["tests"] = sorted(s["tests"])
        for e in errors.values():
            e["tests"] = sorted(e["tests"])
        Path(args.json).write_text(json.dumps({"sites": items, "errors": errors}, indent=1))
    return 0


if __name__ == "__main__":
    sys.exit(main())
