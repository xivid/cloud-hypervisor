use std::fs::File;
use std::time::Instant;
use devices::legacy::fw_cfg::FwCfg;
use vm_allocator::GuestMemory;
use vm_device::BusDevice;
use vm_memory::{Bytes, GuestAddress, GuestMemoryAtomic};

fn thread_cpu_ms() -> f64 {
    let mut t = libc::timespec { tv_sec: 0, tv_nsec: 0 };
    // SAFETY: clock_gettime initializes the supplied timespec.
    assert_eq!(unsafe { libc::clock_gettime(libc::CLOCK_THREAD_CPUTIME_ID, &mut t) }, 0);
    t.tv_sec as f64 * 1000.0 + t.tv_nsec as f64 / 1e6
}

fn main() {
    let path = std::env::args().nth(1).unwrap();
    let payload = std::fs::read(&path).unwrap();
    let file = File::open(&path).unwrap();
    let mem = GuestMemory::from_ranges(&[(GuestAddress(0), 8192)]).unwrap();
    let mut fw = FwCfg::new(GuestMemoryAtomic::new(mem.clone()), None);
    fw.add_initramfs_data(&file).unwrap();
    let mut buf = [0; 4096];
    let mut desc = [0u8; 16];
    desc[..4].copy_from_slice(&2u32.to_be_bytes());
    desc[8..].copy_from_slice(&4096u64.to_be_bytes());
    for _ in 0..2 {
        fw.write(0, 0, &0x12u16.to_le_bytes());
        let cpu = thread_cpu_ms();
        let began = Instant::now();
        for page in payload.chunks(4096) {
            desc[4..8].copy_from_slice(&(page.len() as u32).to_be_bytes());
            mem.write_slice(&desc, GuestAddress(0)).unwrap();
            fw.write(0, 4, &[0;4]);
            fw.write(0, 8, &[0;4]);
            assert_eq!(mem.read_obj::<u32>(GuestAddress(0)).unwrap(), 0);
            mem.read_slice(&mut buf[..page.len()], GuestAddress(4096)).unwrap();
            assert_eq!(&buf[..page.len()], page);
        }
        println!("{:.3},{:.3}", began.elapsed().as_secs_f64()*1e3, thread_cpu_ms()-cpu);
    }
}
