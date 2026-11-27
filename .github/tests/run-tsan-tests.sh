#!/usr/bin/env bash
# Runs the host tests that play through the whole player with a sanitizer
# build of the host player (tests/build.sh) and collects the reports: one
# directory per test, one file per player process
# (<work>/reports/<test>/<san>.<pid>). A measuring tool: a test that fails
# or runs out of time under the sanitizer is noted, the script still ends
# with 0.
#
# SAN=tsan (default): ThreadSanitizer, every data race / lock order report.
# SAN=lsan: AddressSanitizer with LeakSanitizer on (the normal ASan step of
#           tests.yml runs with detect_leaks=0); the leak report is written
#           when the player ends with exit() (q, end of stream), not on the
#           _exit() of the stop signal fallbacks. Suppressions:
#           .github/tests/lsan.supp.
#
# usage: run-tsan-tests.sh <exteplayer3 tree> <work directory>
# needs: FFMPEG_SOURCE, FFMPEG_BUILD, FFMPEG_EXTRA_LIBS (see tests.yml);
#        TESTS = test ids, comma separated (empty = all)

set -u
: "${FFMPEG_SOURCE:?}" "${FFMPEG_BUILD:?}"
UT=$(cd "$1" && pwd)
mkdir -p "$2/logs" "$2/out" "$2/reports"
W=$(cd "$2" && pwd)
OUT=$W/out
FF=$FFMPEG_BUILD/ffmpeg
DRIVER=$FFMPEG_BUILD/libavformat/tests/hls_http
FIFO=$OUT/audio.fifo
APES=$OUT/audio.pes
VPES=$OUT/video.pes
RESULTS=$W/results.tsv
: > "$RESULTS"
TESTS=${TESTS:-}
SAN=${SAN:-tsan}
case $SAN in
  tsan) SAN_CFLAGS="-fsanitize=thread -O1 -fno-omit-frame-pointer" ;;
  lsan) SAN_CFLAGS="-fsanitize=address -fno-omit-frame-pointer" ;;
  *) echo "SAN must be tsan or lsan" >&2; exit 2 ;;
esac

selected() { [ -z "$TESTS" ] || case ",$TESTS," in *",$1,"*) true;; *) false;; esac; }
note() { printf '%s\t%s\t%s\n' "$1" "$2" "$3" >> "$RESULTS"; }

# halt_on_error=0: every race, not only the first; exitcode=0: the reports
# do not change the exit status the tests check; report_signal_unsafe=0: the
# stop signal handlers are known to call what they call
tsan_options() { # tsan_options <test id>
  mkdir -p "$W/reports/$1"
  echo "halt_on_error=0 exitcode=0 report_signal_unsafe=0 second_deadlock_stack=1 history_size=7 log_path=$W/reports/$1/tsan"
}
# detect_leaks=1 with exitcode=0: the leak report does not change the exit
# status the tests check; report_objects=1: the address of every object
asan_options() { # asan_options <test id>
  mkdir -p "$W/reports/$1"
  echo "detect_leaks=1:exitcode=0:log_path=$W/reports/$1/lsan:malloc_context_size=30"
}
lsan_options() {
  echo "report_objects=1:exitcode=0:suppressions=$UT/.github/tests/lsan.supp:print_suppressions=1"
}

# step <id> <seconds> <command...>: under the sanitizer, result noted, never fatal
step() {
  local id=$1 tmo=$2 start=$SECONDS state rc
  shift 2
  rm -f "$FIFO" "$APES" "$VPES"
  echo "::group::$id"
  echo "+ $*"
  if [ "$SAN" = tsan ]; then
    (cd "$UT" && TSAN_OPTIONS=$(tsan_options "$id") timeout -k 10 "$tmo" "$@") 2>&1 | tee "$W/logs/$id.log"
  else
    (cd "$UT" && ASAN_OPTIONS=$(asan_options "$id") LSAN_OPTIONS=$(lsan_options) \
      timeout -k 10 "$tmo" "$@") 2>&1 | tee "$W/logs/$id.log"
  fi
  rc=${PIPESTATUS[0]}
  echo "::endgroup::"
  case $rc in
    0) state=pass ;;
    124|137) state="TIMEOUT after $tmo s" ;;
    *) state="FAIL (exit $rc)" ;;
  esac
  note "$id" "$state" "$((SECONDS - start)) s"
}

