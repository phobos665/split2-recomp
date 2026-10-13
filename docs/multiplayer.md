# Multiplayer: System Link for TimeSplitters 2

Status (13 October 2026): System Link works on Windows, between copies of
this build on one PC, on a LAN and over the internet. It does not work on
macOS yet. Split-screen multiplayer works on both.

TimeSplitters 2 has System Link (LAN play between consoles) and no Xbox Live,
so there is no online service to replace. The toolkit emulates the console's
network card and carries its Ethernet frames between copies, and the game's
own network code runs unchanged on top. How the card, the sessions and the
crypto work is toolkit material, in
`xboxrecomp/docs/technical/system-link.md`. This file keeps what is specific
to TS2.

## Playing

The README's System Link section covers it for players: one copy hosts a
session from the launcher's System Link tab (or `RECOMP_SYSLINK=host`), the
others join it (`RECOMP_SYSLINK=join RECOMP_SYSLINK_HOST=<address>`), and then
everyone uses the game's own Arcade > System Link menu.

Two copies on one PC, each with its own save folder so each has its own
Ethernet address:

```text
copy A: RECOMP_SAVE_DIR=<a> RECOMP_SYSLINK=host RECOMP_SYSLINK_UPNP=0
copy B: RECOMP_SAVE_DIR=<b> RECOMP_SYSLINK=join RECOMP_SYSLINK_HOST=127.0.0.1
```

TS2 keeps its profiles under `UDATA` in the game folder, which
`RECOMP_SAVE_DIR` does not cover. Run scripted copies from copies of the game
folder without `UDATA`.

## How TS2's network code runs

The game links Microsoft's network library (XNet) into its own executable, in
the `XNET` section (VA `0x0020B0E0` in PAL, `0x0020ACC0` in USA, 37,836
bytes). It does not start the stack at boot: nothing touches the network card
until Join Game, or the hosting path, starts XNet. That is also when the
game first asks for the console's Ethernet address.

The PAL driver is five functions at `0x0020F578` to `0x0020FD1E`. Its
interrupt routine (`0x0020F742`) connects on bus level 4. The register-level
trace of what it does is in the toolkit's doc ("What XNet does, measured").

To find a game, XNet broadcasts UDP from port 3074 to port 3074, from IP
0.0.0.1. There is no DHCP on System Link.

## What TS2 needed

One seed. Selecting System Link makes an indirect call to `0x0009D530`
(PAL), which discovery had not found. The skipped call returned 0, the game
took its error path and crashed writing through `0xFFCFFFF0`. The seed is in
`config/pal/seeds.json` and in the toolkit's `config/seeds/4553000A.json`.

Everything else was toolkit work that every title gets: the network card,
a unique Ethernet address per save folder, a kernel fix that had moved the
card's interrupt to vector 0, and real Diffie-Hellman and triple DES in place
of the stubs.

## Measured

Two PAL copies on one PC, Deathmatch, 150 seconds in the level:

| Run | Joined | Match | Frames (host out / in) |
| --- | --- | --- | --- |
| No added delay | yes | held to the end | 1654 / 1506 |
| 100 ms added each way | yes | held to the end | 1336 / 1233 |
| 50 ms each way, 5% loss | yes | held to the end | 1324 / 1157, 130 dropped in all |

In a match TS2 sends about 11 frames a second each way. The largest frame
seen during the join was 298 bytes. Match traffic has not been measured for
frame size.

## Not done or not checked

- macOS. The toolkit's network card is Windows-only: on POSIX the register
  page is plain memory and the game finds no games. This is toolkit work.
- The USA release. Nobody has opened System Link in it yet. Expect the USA
  counterpart of `0x0009D530` to be missing from `config/us/seeds.json`.
  Find it with `tools.seed_from_log` from a run that selects System Link.
- Playing against xemu or a real console. It needs the player's own
  `XboxLANKey` in `keys.ini`. Two recompiled builds agree on an all-zero key,
  which is why they play each other without one. Untested.
- XLink Kai.
- More than one player per copy (split screen over System Link). It
  multiplies traffic, and has not been tried.
- The intermittent `0xFFFFFFFF` exit (see `CLAUDE.md`) would end a session
  for everyone if it hit the host.
