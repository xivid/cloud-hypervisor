/* Local syscall-cost sensitivity check. FIONREAD does not emulate KVM internals. */
#include <stdint.h>
#include <stdio.h>
#include <stdlib.h>
#include <sys/ioctl.h>
#include <time.h>
#include <unistd.h>

static uint64_t now(void) {
    struct timespec t;
    if (clock_gettime(CLOCK_MONOTONIC_RAW, &t)) exit(1);
    return (uint64_t)t.tv_sec * 1000000000 + t.tv_nsec;
}

int main(void) {
    int fd[2], available = 0;
    if (pipe(fd) != 0) return 1;
    const int pages = 140, repetitions = 256;
    puts("pair,position,variant,pages,repetitions,ns_per_import_batch");
    for (int pair = 0; pair <= 30; pair++) {
        for (int pos = 0; pos < 2; pos++) {
            int do_ioctl = ((pair + pos) % 2 == 0);
            uint64_t start = now();
            for (int r = 0; r < repetitions; r++) {
                for (int i = 0; i < pages; i++) {
                    if (do_ioctl && ioctl(fd[0], FIONREAD, &available)) return 2;
                    /* Preserve a loop when the proxy call is absent. */
                    __asm__ volatile ("" : : "r"(available) : "memory");
                }
            }
            uint64_t delta = now() - start;
            printf("%d,%d,%s,%d,%d,%.3f\n", pair, pos + 1, do_ioctl ? "ioctl" : "empty",
                   pages, repetitions, (double)delta / repetitions);
        }
    }
    return 0;
}
