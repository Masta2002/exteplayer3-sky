#!/usr/bin/env python3
"""Unique ThreadSanitizer reports of the TSan host tests.

usage: tsan_report.py <reports directory> [--json <file>]

Reads every TSan log file below the directory (run-tsan-tests.sh writes
<reports>/<test>/tsan.<pid>), splits it into reports and counts each report
once per kind and pair of source locations: the first frame of each access
that is in the player's own sources. Prints a Markdown summary; --json
writes the unique reports with the full text of their first occurrence.
"""

import argparse
import json
import re
import sys
from pathlib import Path

SOURCE_DIRS = ("container/", "main/", "output/", "manager/", "playback/", "tools/", "external/")
HEADER = re.compile(r"^WARNING: ThreadSanitizer: (.+?) \(pid=\d+\)")
ACCESS = re.compile(r"^  (Previous )?((?:atomic )?(?:write|read))[^:]*? by (main thread|thread T\d+)", re.I)
# "#0 func path/file.c:123:5 (module+0x..)": the column is dropped
FRAME = re.compile(r"^\s+#\d+ (\S+) (\S+?:\d+|\S+?)(?::\d+)? \(")
CREATED = re.compile(r"^  Thread (T\d+) .*created by (main thread|thread T\d+) at:")
LOCATION = re.compile(r"^  Location is (.*?)(?: at 0x[0-9a-f]+.*)?$")
SUMMARY = re.compile(r"^SUMMARY: ThreadSanitizer: (.*)$")


def source(path):
    """container/x.c:12 for a frame in the player's sources, else None."""
    for d in SOURCE_DIRS:
        i = path.rfind("/" + d)
        if i >= 0:
            return path[i + 1:]
        if path.startswith(d):
            return path
    return None


def first_own(frames):
    for func, path in frames:
        s = source(path)
        if s:
            return f"{func} {s}"
    return frames[0][0] + " (not in the player)" if frames else "?"


def split_reports(text):
    reports, cur = [], None
    for line in text.splitlines():
        if line.startswith("=================="):
            if cur:
                reports.append(cur)
            cur = []
            continue
        if cur is not None:
            cur.append(line)
    if cur:
        reports.append(cur)
    return [r for r in reports if any(HEADER.match(l) for l in r)]


def parse(lines):
    rep = {"kind": "?", "accesses": [], "location": "", "threads": {}, "summary": ""}
    section = None
    for line in lines:
        m = HEADER.match(line)
        if m:
            rep["kind"] = m.group(1)
            continue
        m = ACCESS.match(line)
        if m:
            section = {"op": m.group(2).lower(), "previous": bool(m.group(1)),
                       "thread": m.group(3), "frames": []}
            rep["accesses"].append(section)
            continue
        m = CREATED.match(line)
        if m:
            section = {"thread": m.group(1), "frames": []}
            rep["threads"][m.group(1)] = section
            continue
        m = LOCATION.match(line)
        if m:
            rep["location"] = m.group(1)
            section = None
            continue
        m = SUMMARY.match(line)
        if m:
            rep["summary"] = m.group(1)
            section = None
            continue
        if line.startswith("  ") and not line.startswith("    "):
            # another block (mutex created at, ...): its frames are not kept
            section = None
            continue
        m = FRAME.match(line)
        if m and section is not None:
            section["frames"].append((m.group(1), m.group(2)))
    return rep


def role(rep, thread):
    if thread == "main thread":
        return "main"
    t = thread.split()[-1]
    created = rep["threads"].get(t)
    if not created:
        return t
    where = first_own(created["frames"])
    return f"thread created in {where.split()[0]}"


def key_of(rep):
    if len(rep["accesses"]) >= 2:
        a = tuple(sorted(first_own(x["frames"]) for x in rep["accesses"][:2]))
        return (rep["kind"],) + a
    return (rep["kind"], rep["summary"])


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("reports")
    ap.add_argument("--json")
    args = ap.parse_args()
    root = Path(args.reports)
    unique, total = {}, 0
    files = sorted(p for p in root.rglob("*") if p.is_file())
    for f in files:
        test = f.relative_to(root).parts[0] if f.parent != root else "?"
        text = f.read_text(errors="replace")
        for lines in split_reports(text):
            total += 1
            rep = parse(lines)
            k = key_of(rep)
            u = unique.get(k)
            if u is None:
                u = unique[k] = {"kind": rep["kind"], "count": 0, "tests": set(),
                                 "location": rep["location"], "summary": rep["summary"],
                                 "accesses": [{"op": ("previous " if a["previous"] else "") + a["op"],
                                               "where": first_own(a["frames"]),
                                               "thread": role(rep, a["thread"])}
                                              for a in rep["accesses"][:2]],
                                 "text": "\n".join(lines).strip()}
            u["count"] += 1
            u["tests"].add(test)
    items = sorted(unique.values(), key=lambda u: (u["kind"], -u["count"]))
    print("### ThreadSanitizer: unique reports")
    print()
    print(f"{len(files)} log files, {total} reports, **{len(items)} unique** "
          "(by kind and the pair of source locations).")
    print()
    if items:
        print("| # | kind | seen | access 1 | access 2 | location | tests |")
        print("|---|---|---|---|---|---|---|")
        for i, u in enumerate(items, 1):
            acc = [f"{a['op']} `{a['where']}` ({a['thread']})" for a in u["accesses"]]
            while len(acc) < 2:
                acc.append(u["summary"] if not acc else "")
            loc = u["location"].replace("|", "/")[:80]
            print(f"| {i} | {u['kind']} | {u['count']} | {acc[0]} | {acc[1]} | {loc} | "
                  f"{', '.join(sorted(u['tests']))} |")
    if args.json:
        for u in items:
            u["tests"] = sorted(u["tests"])
        Path(args.json).write_text(json.dumps(items, indent=1))
    return 0


if __name__ == "__main__":
    sys.exit(main())
