# 2. Boot chain and partitions

## Boot chain

```
SoC boot ROM (immutable, in silicon)
  -> FDL1       first-stage loader, NAND partition type 0x6200 (download mode only)
  -> FDL2       second-stage loader (download mode only; does the NAND writes)
  -> BOOT0      NAND blocks 0-1, read raw by the ROM
       -> BOOT1 NAND blocks 2-3, loaded to 0x80100000
            -> (TF_LOAD in one reset mode only)
            -> KernelImg  (partition 3): the MOCOR kernel, ThreadX
                 -> UserImg (partition 4): demand-paged, runs as task T_P_APP
```

- **BOOT0** (payload base `0x6400`): no key check. Reads the NAND id, reads BOOT1
  raw from NAND block 2 onwards to `0x80100000`, checks only ECC, jumps. Returns to the
  ROM on any failure.
- **BOOT1** (payload base `0x80100200`): reads ADI `0x40608E24` bits [8:4]
  (the "reset mode"). If it is `0x17` (23) it prints `boot1 enter auto download`,
  brings up USB and answers the BSL handshake with `SPRD3`. Otherwise it opens
  FTL partition 3, reads the first sector to `0x80145D70`, checks only
  `magic == "DHTB"` and `version == 1`, copies `size@+0x30 + 511` bytes to
  `0x80E65E00` and jumps to `0x80E66000`. **No hash, CRC or signature check**
  anywhere: the DHTB header's hash/sign fields are zero. There is **no keypad
  check in BOOT1**. On any load failure it hangs in `while(1)`; it does not fall
  back to download.
- **KernelImg** sets up DRAM state, clocks, power and the panel, starts
  ThreadX, and installs the *hold-key listener* ([page 3](03-flashing-and-recovery.md)).
- **UserImg** is not loaded: the kernel maps a 0x1200000-byte window at
  `0x88000000` and demand-pages it from NAND partition 4 on fault
  (4 KiB at a time, three retries, then assert `mmu_vm.c:361`).
  Nothing validates its content.

## The DHTB container

`KernelImg` and `UserImg` are wrapped in a 256-byte header:

```
0x000  "DHTB"      magic
0x004  u32 = 1     version
0x030  u32         payload length
0x100  ...         payload
```

`MMIRes` instead begins with the magic `sres0001` (SmartUI resource container).

## Partition map (`UMS9117.xml` inside the PAC)

`Base` values are Unisoc **partition-type codes**, not addresses.

| File-ID | Type | Base | Notes |
|---|---|---|---|
| FDL / FDL2 | FDL / NAND_FDL | `0x6200` / `0x80100000` | download-mode loaders (22 KB / 71 KB) |
| NV | NV_NAND | `0x90000001`, `0x9000000C` | **IMEI + RF calibration**, 707 KB |
| BOOT0 / BOOT1 | BOOT_LOADER | `0x80000001` / `0x80000002` | 26 KB / 58 KB |
| TF_LOAD | CODE | `0x90000024` | TrustZone firmware, only loaded in reset mode 26 |
| **KernelImg** | CODE | `0x80000003` | 12.2 MB RTOS kernel |
| **UserImg** | CODE | `0x80000004` | 12.9 MB phone application (MMI) |
| MMIRes | CODE | `0x90000004` | 3.2 MB UI resources |
| GSMDSPCODE | CODE | `0x90000006` | CEVA TeakLite-4 image, 2.5 MB |
| LTEDSPCODE | CODE | `0x90000005` | 3.0 MB |
| CM4CODE / CM4CODE_AB | CODE | `0x90000013` / `0x90000018` | Cortex-M4 firmware (modem side), 54 KB |
| WCNCODE | CODE | `0x90000014` | Marlin2 Cortex-M4 firmware, 579 KB |
| GPS_GL / GPS_BD / GPS_FDL | CODE | `0x9000001E` / `1F` / `21` | GNSS modem images and loader |
| DeltaNV | CODE | `0x90000019` | 84 bytes |
| APN, OmadmFota, Preload_*, RomDisk | CODE | various | auxiliary |

The package also contains `UMS9117.xml` (partition map), plus the `NV` blob.
`CheckFlag`: 0 present, 1 must be selected, 2 optional.

The vendor tool's `BMFileType.ini` confirms the platform: `[UMS9117] CODE=0xb000`,
`NAND_FDL=0x2200`, matching the `nFileFlag` values in the PAC file table.

## NAND layout (SPI NAND, 128 KiB blocks)

From the FDL2 partition table (**Read**, and confirmed by readback of the UserImg range
on hardware):

| Partition | id | Blocks (first..last, or first + count) |
|---|---|---|
| BOOT0 / BOOT1 | 1 / 2 | 0-1 / 2-3 |
| NV | `0x10000001` | 4-11 |
| gsmdsp | `0x10000006` | `0x15` + `0x19` |
| ltedsp | `0x10000005` | `0x2E` + `0x3E` |
| KernelImg | 3 | `0xF0` + `0x70` |
| **UserImg** | **4, attr `0x100` (raw)** | **`0x160`..`0x1EB` (140 blocks, `0x1180000` bytes)** |
| MMIRes | `0x10000004` | `0x1EC` + `0xC0` |
| file system | 8 | `0x2EE`.. |

