# 9. LTE findings

LTE (Cat.1) is run by a second DSP (`LTEDSPCODE`, branch `0x117a`, svn `0xddaf`) and a Cortex-M4 (`CM4CODE`), with the LTE
protocol stack (NAS, RRC, MAC) in the stock AP kernel. This page records what is known about powering it up and attaching
under a foreign host (the experiment of [page 10](10-modem-under-linux.md)). Status first.

| Item | Status |
|---|---|
| Release the LTE DSP and see it answer VERSION | **Proven (hardware)**, but **only after a real PMIC power-off** (see below) |
| Camp on an LTE cell, RACH, RRC connection | **Proven (hardware)** |
| NAS authentication, security mode, RRC reconfiguration, ATTACH ACCEPT / ATTACH COMPLETE | **Proven (hardware)** once, after a DMA fix |
| `+CEREG` registered and a PDN activated | observed once (`+CEREG: 2,1`, `NW PDN ACT 1`) |
| **User-plane data over LTE** | **not achieved**: no data passed |
| Sustained operation | **not achieved**: real-time stalls end every run |

## Memory the LTE side expects (stock addresses, must stay intact)

`0x80467E00..0x80467FFF` (shared words: ARM writes, DSP reads), LTE image `0x80468000..0x80906000`, calibration `0x806B0000..`,
uplink data `0x80926000..0x80A56000`, `0x80D17500` (256 B), and the DSP-visible on-chip RAM `0xE400..0x10BFF` (rings; `0x10BF8` = mode).
PMU `0xC0` fields (5 bits each): bits 14:10 LTE DSP domain, bits 29:25 LTE_P1; `0xC0` is read-only status. The DSP powers LTE_P1
itself by writing PMU `0x28`. LTE DSP response ring at `0xE478`: u16 in-index, then 12 slots of 8 bytes (u16 type, u16 code,
u32 pointer). The DSP writes `0xAAAAAAAA` (deactivation handshake `0x11111111` -> `0xAAAAAAAA`) / `0x55555555` into the
shared word `0x80467E14` (the address `0x40233F0A` in DSP words appears next to the constant in the image); a VERSION response (id 5)
on **mailbox core 3** through AP-target line 69 is the cold-start success signal.

## Bring-up facts

- Release sequence: hold reset, reload the LTE image (a clean reload of `0x49E000` bytes to `0x80468000` each time), chip id,
  `0x81064F90(1)` (domain power), 100 ms, `0x815B90D8(1)`, vector `0x40234200`, boot enable, release. Chip-id globals must be set first
  (`0x80EAB256` sets `0x81C222B0 = 0x98180001` etc.).
- Stock never releases the LTE DSP before the Linux hand-off (AON `0x130 = 0x10000`, vector `0x18000000` reset default, PMU `0x34`
  auto-shutdown), so a host must do the whole release itself. The hand-off register set equals Linux's apart from radio power-on.
- LTE NV: items 34/21/26/27/28 (calibration) present; `NV_LTE_MODE_CFG` (type 55) missing on this unit.
- `AT^SYSCONFIG` is a facade in this build (it always answers `17,5,1,2`). `AT+SPTESTMODEM=<m>,254` changes the per-SIM RAT:
  mode 10 selects GSM only (RAT 0), 21 removes WCDMA (LTE+GSM). Modes 11/12/18/19/64 -> RAT 1; 255/20 -> RAT 2; 1..3 and 0 -> RAT 16; 4..9 -> RAT 19.
  `plm_lte_is_to_be_powerup` answers false when the preferred RAT is below 16, which is why GSM-only mode skips the LTE wait.

## The DSP "never comes back" trap

After some failed runs the LTE DSP stayed silent through warm reboots and download-mode reflashes. **State that survives
those, and only a real PMIC power-off clears**: `sync; poweroff -f` (PMIC power-down bit; the phone powers itself back on if USB
power is present) restored a working release. DRAM outside the reloaded image also keeps state across warm reboots; zeroing
`0x80906000..0x80B00000` froze the phone. A bus error into the modem block `0xE0010002` (a misaligned read from stock's NVM idle task
through a garbage pointer, 390+ times per LTE run) was shown to be an alignment fault, not a wedged bus.

## Attach under a foreign host

Sequence observed: LTE DSP up, `LTEDSP_Ver[64]` log, RACH answered, contention resolution, EMM state 1 -> 2 (attach), AUTHENTICATION
REQUEST/RESPONSE, **NAS SECURITY MODE COMMAND** (EMM message `0x5D`). Then the integrity-protection job goes to the LTE
security engine "SEC" (`0x60810000`, `sec_phy.c`, interrupt line 54), which **stalled**. Cause: **DMA into the host's private
memory.** Stock gives the engine link-list nodes and data in its own heap (`0x8327xxxx`); under a foreign host those are a private
mapping, physically Linux's RAM. The fix was a *bounce* copy of each job into an unused physical area (`0x80FF0000`, unused part of
stock's loaded kernel image) and copy-back on completion. With it the attach ran through SECURITY MODE COMPLETE, RRC security,
RRCConnectionReconfiguration with ATTACH ACCEPT (229 B) and ATTACH COMPLETE on SRB2.

General lesson: **every address stock hands to a DMA engine or a DSP must be physical and valid in the host.**

## Blockers after the attach

1. `LTE_ADX: CMD REGION IS FULL` (`layer1_adx_api.c`): the DSP takes one command per 1 ms subframe and the ARM side has no flow
   control; the region overflows when the host stands still for 10-50 ms, then 5-6 commands are issued in a burst.
2. "There is no idle subframeInd buffer!" (`mar_pal_mimoon.c`): the ADX task (prio 12) fills an 8-slot ring at `*(0x822F34DC)` per
   1 ms subframe; the consumer LGRANT (prio 13) did not keep up.
3. **System-wide stalls of 8-52 ms** with the LTE stack running (GSM-only: none): nothing on the CPU runs, not even high-priority
   probes; the stall ends at a line-69 (LTE DSP) interrupt. Likely a bus access held while the LTE DSP sleeps (**Inferred**). It is
   not the scheduler path, LCD, WFI or the drivers.
4. First-touch page faults on stock code read from slow storage stall threads 3-12 ms (mitigated by pre-faulting and locking
   the working set); SIM interrupt storms (about 7 ms of HISR per storm) also contribute.
5. After the attach the DSP sometimes stops for good.

With real-time priorities raised for LGRANT/LCONTROL and pre-faulted memory, a 60 s run completed with the subframe ring
never above one entry and over 31,000 interrupts serviced, then ended on the attach/stall issues above.

## Honest summary

An LTE attach through the stock stack **can** complete on this hardware under a foreign host; LTE user data does **not** work, and
the system-wide stalls are unexplained. LTE+GSM and GSM-only modes are usable ways to avoid it. Mobile data in practice used GPRS
([page 10](10-modem-under-linux.md)).
