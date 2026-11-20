# 10. Running the stock modem stack under Linux

The phone's 2G/3G/4G protocol stack is inside the stock AP kernel image (ThreadX), with only the
physical layer on the DSPs ([page 7](07-mocor-stock-os.md), [page 8](08-gsm-dsp.md)). A Linux that
replaces the stock kernel therefore loses calls, SMS and mobile data. Writing a new GSM stack
(OsmocomBB-style) was estimated at 3-6 months for GSM alone and was not attempted.

This page describes the alternative that was built and tested: **load the stock kernel and user
images into a Linux process at their own addresses and run the stock radio code there**, with a thin
compatibility layer standing in for the parts of the OS and hardware the stock kernel owned. The
process is called `mocord` (its code is not published: it is built around
the proprietary stock firmware; the kernel side is in
[ums9117-linux](https://github.com/maxmaster55/ums9117-linux)). Think Wine or libhybris, but for an
RTOS with direct hardware access and no relocation table.

## Status at a glance

| Capability | Status |
|---|---|
| Stock memory layout, ThreadX scheduler, SCI/OSA/GKI init, 109 stock threads running | **Proven (hardware)** |
| GSM DSP loaded and fully booted by a Linux driver | **Proven (hardware)** |
| Stock layer-1 init, mailbox/timer interrupts forwarded to the process | **Proven (hardware)** |
| SIM power-on and card answer | **Proven (hardware)** after forwarding the SIM interrupt lines |
| GSM registration on a home network (`+CREG`, `+COPS`, `+CSQ`) | **Proven (hardware)** |
| Voice call, outgoing, connected, held, hung up ("normal clearing"); the called party reported good voice | **Proven (hardware)** (a small number of calls) |
| GPRS data: attach, PDP context, TUN interface, default route; ping, DNS and an HTTP GET | **Proven (hardware)** |
| SIM SMS list/read and phonebook queries | **Proven (hardware)** after kicking stock's SIM-file chain |
| Sending an SMS | not verified in these notes |
| Dual SIM (slot 2) | slot 2 powered correctly but no card answered; **not verified with a card** |
| SIM Toolkit | **not working** (no proactive command reached the AT side) |
| LTE attach | reached ATTACH COMPLETE once; **no user data** ([page 9](09-lte.md)) |
| Stability | **limited**: the GSM DSP deadline assert recurs under load (see below) |

Be explicit about scope: all results are from one phone and one operator environment. Treat
"works" as "demonstrated", not "robust".

## Why it is possible, and what could have stopped it

- Stock's ThreadX can be **kept**: only its port layer (context switch, interrupt control, tick) and the
  shared hardware are replaced, about 30-60 hooks, rather than rewriting ~470 OS API functions.
- Three risks were identified up front: layer-1 timing, hardware that both sides touch, and hidden
  physical-address use (DMA, DSP pointers). All three bit in practice; the timing one still does.
- The image cannot be relocated (about 28,000 absolute code pointers and 37,000 data pointers, no
  relocation table), so it is mapped at its own virtual addresses.

## Architecture

**Memory.** Map the kernel code `0x80E65E00..0x81A91200` and the user image at `0x88000000` with
`mmap(MAP_FIXED)` (file-backed, only touched pages use RAM). User space reaches `0xBF000000` with a 3G/1G
split. Reserve `0x81B00000..0x826B8000` (11.7 MiB), the DSP ranges and the two 128 KiB blocks as `no-map`
so that physical addresses stock hands to DMA or a DSP remain valid. That gives the rest of the system
about 42 MB instead of 22 MB. Stock's heaps (INFRA 1.5 MB, STACK 7.7 MB, OSA 16.4 MB pools at
`0x8276D000`) grew to about 25 MB touched; a compressed RAM swap plus a swap file is needed on a 64 MB phone.
Mapping the vector page at 0 needs `vm.mmap_min_addr=0`.

**I/O.** Modem I/O at `0xC0000000..0xEFFFFFFF` cannot be mapped by a user process. About 190 candidate
literal words in 108 functions (`0xE0410000`, `0xE0440000`, `0xE0020000`, ...) were treated by emulating the
access in a SIGSEGV handler (decode Thumb/ARM load/store forms). SIGILL handler skips CP15 and WFI. An unaligned
access to device space reads 0 and drops writes (stock's NVM idle task does 390+ per LTE run). A small
kernel driver arbitrates shared hardware (interrupt controller, AP timer, ADI/PMIC, clock gates, AP DMA,
watchdog, deep sleep).

**Interrupts.** A tiny kernel driver (`mocirq`, `ums9117-irqfwd` in ums9117-linux) masks the line and signals the process; the signal
handler acts as the interrupt, calls stock's handler (and queues the HISR), then switches threads by
editing the saved context. Lines that matter: mailbox 68/69, modem timers 113/115, `DMA_LINK` 71, SIM0
line 10 and SIM1 line 13 (**without forwarding these the SIM never answers**), and line 93. The OS tick
comes from a Linux timer (stock must never reprogram the timer Linux uses, SPI 29); stock's ThreadX is
tickless (a sorted timer list and one interrupt after N ms).

**Scheduler.** Each ThreadX thread's registers are kept by the host (`ucontext`: r0-r15, CPSR with
Thumb/IT bits, VFP), a switch happens by swapping the handler's `ucontext` so the kernel's sigreturn restores
everything, which user code cannot do (IT bits). A flag replaces the CPSR I-bit; interrupt-control functions
(`0x81244A48/68/88`, which silently do nothing in user mode) are hooked. Self-test: two stock threads sleeping 30
and 50 ms ran in the right order and times (within 1 ms). Run the stock image as `SCHED_FIFO` (about priority 50) with
`mlockall`, and pre-fault and lock the used part of the user image: first-touch page faults from an SD card
stalled stock threads 3-12 ms.

**Start-up order.** Stock's kernel start `0x80E67158` -> init thread `0x80F4E6E4` -> full boot function
`0x80F4E31C` cannot run as a whole (it owns the LCD, flash, USB, keypad). The compatibility layer instead runs:
memory layout, ThreadX init, SCI init (`0x8151A9AA`), HISR init (`0x80EA2FCA`), the static thread table
(`0x80F473F8`), mailbox init (`0x815252C2` plus the HAL init `0x812BA320`, see below), then stock's normal-mode start
`0x80F33EF2`, then the scheduler. Stock starts the GSM DSP itself inside it.

**Hooks (about 25 for the first milestone):** trace/printf, sleep, asserts and OSA fatal, irq off/restore,
NV size/read (served from a backup of the NV partition), ISR register/enable/disable, SCI/OSA allocators, user-image protected
read, serial read stub. NV writes go to a file; **stock's flash layer must never write NAND**.

**Control.** The MN layer (call, SMS, PDP control) is reachable through the 2003 kernel entry points the user
image imports. Stock's AT command processor (ATC, in the user image) was used as the control interface: the host
talks AT to it over a pseudo-port, and where the AT layer cannot do something it calls stock functions directly
(for example PDP activation via the helper at `0x815E01F8`, because `AT+CGACT` is remapped and the address is not shown on
the AT side). Stock's own SIM-power replay (`0x80F19004(dual_sys, 0)` is the call that really starts the SIM; the
app-level request `0x8150AF88` is a no-op in the post-power-on state).