A block map record `VBM_BOOT` lives in one page of one of the top 43 blocks:
`"VBM_BOOT"`, u32 version 258 at +8, u16 boot-block count 43 at +12, map blocks at
+18/+20, part count at +22, then 10-byte entries from +24 (u32 id, u16 attr,
u16 start, u16 end). Bad blocks are recorded in `"_MAP"` pages in two map blocks
(u32 258, u16 sequence number, u16 count, pairs bad -> replacement; newest page
wins). A raw partition reads physical `start + n` through that map. **Inferred**:
whether `end` is inclusive (the readback agrees with `0x1EB`).

Observed UserImg facts: the partition is `0x1180000` (18,350,080) bytes; the
stock payload is smaller and padded with `0xFF`; FDL2 erases the whole partition
before a download and pads with `0xFF` pages, so every page of the partition is
programmed.

### NAND controller and ECC

SPI-NAND controller at `0x21A00000`, AHB clock gate bit 9 of `0x20E00000`.

| Register | Use |
|---|---|
| `0x000` | START: ECC code (`0x2000` = 12-bit BCH) OR 1 = go; 2 = abort |
| `0x004` / `0x008` / `0x00C` | per-operation configuration |
| `0x010` | bit 24 done, bit 27 error; OR `0xF00` clears |
| `0x0F8`, `0x190` | mode (`2` / `0x3A`), chip select (bit 30) |
| `0x19C`/`0x19D` | bytes read by micro-op `0x1000` (id, feature value) |
| `0x200..0x214` | DMA: main, spare, ECC status |
| `0x220..` | micro-program: 16-bit ops, two per word, at most 32 |

Micro-ops: `0x00xx` send byte, `0x1000` receive byte, `0xE000` end of SPI
transaction, `0xE001` repeat until ready, `0xE201` same after program, `0x6000`
dummy, `0x3200`/`0x5200` read main/spare x4, `0x2200`/`0x4200` write main/spare x4,
`0xF000` done. Wait by polling `0x010` (up to 5 s).

FDL2 carries a 14-entry SPI chip table keyed by manufacturer/device id
(`c8c1 c821 c841 c881 c8f4 efba e521 ba21 c290 c811 a1a5 a1c1 cd61 cd60`), all
with the same geometry: page 2048+64 as 2 x (1024+32), 64 pages per block, 12-bit
BCH, 43 reserved top blocks, refresh at 4 corrected bits.

**ECC format (recovered from a raw readback, verified on hardware):** one BCH
code word per 1024-byte sector; BCH over GF(2^14) with field polynomial
`0x6111` (x^14+x^13+x^8+x^4+1), t = 12, generator g = lcm(m1..m24) (168 bits).
Message = the sector bytes from last to first, each MSB first; parity =
message * x^168 mod g, 21 bytes MSB first at spare bytes 4..24. No scrambler or
mask. Spare layout per 32-byte sector: `[0]` bad-block marker, `[1..2]` software
ECC of the info bytes, `[3]` info, `[4..24]` BCH parity, `[25..31]` info. For a raw
partition such as UserImg the spare handed to the controller is `ff d4 40 ff ff..`
per sector. A model of this ECC reproduced all 256 sectors of a raw dump byte for
byte, and matched the stored spare of every block of the UserImg range on a
phone (**Proven, hardware**).

## NV items that must survive a flash

`UMS9117.xml` marks these as backed up and restored around a download:

- IMEI (both slots)
- `Calibration`
- `LTE_gain_table`, `LTE_gain_table_flag`
- `LTE_Calibration` and `LTE_Cali_Band1..10`

`EraseUserNV` / `EraseRunNV` are explicit erase operations. If a tool does not
implement NV backup/restore, back up the NV partition yourself first, and write the
IMEI back with the vendor's WriteIMEI tool if it is lost.

## Firmware package contents (stock `.pac`)

| File | Size | What |
|---|---:|---|
| fdl1.bin / fdl2.bin | 22 KB / 71 KB | loaders |
| nvitem.bin | 707 KB | NV and calibration |
| boot0.bin / boot1.bin | 26 KB / 58 KB | |
| tfboot.bin | 159 KB | TrustZone |
| EXEC_KERNEL_IMAGE.bin | 12.2 MB | KernelImg |
| EXEC_USER_IMAGE.bin | 12.9 MB | UserImg |
| mmi_res_240x320_mini_SmartUI.bin | 3.2 MB | resources |
| NEMOL_DM_DSP.bin | 2.5 MB | GSM DSP |
| Nemol_mem_cut_LTEA_DSP.bin | 3.0 MB | LTE DSP |
| EXEC_KERNEL_IMAGE.bin (WCNCODE) | 579 KB | Wi-Fi/BT/FM firmware (same file name as KernelImg; tools must prefix the File-ID) |
| PM_nemol_cm4.bin | 54 KB | CM4 |
| gnssmodem.bin, gnssfdl.bin | 587 KB, 2.6 KB | GNSS |

See [unisoc-pac-tools](https://github.com/maxmaster55/unisoc-pac-tools) for extracting a PAC.