# build <variant> <environment...>: the TSan host player of tests/build.sh
build() {
  local name=$1 start=$SECONDS rc
  shift
  echo "::group::build $name"
  (cd "$UT" && env "CFLAGS=$SAN_CFLAGS -DPCM_EXPORT_PATH=\"$FIFO\"" "$@" \
    sh tests/build.sh "$OUT/exteplayer3-$name") 2>&1 | tee "$W/logs/build-$name.log"
  rc=${PIPESTATUS[0]}
  echo "::endgroup::"
  if [ "$rc" = 0 ]; then
    note "build-$name" pass "$((SECONDS - start)) s"
    return 0
  fi
  note "build-$name" "FAIL (exit $rc)" "$((SECONDS - start)) s"
  return 1
}

host=no; capture=no; timing=no
if selected integration || selected cover || selected chapters || selected hls_switch-export; then
  build host && host=yes
fi
if selected hls_switch-compressed || selected hls_switch-software; then
  build capture "HOST_AUDIO_OUTPUT=$APES" HOST_HLS_ALIAS=1 && capture=yes
fi
if selected first_keyframe || selected hls_switch-timing; then
  build timing "HOST_AUDIO_OUTPUT=$APES" "HOST_VIDEO_OUTPUT=$VPES" HOST_HLS_ALIAS=1 && timing=yes
fi

if [ $host = yes ]; then
  selected integration && step integration 2400 \
    python3 tests/integration.py --player "$OUT/exteplayer3-host" --ffmpeg "$FF" --pcm-fifo "$FIFO"
  selected cover && step cover 900 \
    python3 tests/cover.py --player "$OUT/exteplayer3-host" --ffmpeg "$FF"
  selected chapters && step chapters 1800 \
    python3 tests/chapters.py --player "$OUT/exteplayer3-host" --ffmpeg "$FF"
  selected hls_switch-export && step hls_switch-export 1800 \
    python3 tests/hls_switch.py --player "$OUT/exteplayer3-host" --ffmpeg "$FF" --pcm-fifo "$FIFO"
fi
if [ $capture = yes ]; then
  selected hls_switch-compressed && step hls_switch-compressed 1800 \
    python3 tests/hls_switch.py --player "$OUT/exteplayer3-capture" --ffmpeg "$FF" --pcm-fifo "$FIFO" \
    --audio-output "$APES" --mode compressed --multiple --video-first --quality all
  selected hls_switch-software && step hls_switch-software 1800 \
    python3 tests/hls_switch.py --player "$OUT/exteplayer3-capture" --ffmpeg "$FF" --pcm-fifo "$FIFO" \
    --audio-output "$APES" --mode software
fi
if [ $timing = yes ]; then
  selected first_keyframe && step first_keyframe 900 \
    python3 tests/first_keyframe.py --player "$OUT/exteplayer3-timing" --ffmpeg "$FF" \
    --video-output "$VPES" --audio-output "$APES"
  if selected hls_switch-timing && [ -x "$DRIVER" ]; then
    step hls_switch-timing 1800 \
      python3 tests/hls_switch.py --player "$OUT/exteplayer3-timing" --ffmpeg "$FF" --pcm-fifo "$FIFO" \
      --audio-output "$APES" --video-output "$VPES" --timing-driver "$DRIVER" \
      --mode compressed --case live --multiple --video-first --quality all --sync default --backpressure
  fi
fi

{
  echo "### Host tests under $SAN: exteplayer3 $(git -C "$UT" rev-parse --short=10 HEAD)"
  echo
  echo "The results only say whether a test still passed with the slower sanitizer player;"
  echo "what counts are the reports below."
  echo
  echo "| step | result | time | $SAN log files |"
  echo "|---|---|---|---|"
  while IFS=$'\t' read -r id state time; do
    n=$(find "$W/reports/$id" -type f 2>/dev/null | wc -l)
    echo "| $id | $state | $time | $n |"
  done < "$RESULTS"
  echo
} | tee "$W/summary.md"
if [ -n "${GITHUB_STEP_SUMMARY:-}" ]; then cat "$W/summary.md" >> "$GITHUB_STEP_SUMMARY"; fi
exit 0
