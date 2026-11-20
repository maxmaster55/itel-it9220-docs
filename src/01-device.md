# 1. Device and SoC

## Identity

| Property | Value |
|---|---|
| Marketing name | itel Neo X10+ 4G |
| Model code | `it9220` |
| Firmware family | `LS2404`, build string `MOCOR_MOCOR_20A_MP_W24.28.3` |
| SoC | Unisoc **UMS9117** (= T117, SC6531E class; SC9863-like low-end block layout) |
| CPU | one ARM **Cortex-A7** (ARMv7-A, MMU, VFPv3-D16 in use by stock), about 1 GHz |
| RAM | 64 MB DRAM at `0x80000000` |
| Flash | **SPI NAND**, 1024 blocks of 128 KiB = 128 MiB (2048+64 byte pages; vendor pages say "64 MB"); the one unit examined reported JEDEC id `C8 81` (GigaDevice) |
| Display | 240 x 320 TFT, **ST7789** panel on SPI1 (not RGB) |
| Radios | GSM/GPRS, LTE Cat.1, Wi-Fi 2.4 GHz + Bluetooth + FM (Marlin2 combo chip), GNSS |
| USB | Type-C, charge + data (Mentor MUSB core) |
| Audio | PMIC-internal codec (SC2720 family) with a loudspeaker PA inside the PMIC; no external amplifier GPIO |

Firmware package names encode the variant, for example
`UMS9117_LS2404_it9220_240X320BAR_64MB_<languages>_<region>.pac`: platform,
OS version, model, form factor and RAM, language set, region. Flash the
package that matches your exact variant.

Vendor marketing pages disagree with each other (some list an Android phone
with a 6.5 inch display). The firmware package is the authority: this is a
**MOCOR** feature-phone OS (see [page 7](07-mocor-stock-os.md)), not Android and not KaiOS.

There is no fastboot and no bootloader unlock on this class of device.
Flashing uses Unisoc's BSL protocol over USB ([page 3](03-flashing-and-recovery.md)).

## Memory map

| Range | What | Notes |
|---|---|---|
| `0x00000000`-`0x0000FFFF` | on-chip RAM (boot ROM loads FDL1 to `0x6200`); exception vectors at `0x0..0x3C` in stock | |
| `0x00010C00` | GSM DSP dual-port area (FrameInst/RespQ) | **Proven (hardware)** that it is at physical `0x10C00` |
| `0x0000E400`-`0x00010BFF` | LTE DSP on-chip rings (`0x10BF8` = mode word) | Read |
| `0x20000000`+ | AHB peripherals (see below) | |
| `0x40000000`+ | APB peripherals, AON, PMU, ADI | |
| `0x70000000` | UART0; `0x70100000` UART1; `0x70200000` UART2 | |
| `0x80000000`-`0x83FFFFFF` | DRAM (64 MB) | |
| `0x80020000` | CM4 firmware (loaded by stock) | `0xD4000` bytes |
| `0x80100000` | GSM DSP shared block A (`0x20000`); also where BOOT1/FDL2 run (`0x80100200` payload) | |
| `0x80120000` | GSM DSP image | `0x300000` bytes |
| `0x803A8000` | GSM DSP shared block B | voice rings |
| `0x80468000` | LTE DSP image | `0x49E000` bytes |
| `0x80E65E00` | KernelImg load address (DHTB header); code entry `0x80E66000` | stock AP kernel `0x80E66000..~0x81A92000` |
| `0x81B00000` | stock page pool (1 MB) used to demand-page UserImg | |
| `0x81C20000` | kernel initialised data (decompressed from a scatter table); BSS to about `0x826B7340` | |
| `0x88000000` | UserImg window (`0x1200000`), demand-paged from NAND partition 4 | |
| `0xC0000000`-`0xEFFFFFFF` | modem/baseband I/O windows used by stock (not ordinary peripherals) | |

Stock zeroes `0x80000000+128K` and `0x83FE0000+128K` at start-up. The modem side
(DSPs, CM4) owns low DRAM; a host that wants the whole 64 MB must first find
which areas the DSPs still write ([page 10](10-modem-under-linux.md)).