## Bring-up findings that cost days

1. **Mailbox HAL init `0x812BA320`** is only called from the full boot function, so a host that skips it never services
   the DSP's init handlers even though mailbox line 69 fires. Replicate its few global words. After that, GSM layer 1
   activates, scans, and the phone **registers**. (The "L1:event fail Act" assert, `layer1_main.c:9897`, was this.)
2. **GSM-only mode** (`AT+SPTESTMODEM=10,254` after the SIM power-on and before the stack power-on) removes the LTE
   power-up wait and its assert (`nam.c` NAS guard timer, 20 s). `^SYSCONFIG` changes nothing in this build.
3. **SIM start**: forward lines 10/13; the SIM driver tries 1.8 V then 3.0 V and gives up if no ATR interrupt arrives.
4. **GPRS attach**: a "SIM-ready replay" byte (MNC app-present, `0x81C26A56`) left set makes the SIM layer's GMM
   authentication entry (`0x80F177E0`) fail every PS authentication; clear it before attaching.
5. **SMS/phonebook** need stock's MNSIM chain started (`0x8101CFEE(dual)` posts step 19 for a 2G SIM, 166/399 for a
   USIM); the MMI normally calls it at boot, the host must. Then `AT+CPMS?`/`AT+CPBR` work. Entry 1 empty reads as "SIM busy" (`65536014`); that
   error code is stock's generic "parameter/type mismatch", not "SIM busy".
