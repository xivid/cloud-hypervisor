/* Plain x86_64 benchmark guest. The fixture and its fw_cfg name are fixed. */
#include <endian.h>
#include <errno.h>
#include <fcntl.h>
#include <stdint.h>
#include <stdio.h>
#include <string.h>
#include <sys/io.h>
#include <sys/mman.h>
#include <time.h>
#include <unistd.h>

enum { PAGE_BYTES = 4096, FILE_SIZE = 8 << 20, PORT = 0x510 };
static _Alignas(PAGE_BYTES) unsigned char data_page[PAGE_BYTES];
struct dma_descriptor {
    uint32_t control, length;
    uint64_t address;
};
static _Alignas(PAGE_BYTES) volatile struct dma_descriptor descriptor;
static unsigned char expected[256][PAGE_BYTES];

static int error(const char *message) {
    printf("CH_BENCH_DMA_ERROR %s (errno=%d)\n", message, errno);
    fflush(stdout);
    return 1;
}

static void pio_read(void *buf, size_t length) {
    unsigned char *bytes = buf;
    for (size_t i = 0; i < length; i++)
        bytes[i] = inb(PORT + 1);
}

static int dma_file_selector(void) {
    outw(0, PORT);
    char signature[4];
    pio_read(signature, sizeof(signature));
    if (memcmp(signature, "QEMU", 4))
        return -1;
    outw(1, PORT);
    if (!(inb(PORT + 1) & 2))
        return -1;
    outw(0x19, PORT);
    uint32_t count;
    pio_read(&count, sizeof(count));
    count = be32toh(count);
    if (count > 1024)
        return -1;
    for (uint32_t i = 0; i < count; ++i) {
        struct { uint32_t size; uint16_t select, reserved; char name[56]; } file;
        pio_read(&file, sizeof(file));
        if (be32toh(file.size) == FILE_SIZE && !strncmp(file.name, "opt/ch-bench", sizeof(file.name)))
            return be16toh(file.select);
    }
    return -1;
}

static int guest_physical(int pagemap, const volatile void *addr, uint64_t *result) {
    uint64_t entry;
    if (pread(pagemap, &entry, sizeof(entry), (uintptr_t)addr / PAGE_BYTES * sizeof(entry)) != sizeof(entry))
        return -1;
    uint64_t pfn = entry & ((UINT64_C(1) << 55) - 1);
    if (!(entry & (UINT64_C(1) << 63)) || !pfn)
        return -1;
    *result = pfn * PAGE_BYTES;
    return 0;
}

static uint64_t monotonic_ns(void) {
    struct timespec ts;
    clock_gettime(CLOCK_MONOTONIC, &ts);
    return (uint64_t)ts.tv_sec * 1000000000 + ts.tv_nsec;
}

static int fw_cfg_probe(void) {
    if (sysconf(_SC_PAGESIZE) != PAGE_BYTES || ioperm(PORT, 12, 1) < 0)
        return error("fw_cfg port unavailable");
    int selector = dma_file_selector();
    if (selector < 0)
        return error("missing expected fw_cfg DMA file or feature");
    memset(data_page, 0xaa, sizeof(data_page));
    descriptor.control = 0;
    if (mlock(data_page, PAGE_BYTES) || mlock((const void *)&descriptor, sizeof(descriptor)))
        return error("mlock");
    int pagemap = open("/proc/self/pagemap", O_RDONLY);
    uint64_t descriptor_gpa, data_gpa;
    if (pagemap < 0 || guest_physical(pagemap, &descriptor, &descriptor_gpa) ||
        guest_physical(pagemap, data_page, &data_gpa))
        return error("guest pagemap unavailable");
    close(pagemap);
    for (unsigned p = 0; p < 256; ++p)
        for (unsigned i = 4; i < PAGE_BYTES; ++i)
            expected[p][i] = (unsigned char)(i + p);
    descriptor.length = htobe32(PAGE_BYTES);
    descriptor.address = htobe64(data_gpa);
    /* x86 fw_cfg DMA commands complete synchronously with the doorbell. */
    uint64_t start = monotonic_ns();
    for (uint32_t p = 0; p < FILE_SIZE / PAGE_BYTES; ++p) {
        descriptor.control = htobe32(p ? 2u : ((uint32_t)selector << 16) | 8u | 2u);
        __sync_synchronize();
        outl(htobe32((uint32_t)(descriptor_gpa >> 32)), PORT + 4);
        outl(htobe32((uint32_t)descriptor_gpa), PORT + 8);
        __sync_synchronize();
        if (descriptor.control != 0)
            return error("DMA completion error");
        unsigned char *bytes = expected[p & 255];
        memcpy(bytes, &p, sizeof(p));
        if (memcmp(data_page, bytes, PAGE_BYTES))
            return error("DMA data mismatch");
    }
    uint64_t elapsed = monotonic_ns() - start;
    printf("CH_BENCH_DMA_READY bytes=%u descriptors=%u ns=%llu\n",
           FILE_SIZE, FILE_SIZE / PAGE_BYTES, (unsigned long long)elapsed);
    fflush(stdout);
    return 0;
}