## SoC blocks

All from stock driver code unless marked.

| Block | Address | Notes |
|---|---|---|
| GIC (v2) | GICD `0x12001000`, GICC `0x12002000` | stock does not write IGROUPR; SPI number = GIC id - 32 |
| AP timer 0 | `0x40220000` (SPI 29); timer 1 `0x40220020` (SPI 118) | Linux `sprd,sc9860-timer` register layout |
| 1 kHz system counter | `0x4023000C` (SPI 31) | handy free-running ms clock |
| Generic timer | not used by stock (no CNTFRQ/CNTPCT use anywhere) | measure before trusting |
| Pin / strap | `0x40250000` | `+0x2C` holds keypad strap bits |
| Pinmux | `0x402A0000` (`+0x18` UART/JTAG select, `+0x120..`, `+0x520..`) | |
| AON/clock gates | `0x402E0000` with set/clear aliases at `+0x1000` / `+0x2000` | `0x402E1000 + r` sets bits of `0x402E0000 + r`, `0x402E2000 + r` clears them |
| AHB gates | `0x20E00000` (aliases `0x20E01000`, `0x20E02000`) | SDIO0 bit 7, SDIO1 bit 8, NANDC bit 9, MUSB bit 4, DMA bit 5 |
| ADI (PMIC bus) | `0x40600000` | see [page 4](04-peripherals.md#adi-and-the-pmic) |
| PMU / radio power | `0x402B0000`, `0x60830000`; LTE security engine `0x60810000` | |
| Mailbox | inbox (AP to others) `0x400A0000`, outbox `0x400A8000` | SPI 68 / 69 |
| AP DMA | `0x20100000` (channels `0x20101000 + n*0x40`, request routing `0x20102000`) | SPI 50; register layout of mainline `sprd-dma` |
| VBC (voice band codec) | `0x40020000` | [page 5](05-audio.md) |
| Audio codec digital | `0x40000000` | [page 5](05-audio.md) |
| LCDC | `0x20800000` | SPI 19; panel on SPI1 |
| SDIO0 (microSD) | `0x20300000` | SPI 57 |
| SDIO1 (Wi-Fi/BT/FM chip) | `0x20400000` | SPI 58 |
| MUSB (USB device) | `0x20200000` | SPI 55 |
| SPI-NAND controller | `0x21A00000` | SPI 59 |
| GPIO | `0x40280000`, 128 lines, 16 per `0x80` bank | SPI 35; layout of mainline `gpio-sprd` |
| Watchdog (AP) | `0x40310000` | stock leaves it armed; stop it early in any replacement OS |
| UART | data `+0x00`, status `+0x0C` (bit `0xFF00` = TX busy) | UART1 is the FDL1 console; clock gate `0x71300000` |

Useful interrupt lines (SPI numbers): UART1 3, SPI0 7, SPI1 8, I2C0 11, I2C1 12,
UART2 17, UART0 18, LCDC 19, AUD 20, ADI 25, AON timer 28, AP timer 29,
AP syst 31, GPIO 35, keypad 36, EIC 37, ANA 38, DMA 50, OTG 55, SDIO0 57,
SDIO1 58, NANDC 59, mailbox to AP 69, AP timers 1..4 118..121, AP watchdog 123,
CA7 watchdog 124. SIM0 is line 10 and SIM1 line 13 (**Read**). Modem timers
113/115 and `DMA_LINK` 71 matter for the modem ([page 10](10-modem-under-linux.md)).

Other drivers named in the stock kernel: I2C0/I2C1, SPI0/SPI1, PWM0-2, ADC,
RTC (32 kHz counter), camera (DCAM/ISP, five sensor drivers), GNSS (separate
modem images, no AP-side driver studied).

## Pin straps and UART/JTAG mode

BOOT0 reads strap mask/value words (`0x1034`/`0x1038` window) and prints
`boot0 UART/JTAG mode`; a strapped value of 16 means UART, 17 means JTAG
(**Read**). UART/JTAG routing is selected by bits `0x40000000`/`0x80000000`/
`0x20000000` of `0x402A0018`. Which UART is wired to an external debug
connector on this board is **Unknown**.
