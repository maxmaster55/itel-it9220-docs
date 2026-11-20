# 6. Wi-Fi, Bluetooth and FM (Marlin2)

The phone has a Unisoc **Marlin2** (SC2342 family, "uwe5622"-style host protocol) combo
chip: Wi-Fi 2.4 GHz (station and AP), Bluetooth (HCI 5.1 on the chip) and FM, with its own
Cortex-M4. Its firmware is the `WCNCODE` partition ("Platform Version:Marlin2_20B_W21.05.3",
project `marlin2_cm4`, 592,489 bytes used). There is no GNSS code in it.

It is an **SDIO device on SDIO1** (`0x20400000`), not a shared-memory (SIPC) core. The
`fm_sipc_thread` / `spipe` names in the stock kernel are only local naming.

Status:

| Item | Status |
|---|---|
| Power-up, SDIO attach, chip id, firmware download, start, calibration handshake | **Proven (hardware)** |
| Bluetooth HCI Reset / Read Local Version / Read BD_ADDR | **Proven (hardware)** |
| FM open, tune, mute, close | **Proven (hardware)** |
| Wi-Fi GET_INFO, OPEN (station), scan with results | **Proven (hardware)** |
| Wi-Fi connect, data path, DHCP | written from stock code, **not run** |
| Bluetooth host stack (vendor PSKEY/RF commands, HCI bridge) | **not started** |
| FM audio to the speaker | route written, **never heard** ([page 5](05-audio.md)) |
| SDIO in-band IRQ / GPIO 18 interrupt | polling used; interrupt **not proven** |

## Wiring

| Thing | Value |
|---|---|
| Host | SDIO1 `0x20400000`, SPI 58, same "R11" controller as microSD |
| Host gate / reset | `0x20E00000` bit 8 / `0x20E00004` bit 12 |
| Host clock source | `0x21500074` low 3 bits: 0 = 1 MHz, 1 = 26 MHz, 2 = 307.2, 3 = 384, 4 = 390, 5 = 409.6 MHz. Stock asks for 384 MHz and starts at 400 kHz; 26 MHz (25 MHz bus) works |
| Chip enable | GPIO 14 |
| Reset | GPIO 17 |
| Chip interrupt to AP ("pub_int") | GPIO 18 |
| AP wake to chip ("tx_req") | GPIO 13 |
| Supply | LDO `vddwcn` (id 27): on = clear bit 0 of `0x40608CAC`; voltage in low 6 bits of `0x40608CB0` (800 mV + 12.5 mV/step; stock picks level 3 = 1600 mV, clamped to 1587.5 mV). Another supply `vddwifipa` (id 34) exists |
| 32 kHz clock to chip | `0x402E0004` bit 2 (set via `0x402E1004`, clear via `0x402E2004`) |

GPIO block `0x40280000`, 128 lines, 16 per `0x80` bank, layout as mainline `gpio-sprd`
(data 0, mask 4, dir 8, IE `0x18`, IC `0x24`, INEN `0x28`). Pad pin-mux is left as the stock
boot set it; which pin registers they are was not mapped.

## Power-up sequence (stock)

1. 32 kHz clock on.
2. `vddwcn` to level 3, then on.
3. Chip enable low, 100 ms, high. Reset low, chip enable low, 100 ms, enable high, 2 ms.
   Reset low, 2 ms, reset high, 2 ms. Then 20 ms.
4. SDIO card start: CMD0, CMD8, CMD5, normal SDIO attach; function 1 on; 512-byte blocks on
   functions 0 and 1; function 0 register `0x1CA` OR 3. Linux needs a quirk allowing
   function-0 access with the 17-bit address.
5. Read chip id at chip address `0x603003FC`.
6. Download the first `0x90C00` bytes of `WCNCODE` to chip address 0, in 8 KiB chunks.
7. Hold the chip CPU (bit 0 of `0x40060288`), `0x60300150` OR `0x80000000` ("SDIO priority"),
   then release the CPU (clear bit 0 of `0x40060288`). Reset value of that register after a
   power cycle is 1 (held).
8. Calibration handshake (below), then wait up to 30 s for "cp2 is running".

## Calibration handshake

All accesses are direct transfers. Chip addresses:

1. read `0x60300004`, OR `0x20`, write back.
2. write **3908 bytes** at `0x70040010` (616 bytes of Wi-Fi config then 3292 bytes of
   calibration data). Stock sources them from NV items 409 (first 616 of 888 bytes) and 417
   (3292 bytes). Treat these as the phone's own calibration: never publish them.
3. up to 20 times read `0x70040004`, expecting `0xCCCCCCCC` ("alive"), 100 ms apart; stock
   goes on after 20 tries. On hardware the tag was set after a warm restart but **not** after
   a cold power cycle, yet calibration still completed.
