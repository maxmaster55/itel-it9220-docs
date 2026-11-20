# 3. Download mode, flashing, recovery

## Protocol overview

There is no fastboot. Unisoc feature phones use **BSL (Boot Serial Loader)** over USB:

```
1. phone in download mode             -> USB 1782:4d00 enumerates
2. host -> phone: BSL connect handshake (0x7E check-baud; reply "SPRD3")
3. host uploads FDL1 into RAM         (base 0x6200)
4. FDL1 runs, initialises DDR
5. host uploads FDL2 into RAM         (base 0x80100000)
6. FDL2 talks to the NAND controller and writes partitions by type code
7. NV (IMEI + RF calibration) is read before and written back after
```

Recovery works with a dead OS because the loaders are uploaded to RAM from the
host. The download-mode paths are the safety net; see below for which ones are
verified.

## USB identifiers

| ID | Meaning |
|---|---|
| `1782:4d00`, no product string | download mode (boot ROM, **or** the stock kernel's listener, **or** BOOT1 auto-download) |
| `1782:4d00` bcdDevice `0x0001` | the **stock kernel's hold-key listener** (not the boot ROM) |
| `1782:4d00` bcdDevice `0x0202` | **BOOT1 auto-download**; stays on the bus and answers `SPRD3` |
| `1782:4d01` "Generic Disk1.0" | stock OS booted, USB mass-storage mode (wrong key) |
| `1782:000c` "Unisoc Phone" | stock OS booted, PC-suite mode |
| `1782:5d00` | FDL2 running |
| `1782:1d00` | boot ROM (BROM) |

Udev rule for non-root use:

```sh
SUBSYSTEMS=="usb", ATTR{idVendor}=="1782", MODE="0666"
```

## Entering download mode

**Proven (hardware):** hold `*` while plugging in USB with the phone off. This does
**not** reach the boot ROM. It reaches the stock kernel's *listener*
(`run_mode.c` in KernelImg):

1. Hold `*` and plug in. The phone shows `1782:4d00`, bcdDevice `0x0001`.
   The listener ignores the BSL `0x7E` check-baud, sends ten `7E` bytes after
   2-15 s, then boots on.
2. Send it the diagnostic "run mode" frame `7E 00 00 00 00 08 00 FE 82 7E`
   (type `0xFE`, mode `0x82`). It sets reset mode `0x17` in ADI register
   `0x40608E24` bits [8:4] and lets the watchdog reset the chip.
3. BOOT1 sees mode `0x17`, prints `boot1 enter auto download`, and returns as
   `1782:4d00` bcdDevice `0x0202`. This one answers `SPRD3` and stays. Now upload
   the stock FDL1 (`0x6200`) and FDL2 (`0x80100000`) and flash as usual.

Notes on the listener (**Read**, consistent with behaviour):

- Two listeners run in system init, *before* the UserImg window is mapped and before
  the scheduler starts. Listener 1 polls a byte FIFO for 500 ms for a 10-byte
  frame; listener 2 brings up USB and reads bytes for up to 15 s (5 s once the
  cable is removed), echoes them, and parses the frame.
- It only runs when the boot mode is 0 or 3 and ADI `0x40608E14` bits [7:5]
  indicate a PC cable. Boot mode 2 (power key held) skips it. **Do not hold the
  red End key**: on this phone it is the power key; the phone then boots the normal OS.
- Use a PC port, not a charger or a hub with charger detection.
- If the phone remembers "Connect to PC" USB mode it may stay silent: set USB to
  charge-only before powering off. If it never enumerates, pull the battery
  (removable) for 20-30 s.

**Other entry paths, not verified on this phone:**

- *Boot ROM key.* On SC6531E/T117 the ROM's download key is the key at keymap
  row 0, column 0. On this phone that code is `0x08`, the left soft key (LSOFT).
  Holding LSOFT while plugging in *should* give the ROM's own download mode.
  Untried.
- *Boot cable.* A micro-USB/OTG adapter with ID (pin 4) shorted to GND, plus an
  AM-to-AM cable (documented for the platform by the `spreadtrum_flash` project).
  On USB-C it needs an adapter that exposes ID. Untried.
- How the ROM reacts when BOOT0 returns 0 is **Unknown**.

## Tools

| Tool | Notes |
|---|---|
| Unisoc ResearchDownload / UpgradeDownload (Windows) | official; implements NV backup/restore; best for a first known-good flash |
| `spd_dump` (from `ilyakurdyukov/spreadtrum_flash`) | C; used for all the Linux work here (`write_data`, `read_flash`) |
| `emtee40/spreadtrum_flash`, `luxferre/uniflash` | alternatives; uniflash ships `ums9117_generic` FDL blobs whose bases match |
| `uflash`, `spd-tool-bun` | PAC flashing and dumps; both list UMS9117 |

## Safety rules

- **Never write BOOT0, BOOT1 or KernelImg.** The hold-key listener lives in
  KernelImg; BOOT1 hangs (not download) if KernelImg is bad. Losing them leaves
  only the unverified ROM paths.
- **Never use `erase_flash`** with an id whose bit 31 is clear (for example `0`): it
  loops over every NAND block and reformats. Ids `0x80000001`/`0x80000002` take raw-block paths.
- Flash the exact `.pac` for your variant. **Never flash a UserImg from a different
  build onto your kernel**: kernel and UserImg are one linked program ([page 7](07-mocor-stock-os.md)).
- Back up NV, and ideally the whole flash, before writing anything.
- Do not interrupt a write: NAND writes are not transactional.

## Backups

Read the NV partition and every partition you will touch. Sanity-check the NV
copy (it should contain your IMEI as readable text; note both IMEIs with `*#06#`).
A full flash readback lets you diff a modified image against the original later.
Keep dumps private: they identify the unit.

## Why a UserImg-only flash is recoverable (analysis)

Static analysis of a phone's own images, plus an end-to-end test (below).
Confidence high for boot order, medium-high overall.

- The hold-key listener is in KernelImg and runs in the kernel's single-threaded
  start-up, **before** the UserImg window is created and before any task starts.
  A UserImg that crashes at entry, has a bad DHTB header, or is fully erased
  cannot stop it. Every watchdog reboot passes through the listener again, and
  with USB connected the boot mode is 3 so its window opens each cycle.
- BOOT0/BOOT1 never read UserImg. BOOT1's auto-download runs before BOOT1 reads any
  partition.
- UserImg is demand-paged; nothing validates it (no header, hash or signature
  check in BOOT1, the kernel or FDL2). FDL2 START_DATA checks only that the id has
  bit 31 set and that the size fits the partition (error 6 otherwise).
- In calibration-style reset modes (1, 3, 5, 14) init creates a different task
  set (`T_CM`, `T_DIAG`, `T_AUDIO`) and no `T_P_APP`: a possible further fallback,
  **not worked out**.

### Restore procedure

Stock FDL2 registers handlers 1, 2, 3, 5, 6, 7, 10, 11, 23, 41. It has **no `0x2D`
partition-list command and no name-based commands**, so `write_part`,
`partition_list` and `erase_part` do not work; use the id-based `write_data`:

```sh
# 1. get into BOOT1 auto-download (bcd 0x0202): hold *, send the run-mode frame
#    (a small script that waits for 1782:4d00 and writes the 10-byte frame)
# 2. stock FDL1/FDL2 into RAM, write UserImg by id, read back, reboot
spd_dump --wait 30 --verbose 1 \
    keep_charge 1 fdl fdl1.bin 0x6200 \
    blk_size 0x1000 fdl fdl2.bin 0x80100000 \
    timeout 30000 \
    write_data 0x80000004 0 0 userimg.bin \
    timeout 1000 \
    read_flash 0x80000004 0 0x1180000 userimg-verify.bin \
    reset
# 3. compare the checksum of userimg-verify.bin with your backup
```

- START_DATA erases the partition itself (every erase unit) and streams 128 KiB FTL
  writes; no separate erase step. The file may be smaller than the partition, never
  larger (`0x1180000`). Writing the full-size backup makes the partition byte-exact.
- The FDL2 frame limit is `0x4000` bytes, so `blk_size 0x1000` is safe.
- `timeout 30000` covers the whole-partition erase.
- If a write stops part-way, the partition is partly erased; KernelImg and the
  listener are untouched, so simply repeat.
- No secure-boot path is involved: the ROM answers `SPRD3` and `fw_addr` is unset for
  UMS9117, so spd_dump's secure check does not trigger.

**Proven (hardware):** reading the UserImg partition back over USB matches a second
read (MATCH); writing a patched UserImg (a pass-through that only added a few
branches and an appended page) took about a minute, read back VERIFIED, and the
phone booted it. This proves the write path, the paging and the writer end to end.
The restore of an *unmodified* backup was written down but never run as such; the same command was used with the patched image.

### Open risks

1. The ROM download path (LSOFT or boot cable) is unverified; it is the last
   resort if KernelImg were damaged.
2. FDL2 init formats the whole FTL if `SCI_FTL_Load` returns 3, and runs an NV
   backup/update. Both ran harmlessly many times, but are outside your control.
3. Read your backup twice and compare before the first write.
4. A UserImg that breaks the kernel's fixed entry points crashes every boot. That
   is recoverable as above; if the phone hangs, pull the battery (works from an
   assert screen), then plug in holding `*`.
5. The role of `*` in the listener gate is not visible in the code read; it works in practice.

## Linux-side access to NAND (OTA)

An OS running on the phone can read, and with care rewrite, its own UserImg without USB
download mode. **Proven (hardware):** read and verify of the whole partition through
the SPI-NAND controller left initialised by the stock kernel (no controller re-init
needed); and, with a build that compiles the program/erase path in and a runtime gate,
rewriting single blocks (a padding block, then a payload block) with the stock BCH
parity: erase ok, 64 pages programmed, ECC read matches, raw read matches the model,
`PASS`.

Design points worth copying:

1. The probe touches nothing; hardware is first touched on the first open of the device.
2. No `write(2)`; open requires `CAP_SYS_RAWIO` and refuses a writable fd.
3. Program/erase code exists only when compiled in on purpose, and is gated at run time
   by a module parameter (default off) plus checks: chip id in the stock table,
   `VBM_BOOT` says the partition is id 4, blocks `0x160..0x1EB`, attr `0x100`,
   version 258, 43 boot blocks, no bad-block replacement inside the range.
4. A range lock at the lowest level: program and erase refuse every block outside
   `0x160..0x1EB`, so BOOT0/BOOT1/KernelImg/NV/DSP/FS cannot be written through the driver.
5. Every programmed page is read back with ECC and compared; the writer rewrites
   only the blocks that differ and verifies the whole partition at the end.
6. The driver's register sequences were checked write-for-write against FDL2 run
   in an emulator.

Risk that remains: a crash or power loss mid-write leaves UserImg half old, half
new; recovery is the USB path above.

## Stock-OS-to-custom-OS hand-off (technique)

A custom OS can be started from a patched UserImg without touching BOOT0/BOOT1/KernelImg:
the stock kernel boots, sets up DRAM, clocks, power and the panel, and runs the patched
UserImg. A hook in the first UI update:

1. waits for the app pool to have room, marks the attempt once per boot;
2. copies the embedded image to one heap block and a small position-independent
   hand-off routine to another;
3. verifies both blocks are identity mapped (CPU address translation `ATS1CPR`);
   if any check fails it returns to stock, which boots normally;
4. the hand-off masks interrupts, cleans and invalidates caches by set/way, turns off
   MMU, caches, branch prediction, TRE and AFE, invalidates I-cache/BP/TLB, sets
   `TTBCR = 0`, copies the image to its link address (the work used `0x81000000`)
   and jumps to `+0x200` in ARM state.

Caveats learned: the stock kernel's code area (`0x80E66000..~0x81A92000`) is free after
the hand-off, but the modem side keeps running and uses DRAM below it (an early attempt
that copied to `0x80100000` froze the phone); and nothing stock runs afterwards,
so a hand-off image has no calls, SMS or radio unless it brings the modem up itself
([page 10](10-modem-under-linux.md)).
