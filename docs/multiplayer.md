# Multiplayer: System Link for TimeSplitters 2

Status: planning (29 September 2026). Nothing described here is built yet.

TimeSplitters 2 has split-screen multiplayer, which works today, and System Link:
LAN play between consoles. It has no Xbox Live support, so there is no online
service to replace. The work is to make System Link work between copies of this
recompilation, then carry it over the internet.

## How TS2's networking works on the console

The game links Microsoft's network library (XNETS) into its own executable. The
whole stack runs as game code: sockets, the secure key exchange between consoles,
UDP/IP, and the driver for the network card. In this XBE it sits in the `XNET`
section (VA `0x0020B0E0` in PAL, `0x0020ACC0` in USA, 37,836 bytes). `config/<region>/xdk_symbols.json` names 8 of its
functions (`XNetStartup`, `WSAStartup`, `socket`, `bind`, `recv`, `ioctlsocket`,
`XNetGetEthernetLinkStatus`, `XnInit`). The rest are unnamed.

Below the library is the hardware: the MCPX network card, programmed through
memory-mapped registers at `0xFEF00000` and signalling through an interrupt. The
kernel's part is small: `PhyGetLinkState`, `PhyInitialize`, the console's MAC
address from the EEPROM, and connecting the interrupt handler.

TS2 does not start the stack at boot. No network interrupt is connected before
the front end, so it presumably starts when System Link is chosen.

## What the toolkit does today

| Piece | State |
| --- | --- |
| Network card registers at `0xFEF00000` | Plain zeroed memory, part of the 8 MB MCPX aperture. No device behind it |
| `PhyGetLinkState` / `PhyInitialize` | Report link up; do nothing |
| MAC address (`XC_FACTORY_ETHERNET_ADDR`) | The same fixed value, `00:50:F2:00:00:01`, in every copy |
| Calling a game's interrupt handler from a device model | Exists: the USB (OHCI) model does it (`src/usb/ohci.c`) |
| Trapping reads and writes to device registers | Exists: the APU and NV2A hooks (`src/apu/apu_mmio_hook.c`) |

So opening System Link today reaches a network card that never answers.

## The approach: emulate the network card

Emulate the MCPX network card in the toolkit and carry its Ethernet frames
between players. The game's own network code then runs unchanged, including the
secure key exchange that System Link depends on.

This is what xemu does, and it is why XLink Kai works for real consoles: at the
Ethernet level, System Link is just frames on a LAN.

Why not replace the socket calls instead:

- It is per game. Every function in the network library has to be found in each
  XBE, and only 8 are known in this one.
- It has to fake the secure-networking layer (keys, addresses, the "secure"
  sockets) rather than letting the game's code do it.
- It cannot talk to xemu or to real consoles.
- The next game gets nothing from it.

It would save about a week for TS2 alone. Not worth it.

## Work items

### Toolkit (xboxrecomp): nothing here is specific to TS2

1. **Network card model.** Registers, the transmit and receive descriptor rings
   in guest memory, the PHY/MII registers the driver polls, and the interrupt
   status and mask. xemu's `nvnet` is the reference. Check its licence before
   porting code; xboxrecomp is GPL-3. *About 1–1.5 weeks.*
2. **Interrupt delivery.** Raise the network interrupt into the game's connected
   handler, the way `ohci.c` does for USB. *1–2 days.*
3. **A unique MAC address per install.** Generate one on first run and keep it
   in the settings file. Two copies with the same MAC cannot share a network.
   *Under a day.*
4. **Frame transport.** A backend interface with a first backend that sends raw
   frames over UDP to configured peers and relays broadcasts, which System Link
   uses to find games. That covers two copies on one PC or one LAN.
   *2–3 days.*
5. **Settings and launcher.** Enable networking, pick a backend, list peers or
   the relay address. *1 day.*
6. **Optional: an XLink Kai backend.** Kai's engine accepts Ethernet frames over
   a local UDP API. This gives internet play without running our own server, and
   play against xemu and real consoles on Kai. *2–3 days.*
7. **Optional: our own relay and lobby server**, if Kai is not acceptable.
   *1–2 weeks.*

### This repo (TS2)

1. **Bring-up.** Run two copies on one PC, start a System Link game on one and
   join from the other. Expect code paths no run has reached so far: new
   unresolved indirect calls (these become seeds), lifter bugs in the network
   code, and timing assumptions. *3–10 days.* This is the largest unknown on the
   list.
2. **Test with two machines**, then over the internet through the chosen
   backend. Watch for desyncs and for TS2's tolerance of latency.
3. **Defaults.** Whatever TS2 needs in `4553000A.conf` for networking.

## Estimate

| Scope | Estimate |
| --- | --- |
| LAN play: two copies on one PC or one network | 3–5 weeks |
| Internet play through XLink Kai | 4–6 weeks |
| Internet play through our own server | 5–8 weeks |

Confidence is low to medium. Nobody has run TS2's network code under the
recompiler yet, and the bring-up item could be short or long.

## Risks and open questions

- **Timing.** The game's logic steps once per frame (uncapping the frame rate
  breaks it), so two copies must both hold 60 fps. How TS2 handles a peer that
  drops frames is unknown.
- **The intermittent exit** (`0xFFFFFFFF`, see `CLAUDE.md`) will end network
  sessions at random until it is found.
- **Interrupt re-entrancy.** The network interrupt arrives while game code is
  running. The OHCI model delivers its interrupt at safe points; the network
  card needs the same care, or the handler corrupts the state of the code it
  interrupts.
- **Players per console.** Up to four split-screen players on each copy share
  one link; worth testing early, because it multiplies traffic.

## Where this document goes

The toolkit part belongs in `xboxrecomp/docs/technical/` once work starts, per
the rule in `CLAUDE.md` (no fact about TS2 means toolkit). This file then keeps
only the TS2 bring-up and results.
