# 5. Audio

Reconstructed by running the stock audio code (HAL, VBC DAI layer, codec state machine,
DMA layer) in an emulator and recording every PMIC and MMIO write in order with the
stock address that made it, then implementing the same sequence in a Linux ALSA driver.
"Proven (emulation)" below means: the write is in that trace. The emulated registers
start at zero, so the trace shows which bits stock sets and clears, **not** the values the
registers hold on a live phone. It cannot show values that come from the phone's audio
calibration data (speaker gain, speaker PA set-up byte) or anything about timing.

Status summary:

| Path | Status |
|---|---|
| Loudspeaker playback | sequence **Proven (emulation)**; Linux driver written; audible result **not confirmed in these notes** |
| Microphone capture | sequence **Proven (emulation)**; driver written; **not tried on hardware** at time of writing |
| Headphone output | sequence **Proven (emulation)**; **not run on hardware** |
| FM audio (chip to speaker) | route **Read/emulated**; chip side (tune) **Proven (hardware)**; **never listened to** |
| Call audio | stock owns the codec during a call; a foreign host must step aside (see below) |

## The path

```
PCM buffer (RAM)
  -> AP DMA 0x20100000, two channels, requests 30 and 29 (SPI 50)
  -> VBC 0x40020000: DA FIFOs at 0x40021004 (request 30) and 0x40021000 (request 29)
  -> codec digital part 0x40000000: sample rate, DAC enables, mute
  -> SC2720 codec over ADI: analog 0x40608700, CFGA 0x40608800, PMIC global 0x40608C00
  -> "lout" driver + speaker PA, both inside the PMIC
```

There is **no amplifier GPIO**: stock's PA hook goes through the product table entry id
`0x1F` (type 4, callback only) to the SC2720 PA function. Stock opens PCM playback with
flags `0xC0001000`; `0xC0008000` is a different mode (the VBC is handed over, no AP DMA).
Capture is `0x30001000`. FM play is `0xC0000080`, FM record `0x30000080`.

APB set/clear aliases: `0x402E1000 + r` sets bits of `0x402E0000 + r`, `0x402E2000 + r`
clears them. Stock addresses are build-specific (kernel dump offset 0 = `0x80E65E00`).

## Playback sequence

### VBC (dai init `0x81809AB4`, open `0x81809B18`)

| Step | Write |
|---|---|
| AP drives the VBC | `0x402E2020 = 0xC0000` |
| VBC clock | `0x402E1000 = 0x80000` |
| VBC reset | `0x402E1008 = 0x100000`, then `0x402E2008 = 0x100000` |
| interface | VBC+0x3C: clear bits 8:6 and 2:0 |
| DA on | +0xC8 OR 2, OR 1; +0x00 OR 1, OR 2; +0x38 &= ~3; +0x3C &= ~0x100000 |
| FIFO levels | +0xE4 bits 17:0 = (80 << 9) OR 160 |
| AD side | +0xC8 OR 0x20, OR 0x10; +0x80 bits 3:0 = 0; +0x3C &= ~0x40000; +0x38 &= ~0x30; +0xEC = levels |
| DA path | +0x40 bits 3:0 = 0; +0x3C bits 2:0 = 0 |
| DA FIFOs | +0x18 OR 1, OR 2 |

### AP DMA

Channel n at `0x20101000 + n*0x40`; request routing at `0x20102000 + (request-1)*4`
(value = channel + 1); masked interrupt status `0x20100014`. Clock `0x20E01000 = 0x20`.
Per transaction:

| Register | Value |
|---|---|
| +0x08 CFG | 0, then `0x3000` |
| +0x10 SRC / +0x14 DES | buffer / `0x40021004` or `0x40021000` |
| +0x18 FRG_LEN | `0x51300140`: 16-bit both sides, block request, destination fixed, 320 bytes |
| +0x1C BLK_LEN | `0x140` |
| +0x20 TRSC_LEN | bytes, a multiple of 320 (stock asserts it) |
| +0x24 TRSF_STEP | 2 |
| +0x0C | clear pending; then CFG OR `0x01000001` (run) |

