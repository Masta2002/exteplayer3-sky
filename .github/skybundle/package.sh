#!/bin/bash
# Runs on the runner after player.sh: manifest (with the GLIBC check),
# tarball and ipk of the bundle.
# usage: package.sh <out/player> <name> <dist directory>
# environment: MAX_GLIBC, DEPS_RPATH, PLAYER_DIR, PLAYER_REPO, PLAYER_SHA,
#              FFMPEG_REPO, FFMPEG_SHA, FFMPEG_RELEASE
set -eux
P=$1
NAME=$2
mkdir -p "$3"
DIST=$(cd "$3" && pwd)
HERE=$(cd "$(dirname "$0")" && pwd)
BD=$P/bundle

rc=0
python3 "$HERE/elfinfo.py" --max-glibc "$MAX_GLIBC" --bundled-dir "$BD/lib/exteplayer3_deps" \
    --json "$BD/manifest.json" "$BD" > "$BD/manifest.txt" || rc=$?
sed -i "s#^== $BD/#== #" "$BD/manifest.txt"
cat "$BD/manifest.txt"
# version: the number after the format string of the EPLAYER3_EXTENDED message
VERSION=$(sed -n '/EPLAYER3_EXTENDED.*version/,/;/p' "$PLAYER_DIR/main/exteplayer.c" | tr -d '\n' |
    sed -n 's/.*", *\([0-9][0-9]*\)[,)].*/\1/p' | head -1) || true
GLIBC=$(python3 -c "import json,sys; print(json.load(open(sys.argv[1]))['glibc_max'])" "$BD/manifest.json")
{
    echo "name:        $NAME"
    echo "exteplayer3: $PLAYER_REPO $PLAYER_SHA (version ${VERSION:-?})"
    echo "ffmpeg:      $FFMPEG_REPO $FFMPEG_SHA ($FFMPEG_RELEASE)"
    echo "rpath:       exteplayer3 $DEPS_RPATH"
    echo "glibc:       highest GLIBC_ version required: $GLIBC (limit $MAX_GLIBC)"
    echo "built:       Debian 8 armhf userland under qemu-user, GCC 4.9.2, glibc 2.19, $(date -u +%Y-%m-%d)"
    echo "libraries:"
    sed 's/^/  /' "$BD/lib/exteplayer3_deps.versions" 2> /dev/null
    echo "smoke tests (qemu-user):"
    sed 's/^/  /' "$P/smoke.txt"
} > "$BD/BUILDINFO"
cat "$BD/BUILDINFO"

T=exteplayer3-ff9-armv7ahf-$NAME
tar --owner=0 --group=0 -C "$BD" -czf "$DIST/$T.tar.gz" .

# ipk as the one of skyjet18: /usr/bin/exteplayer3, /usr/lib/exteplayer3_deps
W=$(mktemp -d)
mkdir -p "$W/data/usr/bin" "$W/data/usr/lib" "$W/control"
cp -a "$BD/bin/exteplayer3" "$W/data/usr/bin/"
cp -a "$BD/lib/exteplayer3_deps" "$W/data/usr/lib/"
cat > "$W/control/control" <<EOF
Package: exteplayer3
Version: ${VERSION:-0}+ff9+$NAME+${PLAYER_SHA:0:7}
Description: exteplayer3 with FFmpeg 9 and its libraries in /usr/lib/exteplayer3_deps
Section: multimedia
Priority: optional
Maintainer: none
License: GPL-2.0-or-later
Architecture: all
OE: exteplayer3
Homepage: https://github.com/$PLAYER_REPO
Depends: libc6 (>= $GLIBC)
Source: https://github.com/$PLAYER_REPO
EOF
echo "2.0" > "$W/debian-binary"
tar --owner=0 --group=0 -C "$W/control" -czf "$W/control.tar.gz" ./control
tar --owner=0 --group=0 -C "$W/data" -czf "$W/data.tar.gz" ./usr
( cd "$W" && ar -r "$DIST/$T.ipk" debian-binary control.tar.gz data.tar.gz 2> /dev/null )
rm -rf "$W"
cp "$BD/manifest.txt" "$DIST/$T.manifest.txt"
cp "$BD/BUILDINFO" "$DIST/$T.BUILDINFO"
ls -la "$DIST"

{
    echo "### $NAME"
    echo '```'
    cat "$BD/BUILDINFO"
    echo
    grep -A40 '^highest GLIBC' "$BD/manifest.txt"
    echo '```'
} >> "${GITHUB_STEP_SUMMARY:-/dev/null}"
exit $rc