4. write `0xAAAAAAAA` to `0x70040000` ("start cali").
5. function 0 `0x1C0` OR 7 (enable status bits 0..2); optionally enable GPIO 18.
6. the chip calibrates, then raises function 0 `0x1F0` bit 0 (seen within a second; polling is enough).
7. read 3292 bytes at `0x70040010` (results; stock saves them to NV 417), write `0xBBBBBBBB`
   to `0x70040000`.

## Sleep / wake handshake (function 0 registers)

| Reg | Use |
|---|---|
| `0x1C0` | REG_AP_INT_EN0: OR 7 |
| `0x1F0` | status: bit 0 calibration finished, bit 1 "cp2 ack" of a wake, bit 2 "cp2 allows sleep" |
| `0x1D0` | acknowledge (OR the seen status and write back) |
| `0x1A2` | wake: write 0, wait for status bit 1 up to 1000 ms (retry once with 1, 100 ms, 0); 1 = let it sleep |
| `0x1B0` | sleep request: OR 2 together with `0x1A2` = 1 |
| `0x184` | cp2 status; `0x1BC..0x1BF` read in error paths, meaning unknown |
| CCCR `0x05` | SDIO interrupt pending; bit 1 = function 1 has data. It only shows data **after CCCR `0x04` = 3** (master + function 1 interrupt enable) |

A host that never acknowledges "allow sleep" keeps the chip awake; that is the simplest
first-test behaviour. After a firmware assert the chip stops acknowledging wake and a
CPU hold + reload is not enough: a full chip power cycle then reload is the way back.

## SDIO transfer modes

- **Direct transfer**: 32-bit chip address into function 0 `0x15C..0x15F` (Linux has no CMD53 on
  function 0, so use four CMD52 byte writes), data through function 1 address `0x0F`,
  incrementing CMD53. Used for chip RAM/registers, the calibration block and the Bluetooth
  transmit window.
- **Packet mode**: CMD53 on function 1 address `0x20`, fixed address. A write is rounded up to a
  multiple of 512.
- **Lengths not a multiple of 512:** stock sends whole 512-byte blocks (block mode, up to 511 per
  command) then the remainder in byte mode, **both to the same SDIO address**. Linux's
  `sdio_memcpy_toio` moves the address forward for the tail, which misses the direct-transfer port
  (it times out). Do the stock split. Also Linux sends exactly 512 bytes in byte mode; an FM packet
  sent that way crashed the firmware once ("Mpufault"), so pad packet writes to 1024 bytes or send
  512 as one block.
- After a failed packet transfer stock reads `0x184`, `0x1BC..0x1BF`, writes function 0 register 6 = 1
  (abort) and runs a dummy read.

## Packet format

A 32-bit little-endian header per message, payload padded to 4 bytes:

```
bit 31..28  type     0..3 (15 = padding packet, skipped)
bit 27..24  subtype  0..3
bit 23      end marker (header word 0x00800000 = no more packets in this buffer)
bit 22..7   payload length in bytes (1..0x2800), not padded
bit 6..0    zero (low 7 bits read back as 1s; ignore)
```

**TX buffer:** one or more `[header][payload padded to 4]`, then `0x00800000`, zeros up to a
multiple of 512, one fixed-address CMD53 write to function 1 address `0x20`.

**RX read:** read N bytes (multiple of 512, start 2048) from function 1 address `0x20`. The last
8 bytes are a trailer: `u32 used_len`, `u32 next` (queued bytes still waiting, 0 = none). The next N
= `(next + 8*((next >> 10)+1) + 575) & ~511`, max `0x2800`; 2048 when `next` is 0. A buffer usually
starts with a type-15 padding packet (length 60) and the area after the last packet is `0xFF`; skip
type 15 without counting it. A header is valid when type < 4, subtype < 4, length <= `0x2800`, and the
length bits are not all zero.

| type, subtype | Used for |
|---|---|
| 0, 0 | Bluetooth: HCI events and ACL from the chip (H4 framed). BT commands go **to** the chip by direct transfer, not here |
| 0, 1..3 | log / "mdbg" and AT text (`at+loopcheck`, `at+getchipversion`, `startwcn`, `dumpmem`, ...) |
| 1, 0 | FM: commands in, events out |
| 2, 0 and 2, 1 | Wi-Fi (sprdwl); the first payload byte tells command/event/data |
| 3, x | firmware text log (`3,3` asserts such as "WCN Assert in nvic_fault.c ... Mpufault") and binary log records |

## Bluetooth

- TX: the H4 packet is **zero-padded to a multiple of 8 bytes** and written by **direct
  transfer to chip address `0x51004000`**. RX: type 0 subtype 0 packets carry raw H4 bytes.
- Hardware results: HCI Reset OK; Read Local Version reports HCI 5.1 (0x0A), revision/subversion
  `0x1380`, manufacturer 0; the chip's default BD_ADDR is a fixed placeholder until NV 401 (BD
  address + 2 bytes) is sent. NV 409 (888 bytes RF config) and 401 are sent by Marlin vendor
  commands (`HCI_MARLIN_WRITE_PSKEY`, `HCI_MARLIN_WRITE_RF`) whose opcodes are **not decoded**.
  Unsolicited vendor events (`04 FF 05 0A 00 ..`) arrive; wait for the Command Complete of your own opcode.
