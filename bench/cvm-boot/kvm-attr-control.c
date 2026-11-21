/* KVM control: already-SHARED pages in an ordinary VM; no SNP launch or guest execution. */
#define _GNU_SOURCE
#include <errno.h>
#include <fcntl.h>
#include <inttypes.h>
#include <linux/kvm.h>
#include <stdint.h>
#include <stdio.h>
#include <stdlib.h>
#include <string.h>
#include <sys/ioctl.h>
#include <sys/mman.h>
#include <time.h>
#include <unistd.h>

#ifndef KVM_SET_MEMORY_ATTRIBUTES
struct kvm_memory_attributes {
    uint64_t address, size, attributes, flags;
};
#define KVM_SET_MEMORY_ATTRIBUTES _IOW(KVMIO, 0xd2, struct kvm_memory_attributes)
#endif

static int unavailable(const char *operation) {
    fprintf(stderr, "SKIP: %s: %s\n", operation, strerror(errno));
    return 77;
}

static uint64_t now(void) {
    struct timespec t;
    if (clock_gettime(CLOCK_MONOTONIC_RAW, &t)) exit(1);
    return (uint64_t)t.tv_sec * 1000000000 + t.tv_nsec;
}

int main(void) {
    const int pages = 140, repetitions = 128;
    const uint64_t slot_bytes = UINT64_C(8) << 30;
    int kvm = open("/dev/kvm", O_RDWR | O_CLOEXEC);
    if (kvm < 0) return unavailable("open /dev/kvm");
    if (ioctl(kvm, KVM_GET_API_VERSION, 0) != KVM_API_VERSION) {
        fputs("SKIP: incompatible KVM API\n", stderr);
        return 77;
    }
    int vm = ioctl(kvm, KVM_CREATE_VM, 0);
    if (vm < 0) return unavailable("create regular VM");
    void *memory = mmap(NULL, slot_bytes, PROT_READ | PROT_WRITE,
                        MAP_ANONYMOUS | MAP_PRIVATE | MAP_NORESERVE, -1, 0);
    if (memory == MAP_FAILED) return unavailable("map 8 GiB anonymous VA");
    struct kvm_userspace_memory_region region = {
        .slot = 0, .guest_phys_addr = 0, .userspace_addr = (uintptr_t)memory,
        .memory_size = slot_bytes,
    };
    if (ioctl(vm, KVM_SET_USER_MEMORY_REGION, &region)) return unavailable("register 8 GiB slot");
    struct kvm_memory_attributes attrs = {.size = 4096, .attributes = 0, .flags = 0};
    if (ioctl(vm, KVM_SET_MEMORY_ATTRIBUTES, &attrs)) return unavailable("set SHARED memory attributes");
    puts("pair,position,variant,pages,repetitions,ns_per_import_batch");
    for (int pair = 0; pair <= 30; pair++) {
        for (int position = 0; position < 2; position++) {
            int issue = ((pair + position) % 2 == 0);
            uint64_t start = now();
            for (int r = 0; r < repetitions; r++) {
                for (int page = 0; page < pages; page++) {
                    attrs.address = (uint64_t)page * 4096;
                    if (issue && ioctl(vm, KVM_SET_MEMORY_ATTRIBUTES, &attrs)) {
                        perror("KVM_SET_MEMORY_ATTRIBUTES failed during benchmark");
                        return 1;
                    }
                    __asm__ volatile ("" : : "m"(attrs) : "memory");
                }
            }
            printf("%d,%d,%s,%d,%d,%.3f\n", pair, position + 1, issue ? "set_shared" : "omit",
                   pages, repetitions, (double)(now() - start) / repetitions);
        }
    }
    close(vm);
    close(kvm);
    munmap(memory, slot_bytes);
    return 0;
}