6. **Freeze handling:** a DSP start with nobody serving the mailbox froze the phone a few ms later and needed a manual
   reset every time. A PMIC-counter software watchdog (arm 8 s, reload four times per timeout from a kernel work item, off by default) turned
   freezes into automatic reboots about 17-23 s long.
7. **Raw ADI reads while the stack runs froze the phone**; and several early freezes came from the host touching
   `0xE0020000` before the radio power-on.

## Calls

Voice: stock opens the voice path (`!call:0x8174EA48` at alerting in one experiment); the DSP does the speech codec; stock
owns the codec and VBC during the call while the host's own audio driver steps aside. A test call was dialled, alerted,
connected after 8 s, held 30 s and hung up with "normal clearing", no assert, with about 1500 speech frames each way through stock's voice
processing (handset, main mic + line out, 8 kHz); the called party reported good voice.
**Known failure:** a host that keeps its own PCM playback open (ringtone, vibration implemented through audio) resets the VBC and powers the codec
off when it closes the PCM under the voice path, which is the likely cause of a crash when *answering* a call. The robust fix is for the host's audio to
refuse to open while the VBC owner bits indicate a call, and to leave the codec alone on close ([page 5](05-audio.md)).

## Mobile data

GPRS works through stock's TCP/IP-less path: attach, then the stock helper that defines and activates context 1 (`0x815E01F8(0, apn, 0)`),
read the address/DNS from stock's tcpip record (`0x81E70BEC`), and bridge IP packets between the PDP context and a Linux TUN
device cut at the DSM layer (bypassing stock's own stack). Result: a default route, ping about 265-765 ms, DNS and HTTP work.
Reconnects drop the interface address and route, so back off reconnect attempts (30 s, 1, 2, 5, 10 min) instead of retrying every
30 s. Caveats seen: a recurring `dsp assert 0x1c20` forced data restarts; sending `AT+COPS=3,0` on every poll made stock keep re-selecting the
network name; the DNS file and default route should not be overwritten when Wi-Fi is up.

## What still limits it

- **The GSM DSP deadline assert (`dspintisr.c:0x24b`, code `0x1c20`)** is the main modem killer: layer 1 must refill the frame queue within
  1-3 frames (4.6-13.8 ms). It occurs under load, especially SD-card I/O (including paging stock code from a card), large `/proc/<pid>/mem`
  reads, heavy logging, and the LCD push. Mitigations that helped: a PREEMPT_RT kernel (mainline `6.12` plus the RT patch set; the plain
  `PREEMPT` option adds about 46 KB), SCHED_FIFO with locked and pre-faulted memory, an RT-priority IRQ thread, a raw (non-sleeping) LCD lock, preemption
  disabled around ADI. Logged over several days one build still saw tens of restarts per day.
- **Memory**: free RAM stays around 3-6 MB; stock's pool region (`0x826B7000..0x83FE0000`, 25 MB) sits in compressed swap.
- **LTE**: see [page 9](09-lte.md).
- **Address fragility**: every code address here is for one stock build; generate and verify the address table, do not hand-copy it.
- **SIM Toolkit** and dual SIM remain open.

## Reproducing or extending it

Order of attack that worked: boot the stock kernel under an emulator (Unicorn/qemu-user with fake hardware) to find
what each init step needs; do hardware steps one call at a time (radio power-on `0x8106469A`, layer-1 init `0x8104B65E`, GSM
`l1_init` `0x814A678E`, DSP start `0x8119941E`); keep a freeze watchdog armed; add one forwarded interrupt at a time; only then run stock's scheduler.
An exact-dump approach (use the phone's own kernel read back over USB, not the vendor package) is essential because the
addresses differ between builds.

Related prior art: `openfeaturephone/f286-bringup` and `ruio-f286` (Linux on the same SoC family), `lovelytingy/Nokia-2660-Emulator`
(emulator, no modem), OsmocomBB, and Wine/libhybris/qemu-user for the idea of loading a foreign binary and redirecting its system layer.