- A Linux HCI would be a `/dev/vhci` bridge moving H4 packets (not started).

## FM

FM commands are HCI vendor commands, opcode `0xFC8C`, on packet (1, 0):

```
TX: 01 8C FC (len+1) CMD P0 P1 ...      RX: 04 0E len ncmds 8C FC STATUS DATA...
seek-result vendor event: 04 FF len 30 00 ?? ?? FREQ_LO FREQ_HI
```

| CMD | Meaning | Payload |
|---|---|---|
| 0 | open | `00 01` |
| 18 | close | `00` |
| 2 | mute / unmute | `01` / `00` |
| 1 | tune | u16 LE frequency in 10 kHz (101.1 MHz = 10110); mute first; answer: status, RSSI, SNR, frequency |
| 4 | auto seek | u16 frequency, direction byte (`up` = 0 is a guess); result comes later as the vendor event (stock waits up to 15 s) |
| 27 | antenna | `00` long (headset cable), `01` short |
| 11 | scan level | level byte |
| 34 | register write/read | 10 bytes, `00`, u32 addr, u32 value |
| 48 | info | one byte 1..12 (RSSI, pilot, AGC, ...) |
| 23-26, 28 | noise scan, tune/audio-mode parameters, data capture | see stock `FM_OPERATION_*` |

Volume is not a chip command; it is set in the SoC audio part. Hardware: open answered `04 0E 04 01 8C FC 00`;
tune 100.6 MHz answered status 0, SNR about 11-12, frequency echoed. RSSI read the same value on every
station, so its scale is **Unknown** (use SNR). `FM_Init` reads NV item 419 (seek thresholds); whether they are
sent to the chip is not decoded and not needed for open/tune.

## Wi-Fi (sprdwl host protocol)

First payload byte of a type-2 frame: bits 2..0 type (0 command response, 1 event, 2 data); bit 3 direction;
bit 4 "has credit block"; bits 7..5 mode (station 0). Commands have a 12-byte header:

```
byte 0    (sync & 1) << 4 | (mode & 7) << 5
byte 1    command id
byte 2,3  u16 LE total length = 12 + payload
byte 4..7 u32 tick, echoed in the response
byte 8    status in the response (signed; -30 = failure)
byte 9..11 zero
```

Command ids: 1 GET_INFO, 2 SET_REGDOM, 3 OPEN, 4 CLOSE, 5 POWER_SAVE, 6 SET_PARAM, 7 SET_CHANNEL,
10 CONNECT, 11 SCAN, 12 SCHED_SCAN, 13 DISCONNECT, 14 KEY, 15 SET_PMKSA, 16 GET_STATION, 17 START_AP,
18 DEL_STATION, 19 SET_BLACKLIST, 21 TX_MGMT, 22 REGISTER_FRAME, 25 SET_IE, 26 NOTIFY_IP_ACQUIRED, 27 SET_CQM,
28 SET_ROAM_OFFLOAD, 33 NPI_MSG, 34 NPI_GET, 35 ASSERT, 36 FLUSH_SDIO, 39 MULTICAST_FILTER, 56 LLSTAT, 57 GSCAN,
58 PRE_CLOSE, 67 NOTIFY_STATCK_TYPE.

An event frame with byte 1 = `0xB3` carries transmit credits for three queues (command list of 128, two data
lists of 512); do not send data frames without credits. GET_INFO on hardware returned chip model `0x2332`, chip
version `0x01050000`, firmware version `0xA0C5`, standard `0x5F`, capabilities `0x0F7E`. The MAC comes from NV
item 416 (the host makes one up if empty) and is sent in OPEN. **The firmware does the WPA handshake itself**
(the connect command carries the passphrase key; SAE is present), so no `wpa_supplicant` is needed. OPEN and SCAN
worked: scan results arrive on the **data path**, not as an event, and a station scan listed nearby WPA2 networks
with SSID, channel and signal. CONNECT/data payload layouts follow the open uwe5622 sources and the stock driver and
are not decoded here.

## Practical notes

- A user-space daemon with a TAP device is a lean way to present `wlan0`; it avoids cfg80211's size on a 64 MB phone.
- Enabling modules in a kernel for this chip costs about +70 KB zImage and ~230 KB resident RAM; the chip
  transport (transfer code, GPIO interrupt, MMC glue) is small enough to expose as a misc device and keep protocol in user space.
- A GPIO 18 level-high interrupt on the GPIO block's shared line once stormed (100k interrupts, "nobody cared") because
  another line was pending; poll function 0 CCCR `0x05` every ~10 ms instead, or park the line for 20 ms on a spurious hit.
- First-time bring-up from a cold boot took about 12 s to FM-ready (power-up, firmware, calibration).