At first start stock writes 10 zero pairs into the FIFOs and sets VBC+0x18 bits 8, 9
(DMA requests). Stock re-arms each channel from the transaction-done interrupt. Stop:
channel +0x00 OR 1, wait bit 2, CFG &= ~1, +0x00 &= ~1.

### Codec (open `0x812C2CBC`)

Digital rate code (AUD+0x0C bits 3:0): 48000=1, 44100=2, 32000=3, 24000=4, 22050=5,
16000=6, 12000=7, 11025=8, 9600=9, 8000=10. Analog bring-up, in order: PMIC audio module
`0x40608C08` OR `0x10`; codec reset `0x40608C14` OR `0x3100` then clear; digital clock
`0x402E1000 = 0x60000`; digital set-up (AUD+0x14 OR 8, +0x00 clear 7:6, ...); "ap_en 1"
analog enables (ANA+0x18, +0x3C, +0x7C low byte = `0x0D`, CFGA+0x38, ANA+0x00/0x20);
outputs off (ANA+0x2C all gain fields 15, ANA+0x24 clears); interface clocks
`0x40608C0C` OR 3; DAC on (AUD+0x38 = `0x9999`, +0x3C = 1, +0x00 OR 1 and OR 4,
ANA+0x18 OR `0x200`/`0x100`, ANA+0x28 OR `0x1000`, CFGA+0x30 OR 4 and `0x10`); gains in
ANA+0x2C (15:12 speaker, 11:8 earpiece, 7:4 and 3:0 headphone); mic bias off; speaker on
(ANA+0x24 OR `0x2000` then OR 1); PA (ANA+0x20 bits 2:0 = 2, ANA+0x28 OR `0x800`, ANA+0x0C
clear 9:7, PA byte into ANA+0x10/0x14, 20 ms, ANA+0x24 OR `0x2001`, 10 ms, ANA+0x28 OR
`0x40`); unmute at start (AUD+0x0C OR `0x8000`, clear `0x4000`). Close runs it backwards
and waits for the mute-done interrupt (SPI 20, up to 600 ms). Stock waits 5, 10, 20 ms at
the marked points.

### Not proven (playback)

- **Speaker gain.** ANA+0x2C bits 15:12 come from calibration data (levels 0..3 map to
  0, 5, 10, 15). Stock writes 15 to mute; for headphone/earpiece 15 is the quietest, so
  15 is probably quiet for the speaker too, but **which end is loud is a guess**.
- **PA set-up byte** (codec ioctl 8): bits 2:0 -> ANA+0x14 bits 11:9, bit 3 -> ANA+0x10 bit 7
  (then bits 7:5 -> ANA+0x10 10:8), bit 4 -> ANA+0x14 bit 14. The phone's value is **Unknown**;
  leaving the fields as the stock system set them before the hand-off worked as a default.
- Stock keeps a separate buffer per DMA channel; a simpler driver can point both channels
  at one mono buffer.
- Re-arm latency under a foreign kernel is unmeasured; the FIFO holds at least 160
  samples (7 ms at 22050 Hz) between a transaction's end and the next.
- **Playback has no call guard.** Opening playback resets the VBC and soft-resets the
  codec; closing powers the codec off. Under stock's voice path that probably kills a
  call (from reading, not traced). Keep your own sounds off the device during a call.

## Capture (microphone), flags `0x30001000`

Same VBC init/open as playback, then:

- DMA routing: request 32 -> channel 2 (`0x2010207C = 3`), request 31 -> channel 3
  (`0x20102078 = 4`); channel +0x0C interrupts `0x14`.
