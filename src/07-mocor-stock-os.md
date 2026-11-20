# 7. The stock MOCOR OS

MOCOR is Unisoc's closed feature-phone RTOS stack: a **ThreadX** kernel with a
protocol stack and a phone application on top. It is not Android and not KaiOS.

## Two images, one program

| Image | Address of file offset 0 (DHTB header) | First code | Evidence |
|---|---|---|---|
| KernelImg | `0x80E65E00` | `0x80E66000` (ARM vectors, reset to `0x80E6624C`) | 1257 of 2003 UserImg import veneers land on function prologues at this base; the next best base scores 36 |
| UserImg | `0x88000000` | `0x88000200` (Thumb) | 5907 of 10965 in-range code pointers land on prologues; +-0x200 scores at most 129 |

KernelImg and UserImg are **one linked program**. The kernel starts `T_P_APP` at the
fixed address `0x88A5FDEF`, and its initial RAM holds thousands (about 7,500 words) of
absolute pointers into UserImg. Therefore a modified UserImg must be the **stock UserImg
with patches**, keeping every kernel-referenced address; a freshly linked image does not
work. Never combine a UserImg from one build with the kernel of another (the 2024-09 package's
UserImg differs in size from a 2024-08 phone's).

**UserImg to kernel:** UserImg never branches into the kernel directly. It calls **2003 ARM
import veneers** (file offsets about `0xD9194..0xB4A70C`):

```
ldr pc, [pc, #-4]
.word <absolute kernel address>     ; Thumb bit set (odd)
```

The most-called veneers (16k, 10k, 9k call sites, at `0xDA250..0xDA288`) are trace/assert/memory
helpers. **Kernel to UserImg:** absolute pointers into `0x88xxxxxx`, including runs of function
pointers around `0x81A8F08C` (the table the kernel uses to start the MMI and deliver callbacks;
not fully decoded). Odd and even addresses name the same Thumb function (`0x882CE7FB` = `0x882CE7FA`).

## Start-up sequence

```
power-on
  -> BOOT0 -> BOOT1
  -> KernelImg loaded at 0x80E65E00, entry 0x80E66000
       reset path enables the FPU (CPACR = 0x00F00000, FPEXC = 0x40000000)
       ThreadX saves only S0-S31 + FPSCR (D0-D15) on context switch, so any code that
       runs inside a stock task must be built vfpv3-d16 (no D16-D31, no NEON)
  -> system init 0x80F4E31C: listeners (hold-key, see page 3), USB, MMU/VM set-up
       0x80F4E63E (first and only place the UserImg window is created), then
       static thread creation 0x80F473F8 (os_cfg.c) -> SCI_CreateThread builds:
       T_CM, T_DIAG, T_KPDSVR (id 2), T_AUDIO, T_TIMESVR (id 9), then
       T_P_APP: id 21, entry 0x88A5FDEF, 51200-byte stack, priority 228, queue depth 500
  -> scheduler start 0x80E6955C
  -> T_P_APP runs APP_Task (0x88A5FDEE, mmimain.c): init, then the main signal loop
```

APP_Task init (before its loop): trace set-up; resource/NV registration; MMK message queue and
`MMI_UPDATE_MUTEX`; `UILAYER_InitSystem`; power-on reason `0x880D9FB8`; the normal path then registers
the PS service, runs the app/service init (SRV manager, PDP init, settings, call log), starts the
LCD-backlight timer and watchdog registration, and enters the main loop that routes signals by id.

Calibration-style reset modes (1, 3, 5, 14) create a different task set (`T_CM`, `T_DIAG`, `T_AUDIO`) and
no `T_P_APP`.

## UserImg paging

UserImg is not loaded at boot. `0x811E41CE` walks a three-record region table (`0x81C201E0`):
`{0x00000000, 0x100000, type 7}`; `{0x81B00000, 0x100000, ..., type 3}` (the 1 MB physical page pool);
`{0x88000000, 0x1200000, 0x81B00000, type 2}` (the UserImg window). For type 2 it builds empty
page tables and an abort handler (`0x80F37952`) that, on a fault in the window, takes a frame from
the pool and reads 4 KiB at partition offset `va - 0x88000000` from FTL partition 4 (three retries,
then assert). This is why a custom UserImg must stay inside `0x1180000` bytes and why page faults
from NAND appear as latency stalls for any host that reads stock code lazily.

## ThreadX port details (for anyone hosting or tracing it)

| What | Address |
|---|---|
| `_tx_thread_current_ptr` / `execute_ptr` / `preempt_disable` / `system_state` | `0x81C21F78` / `0x81C21F7C` / `0x81C21F8C` / `0x81C21F94` |
| `_tx_thread_schedule` | `0x80E69560` (system stack `0x826B645C + 0x320`) |
| `_tx_thread_system_return` | `0x80E6A5A8` (Thumb veneer, ARM body at +4) |
| `_tx_thread_context_save` | `0x819481E8` (IRQ vector target); IRQ body `0x80E66330` calls dispatcher `0x811EAA40` |
| exception vectors | on-chip RAM `0x0..0x3C`: IRQ -> `0x80E6632C`, FIQ -> `0x80E666D4` (asserts) |

Frames on a thread's stack: solicited `0, cpsr, r4-r11, ip, pc`; interrupt `1, cpsr, r0-r3, r4-r11, ip, lr, pc`.
Interrupt dispatcher `0x811EAA40` (`int_hal.c`): reads the GIC acknowledge, calls a timer hook, indexes a table of
128 entries of 28 bytes at `0x81C202A4`, calls the handler; if it returns `0xE05A05A5` queues the line's HISR
(20-byte entries at `0x81CBA090`, three priority lists) and wakes the HISR thread. Stock also reads ThreadX
internals directly (current thread pointer from about 102 functions), so replacing ThreadX is not an option;
replace its port layer instead.

Layers on top of ThreadX: SCI, OSA, GKI, the LTE OS wrappers, the IMS OS layer. A Wine-style API rewrite would be
about 470 functions (369 OS-layer + ~100 ThreadX core); keeping ThreadX and replacing its port layer plus the shared
hardware is about 30-60 hooks.

## Where the radio stack lives

The whole 2G/3G/4G protocol stack runs **inside the stock AP KernelImg** on ThreadX; the DSPs only do the
physical layer, and there is no separate modem core speaking AT commands. The call/SMS/data control layer (MN:
call control, SMS, PDP) is in the kernel image, reached from UserImg through the 2003 veneers; TCP/IP and PDP
glue (`tcpip`, `DsmPpp.c`) are in UserImg. "Lifting out" the radio stack is not practical (GSM layer 1 alone reaches
33,992 functions, 5.8 MiB, 209 OS entry points). See [page 10](10-modem-under-linux.md).

## Services the user image uses (reference addresses, one build)

Radio getters used by the status bar: signal bars `0x882ED71B(sim)` (0..5), PLMN status `0x883850CD(sim)` (1-3 in
service, 4-7 emergency only), SIM status `0x88385729(sim)` (0 ready, 7 no SIM, 8 not read yet), radio on `0x88389861(sim)`,
operator name `0x883004FD`. Image bases and every address are for the single build examined; **regenerate the address
map for any other build**.

## Heap and RAM facts

Heaps: about 1.9 MiB system, 11.5 MiB app (menus and screens only). Kernel code
`0x80E65E00..0x81A91200` (12.2 MB), RW `0x81C20000..0x81C8E884`, BSS to `0x826B6780`. About 28,000 absolute code
pointers and 37,000 data pointers, with no relocation table: the image cannot be relocated.
