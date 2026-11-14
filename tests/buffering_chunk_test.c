#include <assert.h>
#include <signal.h>
#include <sys/select.h>
#include "../output/linuxdvb_buffering.c"

static int8_t stop_requested(void);

int8_t PlaybackDieNow(int8_t value)
{
    (void)value;
    return stop_requested();
}

static void blocked(int number)
{
    static const char text[] = "BufferingWriteV waits for room a single chunk can never get\n";
    (void)number;
    if (write(2, text, sizeof(text) - 1) < 0)
        _exit(2);
    _exit(1);
}

/* Output follow-up: the end of the buffering thread, an interrupted select(). */

static int stopped, stop_in_flush, interrupts;
static pthread_t command_thread;
static const char *hang;

/* With stop_in_flush the playback is terminated from another thread right
 * after the flush on the command thread has seen it alive. */
static int8_t stop_requested(void)
{
    if (stop_in_flush && g_bDuringWrite && pthread_equal(pthread_self(), command_thread))
    {
        stop_in_flush = 0;
        stopped = 1;
        WriteWakeUp();
        return 0;
    }
    return stopped;
}

bool PlaybackDieNowRegisterCallback(PlaybackDieNowCallback callback)
{
    (void)callback;
    return true;
}

/* Replaces select() of the C library: WriteWithRetry() can be interrupted. */
int select(int count, fd_set *readable, fd_set *writable, fd_set *failed, struct timeval *timeout)
{
    struct timespec limit;
    if (interrupts)
    {
        interrupts--;
        errno = EINTR;
        return -1;
    }
    if (timeout)
    {
        limit.tv_sec = timeout->tv_sec;
        limit.tv_nsec = timeout->tv_usec * 1000;
    }
    return pselect(count, readable, writable, failed, timeout ? &limit : NULL, NULL);
}

static void hung(int number)
{
    (void)number;
    if (write(2, hang, strlen(hang)) < 0)
        _exit(2);
    _exit(1);
}

static bool thread_writes(void)
{
    bool result;
    pthread_mutex_lock(&bufferingMtx);
    result = g_bDuringWrite;
    pthread_mutex_unlock(&bufferingMtx);
    return result;
}

static bool thread_ended(void)
{
    return !hasBufferingThreadStarted && g_pfd[1] == -1;
}

static void wait_for(bool (*event)(void), const char *otherwise)
{
    hang = otherwise;
    alarm(5);
    while (!event())
        usleep(1000);
    alarm(0);
}

static void interrupted_select_is_repeated(Context_t *context)
{
    int wake[2], output[2];
    char data = 0;
    assert(!pipe(wake) && !pipe(output));
    assert(fcntl(output[0], F_SETFL, O_NONBLOCK) >= 0);
    interrupts = 1;
    assert(!WriteWithRetry(context, wake[0], output[1], NULL, "v", 1, 1));
    assert(!interrupts && read(output[0], &data, 1) == 1 && data == 'v');
    close(wake[0]);
    close(wake[1]);
    close(output[0]);
    close(output[1]);
}

static void thread_end(void)
{
    static char block[4096];
    uint8_t frame[256] = {1, 2, 3};
    struct iovec vector = {frame, sizeof(frame)};
    PlaybackHandler_t playback = {0};
    Context_t context = {.playback = &playback};
    int decoder[2];

    interrupted_select_is_repeated(&context);
    /* A decoder that takes no data: the write of the thread does not return. */
    assert(!pipe(decoder) && fcntl(decoder[1], F_SETFL, O_NONBLOCK) >= 0);
    while (write(decoder[1], block, sizeof(block)) > 0)
        ;
    assert(errno == EAGAIN);
    signal(SIGALRM, hung);
    bufferingQueueHead = bufferingQueueTail = NULL;
    bufferingDataSize = 0;
    videofd = -1;

    /* A close without a stop before it, as after a failed OUTPUT_PLAY. */
    assert(!LinuxDvbBuffOpen(&context, "video", decoder[1], NULL));
    LinuxDvbBuffClose(&context);
    wait_for(thread_ended, "LinuxDvbBuffClose has not ended the buffering thread\n");

    /* A flush that waits for the write while the playback is terminated. */
    assert(!LinuxDvbBuffOpen(&context, "video", decoder[1], NULL));
    assert(BufferingWriteV(decoder[1], &vector, 1) == sizeof(frame));
    wait_for(thread_writes, "the buffering thread does not write the chunk\n");
    command_thread = pthread_self();
    stop_in_flush = 1;
    hang = "LinuxDvbBuffFlush still waits for a thread that has ended\n";
    alarm(5);
    assert(!LinuxDvbBuffFlush(&context));
    alarm(0);
    assert(stopped && !stop_in_flush);
    wait_for(thread_ended, "the buffering thread has not ended with the playback\n");

    /* Not queued any more: the result is the size of the data, as for a queued chunk. */
    assert(BufferingWriteV(decoder[1], &vector, 1) == sizeof(frame));
    assert(!bufferingQueueHead && !bufferingDataSize);
    stopped = 0;
    assert(!LinuxDvbBuffClose(&context));
    close(decoder[0]);
    close(decoder[1]);
}

int main(void)
{
    uint8_t frame[256] = {1, 2, 3};
    struct iovec vector = {frame, sizeof(frame)};
    BufferingNode_t *node;

    assert(!pthread_mutex_init(&bufferingMtx, NULL));
    assert(!pthread_cond_init(&bufferingDataConsumedCond, NULL));
    assert(!pthread_cond_init(&bufferingdDataAddedCond, NULL));
    videofd = 7;
    maxBufferingDataSize = 128;
    signal(SIGALRM, blocked);
    alarm(3);
    /* One frame larger than the whole buffer, with nothing queued to be consumed. */
    assert(BufferingWriteV(videofd, &vector, 1) == sizeof(frame));
    alarm(0);
    node = bufferingQueueHead;
    assert(node && node == bufferingQueueTail && !node->next);
    assert(node->dataType == OUTPUT_VIDEO && node->dataSize == sizeof(frame));
    assert(!memcmp(node + 1, frame, sizeof(frame)));
    assert(bufferingDataSize == sizeof(*node) + sizeof(frame));
    free(node);
    pthread_mutex_destroy(&bufferingMtx);
    pthread_cond_destroy(&bufferingDataConsumedCond);
    pthread_cond_destroy(&bufferingdDataAddedCond);
    thread_end();
    return 0;
}