- ADC analog ("ap_adc 1", `0x81783230`): ANA+0x1C OR `0x8000`, `0x4000`, `0x2000` (L),
  `0x1000` (R), `0x80` (L), `0x20` (R); pulse `0x40` (L), `0x10` (R); ANA+0x18 OR `0x800`;
  CFGA+0x30 OR 8 (L), `0x20` (R). Digital: AUD+0x00 OR 2 and OR 8.
- ADC rate: AUD+0x18 bits 3:0 = round(rate / 4000) (8000 -> 2, 16000 -> 4).
- PGA gain: ANA+0x20 bits 11:9 (L), 8:6 (R) = calibration level & 7.
- Main mic: ANA+0x04 bits 2:0 = 2; ANA+0x00 clear 4 and OR `0x400` (bias); ANA+0x08
  bits 8:5 = 15; ANA+0x28 OR 8 (the aux mic uses the same bit; the headset mic bit 2).
- Capture DMA: SRC `0x40021014` (AD0; AD1 is `0x40021010`), FRG_LEN `0x51100140`
  (source fixed), TRSF_STEP `0x20000`; re-arm from the DMA-done handlers.

**Not proven:** which AD channel carries the main mic (stock enables both), the real PGA
value, and the VBC owner-bit detection of calls (APB +0x20 bits 19:18; cleared = AP).
During a call stock's audio stack owns the codec; a foreign host should refuse to open
the codec when those bits, the ADC (ANA+0x1C `0xF0A0`) or the main-mic switch are set.
Do not read a large register dump while audio is running: a full register read has frozen
the phone.

## Headphone output (route 4)

"ap_hp 1": ANA_CDC2 bits `0x10`, `0x8`, `0x4`, pulse `0x400`/`0x100`, then `0x200`, `0x80`,
`0x1000`, `0x800`; ANA_CDC3 `0x200`, `0x100`; then "hp_depop_en" pulses and the depop
start: outputs off, fast charge (ANA+0x64 bit 13, pulse ANA+0x5C bit 0, 65 ms), DC
calibration (ANA+0x4C = `0xFFFF`, +0x54 = `0x4CD8`, +0x58 = `0x2E6C`, +0x5C = `0xA820`,
ANA+0x64 = `0xE000`, wait for bits 12 and 10, 20 x 15 ms), output-capacitor charge (bit 10,
then ANA+0x64 bits 8, 7, 6, 9, wait bits 5 and 4, 30 x 20 ms). Speaker stays muted while
the headphone plays. Which end of the headphone gain is loud is a guess (15 = mute).

## FM audio

FM is a function of the Marlin2 chip ([page 6](06-wcn-marlin2.md)); its audio reaches the
speaker **digitally through the VBC**, not through the codec's line input.

- Stock FM device `ARMVB_FM` opens the audio device with `0xC0000080` (DAI table maps bit
  `0x80` to VBC path bit 2). No AP DMA is opened.
- VBC writes of that path: +0x3C bits 2:0 = 2; +0xF8 OR `0x2000`, OR `0x4000`; +0xF8 OR
  `0x10000` (the FM input on); +0xF8 bits 12:0 = 30; +0x40 OR `0x100`, bits 1:0 = 1, bits
  3:2 = 1; +0x18 OR 1, OR 2 (DA FIFOs on, **no** DMA request bits); 64 zero pairs into the
  DA FIFOs. The codec part is the same as PCM playback.
- Recording FM (`0x30000080`) sets up the VBC and AD DMA exactly like the microphone and
  opens **no** codec input: the AD FIFOs carry the radio itself, which makes a useful
  data check without ears.
- The stock FM driver sends nothing about audio to the chip (open is command 0 with
  `00 01`); the pins from chip to VBC are set once at boot.
- The headset cable is the antenna.

**Unknown:** the DAC/sample rate (48000 is a guess; wrong rate = wrong pitch), whether the
pin routing survives a foreign host, meaning of VBC +0xF8 bits 12:0 = 30. The chip-side
tune was proven on hardware; **the audio has not been heard**.
