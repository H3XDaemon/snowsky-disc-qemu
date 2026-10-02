# What qemu-user cannot show

The emulator runs the player's user-space programs on the Docker VM's kernel.
Everything below is decided by the player's own kernel or hardware, so it is
checked only on a player (or in a future full-system emulation). For each item:
what is missing, what stands in for it here, and what catches the difference.
Current on 2026-10-02 for V2.57 and the pinned qemu 7.2.22.

| Outside qemu-user | Why | What covers it here |
| --- | --- | --- |
| **FPU trap of the player's kernel** | Linux 4.4.94 emulates the delay slot of a taken FPU branch on the user stack; a hard-float program without an executable stack dies there. qemu-user executes FPU instructions itself. | The [FPU guard](#fpu-guard): `guest_run` refuses such a program and a stock-init guest reports it. Build services soft-float and check `readelf -A`. |
| **NAND, MTD, UBI/UBIFS, mask ROM, USB Boot** | No guest kernel and no flash. `/usr/data` is a directory or an ext4 image; the rootfs is an unpacked tree. | Size limit and power loss on the image ([stock init](stock-init.md#usrdata-as-its-own-filesystem)); image layout and writers are verified by their own tools, flashing only on a player. |
| **USB gadget: configfs, UDC, `ttyGS0`, storage and DAC modes** | No UDC; a guest must not mount the VM's configfs. A relative configfs link target that fails on the player is accepted by an ordinary filesystem. | Cable *power* detection only ([idle power](idle-power.md)). Gadget code needs a fixture that models configfs's immediate target lookup, and a player. |
| **Suspend / resume** | The stock standby path ends in kernel suspend; here the display stub goes dark and processes keep running. | Screen sleep, idle power-off and power events are modelled; wake sources and resume timing are not. |
| **Memory: real RSS and limits** | A guest process is a qemu process: 12–17 MiB RSS where the player shows hundreds of KiB, and about 2.6 GiB of reserved address space, so `RLIMIT_AS` and memory cgroups measure qemu. | Growth relative to a warmed baseline, descriptor and thread counts. Absolute memory only on a player. |
| **`/proc` of the player's kernel** | `/proc` is the VM kernel's: `/proc/<pid>/io` exists here and not on the player; `/proc/asound`, `/proc/mtd`, `/proc/cpuinfo` differ or are absent; `exe` and `cmdline` name qemu. | `comm` is faithful. The output stream is published under `/emu/asound` ([audio](audio.md#output-stream-state)); `exe` is corrected for BusyBox readers ([stock init](stock-init.md#process-identity-under-qemu-user)). Do not rely on `/proc/<pid>/io`. |
| **CPU speed and timing** | Translation on a fast host: no cycle accuracy, different scheduling, no DAC clock. | Timeouts and ordering are exercised, durations are not evidence. See [slowing the guest](#slowing-the-guest). |
| **Guest clock** | Time calls reach the shared kernel; it cannot be offset per guest. | [Not adjustable](environment.md#guest-clock-not-adjustable); test wrong time in the program under test or on a player. |
| **Radio: Wi-Fi association, Bluetooth, RSSI** | No driver. | An emulated `wlan0` link with controllable state and address, isolation and bandwidth limits ([network](network.md#emulated-links-isolation-and-shaping)). |
| **mDNS from the guest, LAN reachability** | The stock `avahi-daemon` aborts under qemu 7.2 (truncated control messages); a container is not on the host LAN. | A host-side stand-in, opt-in ([network](network.md#mdns-and-the-host-lan)). |
| **MCU and analog output** | No SPI/ADC hardware. Stock never talks to the MCU ([report](../../research/docs/reports/reset-all.md)). | PCM capture before the DAC; DAC attenuation mirrored for the viewer; an opt-in [jack model](audio.md#analog-output-jack-model) feeds stock's own detection. The player's "playing with no output, no file open" state was not reproduced. |

## FPU guard

`emulator/runtime/abi.py` reads a program's ELF headers. A hard-float MIPS
program is refused when its stack is not executable (`PT_GNU_STACK` without the
execute flag) or when it is linked against musl, whose threads never get an
executable stack. The stock programs pass: they are hard-float glibc programs
without `PT_GNU_STACK`, which is why they work on the player.

- `guest_run` checks the program it starts (also in the `qemu-mipsel-static -0
  name PROGRAM` form) and returns 126 with a `[fpu-guard]` message.
  `FPU_GUARD=warn` prints and runs, `FPU_GUARD=off` skips the check.
- A stock-init guest starts image programs without `guest_run`; when the UI is
  up, executables under `/opt` and `/usr/data` are scanned and trapping ones are
  listed in `machine.log` and as `fpu_trap` in `./emulator/run.sh power status`.
- `python3 -m emulator.runtime.abi check FILE…` is the same check for a build step.

It cannot see a static musl program built with an executable main stack (its
threads would still trap) or FPU use in a library loaded later. Soft-float
(`readelf -A`: `FP ABI: Soft float`, no FPU opcodes in the disassembly) remains
the rule for programs meant for the player.

## Socket error numbers

MIPS has its own `errno` numbering. qemu-user translates the error a system call
returns, but qemu 7.2 does **not** translate the value read with
`getsockopt(SO_ERROR)`: after a refused non-blocking `connect` a guest program
reads the host's `ECONNREFUSED` (111) where the player returns 146. The blocking
`connect` path returns 146 correctly. `emulator/tests/guest/soerror.c` shows
both, and a firmware-free test pins the behaviour so an image update that fixes
it is noticed. Debian 13's qemu-user translates the value correctly; the pinned
qemu is not replaced here, because one qemu registration serves every emulator
container of the Docker VM and a version change needs the full regression.

Until then: take the result from the system call's own `errno` (a bounded
blocking `connect`, or `connect` again on the non-blocking socket), not from
`SO_ERROR`. Do not special-case 111 in code that ships to the player.

## Slowing the guest

Host speed hides timeouts and races. Two blunt tools, neither a timing model:

- CPU: `EMU_CPUS=0.25` in `emulator/.env` (Compose `cpus`, `0` = no limit) caps
  the whole container, viewer included; or
  `docker update --cpus 0.25 <container>` on a running one. Everything gets
  slower evenly: useful for finding assumptions about start-up order and
  readiness, not for measuring.
- Network: `python3 -m emulator.runtime.network shape --rate 800kbit --delay 60ms`.
