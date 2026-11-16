#!/usr/bin/env python3
"""Matrix of the player builds as JSON for GITHUB_OUTPUT.

usage: matrix.py <players.txt> [list] [arches] [arches]
  list: "name repo ref" entries separated by newlines or ';'; when
  empty, the file is used. Lines starting with # are comments.
  arches: Debian architectures (armhf mipsel), empty: both. With the word
  "arches" as fourth argument: the matrix of the architectures alone.
"""
import json
import re
import sys

text = sys.argv[2] if len(sys.argv) > 2 and sys.argv[2].strip() else open(sys.argv[1]).read()
out = []
entries = []
for line in text.splitlines():
    entries += line.split('#', 1)[0].split(';')
for entry in entries:
    entry = entry.strip()
    if not entry:
        continue
    parts = entry.split()
    if len(parts) != 3:
        sys.exit('bad entry (name repo ref): %r' % entry)
    name, repo, ref = parts
    if not re.match(r'^[A-Za-z0-9._-]+$', name) or not re.match(r'^[A-Za-z0-9._-]+/[A-Za-z0-9._-]+$', repo) \
            or not re.match(r'^[A-Za-z0-9._/-]+$', ref):
        sys.exit('bad characters in %r' % entry)
    out.append(dict(name=name, repo=repo, ref=ref))
if not out:
    sys.exit('no player given')
LABELS = {'armhf': 'armv7ahf', 'mipsel': 'mips32el'}
arches = (sys.argv[3] if len(sys.argv) > 3 else '').replace(',', ' ').split() or ['armhf', 'mipsel']
for a in arches:
    if a not in LABELS:
        sys.exit('unknown architecture %r' % a)
if len(sys.argv) > 4 and sys.argv[4] == 'arches':
    print(json.dumps(dict(include=[dict(arch=a, label=LABELS[a]) for a in arches])))
else:
    print(json.dumps(dict(include=[dict(p, arch=a, label=LABELS[a]) for a in arches for p in out])))
