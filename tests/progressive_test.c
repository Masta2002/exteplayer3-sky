#include <assert.h>
#include "../container/container_ffmpeg.c"

static int stopped, source_reads;
static uint8_t target[64];

int8_t PlaybackDieNow(int8_t value)
{
    (void)value;
    return stopped;
}

void E2iSendMsg(const char *format, ...)
{
    (void)format;
}

/* Output follow-up: the last block of a file whose download has ended. */

static int tail_reads;

static int tail(void *opaque, uint8_t *data, int size)
{
    (void)opaque;
    if (tail_reads++)
        return AVERROR_EOF;
    assert(size > 10);
    memset(data, 9, 10);
    return 10;
}

static void last_partial_block_is_returned(void)
{
    ffmpeg_real_read_org = tail;
    finishTimeout = TIMEOUT_MAX_ITERS + 1; /* Nothing more is waited for. */
    assert(ffmpeg_read_wrapper_base(NULL, target, sizeof(target), 0) == 10);
    assert(tail_reads == 2 && target[0] == 9 && target[9] == 9);
    assert(ffmpeg_read_wrapper_base(NULL, target, sizeof(target), 0) == AVERROR_EOF);
    finishTimeout = 0;
}

/* A read callback of FFmpeg: an error at the current end, then the data. */
static int source(void *opaque, uint8_t *data, int size)
{
    (void)opaque;
    if (!source_reads++)
        return AVERROR_EOF;
    assert(data == target && size == sizeof(target));
    memset(data, 7, size);
    return size;
}

static void data_after_a_failed_first_read(void)
{
    assert(ffmpeg_read_wrapper_base(NULL, target, sizeof(target), 0) == sizeof(target));
    assert(source_reads == 2 && target[0] == 7 && target[sizeof(target) - 1] == 7);
}

static void end_is_reported_as_eof(void)
{
    stopped = 1;
    assert(ffmpeg_read_wrapper_base(NULL, target, sizeof(target), 0) == AVERROR_EOF);
    stopped = 0;
}

int main(void)
{
    Context_t context = {0};
    g_context = &context;
    last_partial_block_is_returned();
    ffmpeg_real_read_org = source;
    data_after_a_failed_first_read();
    end_is_reported_as_eof();
    return 0;
}
