# split2-recomp

TimeSplitters 2 for the original Xbox, recompiled into a native program for
Windows and macOS. You build it from your own copy of the game: the build
translates the game's code to C on your machine and compiles it against the
[xboxrecomp](https://github.com/phobos665/xboxrecomp) toolkit. This repository
contains no game code or data.

## What works

- The front end, story mode and System Link deathmatch have been played.
  Challenge and MapMaker have had little testing.
- 60 fps, paced the way the console paced it.
- Widescreen. The camera is widened rather than stretched, and the menus and
  HUD are laid out for 16:9.
- Rendering at up to 8x the console's 640x480.
- Frame interpolation: 120 or more frames a second on screen while the game
  itself runs at 60.
- Fullscreen and variable refresh rate (G-SYNC, FreeSync).
- Controllers and keyboard, both rebindable.
- System Link on Windows, over a LAN or the internet. Not on macOS yet.

## What you need

TimeSplitters 2, PAL or USA, extracted from your disc. The build reads
`default.xbe` to tell which release it is, and stops if it is neither (see
[Other releases](#other-releases)).

Windows 10 or 11, 64-bit:

- Visual Studio 2022 or 2019 with the Desktop development with C++ workload
- [CMake](https://cmake.org/download/) 3.20 or newer, on PATH
- Python 3.10 or newer with `capstone`: `py -3 -m pip install capstone`
- Git

macOS on Apple Silicon:

- Xcode's command line tools: `xcode-select --install`
- CMake, Ninja and OpenSSL from Homebrew: `brew install cmake ninja openssl@3`
- The [LunarG Vulkan SDK](https://vulkan.lunarg.com/sdk/home#mac), installed
  system-wide. It provides MoltenVK and the shader compiler.
- Python 3.10 or newer with `capstone`. Homebrew's Python will not install
  packages globally, so use a virtual environment:
  `python3 -m venv ~/.venvs/recomp && ~/.venvs/recomp/bin/pip install capstone`

## Build

```sh
git clone --recursive https://github.com/phobos665/split2-recomp.git
cd split2-recomp
```

Copy the extracted disc into a folder called `game`, so that `game/default.xbe`
exists with `data/`, `music/` and the rest beside it. Then:

```sh
py -3 scripts/build.py                     # Windows
~/.venvs/recomp/bin/python scripts/build.py   # macOS
```

The first run translates the game, which takes a few minutes, then compiles
it, which takes longer. Later runs only recompile. The program ends up in
`build/Release/`:

| | Windows | macOS |
| --- | --- | --- |
| The game | `split2_recomp.exe` | `split2_recomp` |
| Settings window, then the game | `split2_recomp_launcher.exe` | none yet |

If you cloned without `--recursive`, run `git submodule update --init --recursive`.

## Play

On Windows, run `split2_recomp_launcher.exe` to choose settings and play, or
`split2_recomp.exe` to start straight away. On macOS, run `split2_recomp`.
You can make a shortcut to either from anywhere.

| Key | |
| --- | --- |
| F9 | Show or hide the frame rate |
| F10 | Change the frame cap: adaptive, 60, 30, off |
| F11 | Save a screenshot and a capture of the frame beside the program, for bug reports |
| Alt+Enter | Switch between fullscreen and a window |

Controllers work as an Xbox pad. The keyboard plays as controller 1:

| Xbox | Key |
| --- | --- |
| D-pad | Arrows |
| A, B, X, Y | Z, X, A, S |
| Start, Back | Enter, Backspace |
| White, Black | Q, W |
| Left, right trigger | E, R |

Change them in the launcher's Input tab, or in `input_bindings.json` (format in
`xboxrecomp/docs/technical/input-binding.md`).

| | Windows | macOS |
| --- | --- | --- |
| Saves | `game\UDATA\4553000a\` | `game/UDATA/4553000a/` |
| Settings | `%APPDATA%\xboxrecomp\titles\4553000A.conf` | `~/Library/Application Support/xboxrecomp/titles/4553000A.conf` |
| Controls | `%APPDATA%\xboxrecomp\input_bindings.json` | `~/Library/Application Support/xboxrecomp/input_bindings.json` |
| Log, when not started from a terminal | `build\Release\split2_recomp.log` | `build/Release/split2_recomp.log` |

## Settings

These are rows in the launcher's Video tab, and lines in the settings file.
Every line can also be set with the environment variable shown, which wins
over the file.

| Setting | File | What it does |
| --- | --- | --- |
| Resolution | `resolution_scale` (`RECOMP_RES_SCALE`) | Renders at 1 to 8 times 640x480 and filters down. 2 is much sharper and costs little |
| Widescreen | `widescreen` (`RECOMP_WIDESCREEN`) | 16:9, with the wider camera and menus |
| Texture sharpness | `anisotropy` (`RECOMP_ANISO`) | Anisotropic filtering, 1 to 16 |
| Frame rate | `frame_cap` (`RECOMP_FPS_CAP`) | Adaptive (the default), 60, 30, or 0 for uncapped |
| Show frame rate | `fps_overlay` (`RECOMP_FPS_OVERLAY`) | Start with the counter on |
| Fullscreen | `fullscreen` (`RECOMP_FULLSCREEN`) | Borderless fullscreen |
| Variable refresh rate | `vrr` (`RECOMP_VRR`) | In fullscreen, an even 60 on a high refresh display. It has to be on in the display's driver too |
| Frame interpolation | `frame_interp` (`RECOMP_FRAME_INTERP`) | 2 shows twice the game's frames, up to 4. 1 is off. Best with variable refresh |

The game runs its logic once a frame, so an uncapped frame rate makes it run
fast. Use frame interpolation for smoother motion instead.

To keep the front end at 4:3 between bars while the levels are 16:9, add
`ts2_menus = 43` to the settings file (`RECOMP_TS2_MENUS=43`).

## System Link

Windows only for now. On macOS the network card is not emulated yet, and
the game finds no System Link games.

One player hosts a session and everyone else joins it. Up to 16 copies can be
in one session. In the launcher's System Link tab:

- Host a session. The tab shows the address to give the others: your PC's
  address on your own network, and your internet address once your router
  answers. With Open the router on (the default), the game asks your router
  (over UPnP) to forward UDP port 27610 while you host. If your router does not
  support UPnP, forward that port to your PC yourself.
- Join a session. Enter the host's address, with `:port` at the end if they do
  not use 27610. A joining player does not need to open anything.
- Join code. Optional. If the host sets one, only players who enter the same
  word can join.

Then everyone starts the game and opens System Link from its own menus, as on
a console. Any player can host the game there, not only the one who hosts the
session. The session ends when its host quits.

Without the launcher, set it in the environment:

```text
host: RECOMP_SYSLINK=host [RECOMP_SYSLINK_PORT=27610] [RECOMP_SYSLINK_CODE=word]
join: RECOMP_SYSLINK=join RECOMP_SYSLINK_HOST=81.2.3.4[:port] [RECOMP_SYSLINK_CODE=word]
```

Copies of this build can play each other without anything else. To play
against xemu or a real console, you also need your console's `XboxLANKey` in
`%APPDATA%\xboxrecomp\keys.ini` as `lan_key = ...`. The details are in
`xboxrecomp/docs/technical/system-link.md`.

## Other releases

The build identifies the release by the SHA-1 of `default.xbe`:

| Release | `default.xbe` SHA-1 | Addresses |
| --- | --- | --- |
| PAL | `2809eb147385723eaa90c425be89ee4db033fc5a` | `config/pal/` |
| USA (NTSC) | `3ec95fe3ae9e7794d83a5b489ad8583f352e0c18` | `config/us/` |

Each folder lists addresses inside that release's `default.xbe`: function
entry points, XDK functions and the places this repository's fixes attach to.
Any other disc, such as the Japanese release or another revision, needs a
folder of its own. The build stops and prints the SHA-1; please open an issue
with it.

## Updating

```sh
git pull
git submodule update --init --recursive
py -3 scripts/build.py --relift
```

On macOS, use `~/.venvs/recomp/bin/python` in place of `py -3`. `--relift`
translates the game again, which is needed whenever the toolkit or `config/`
changes.

## Problems

- "no default.xbe in ...": the disc's files are not in `game/`.
- A black window and nothing else: read the log (see [Play](#play)).
- A rendering bug in one place: press F11 there, and attach the `.bmp` and
  `.d3dcap` files it writes to an issue.

## Legal

You need your own copy of TimeSplitters 2. Do not share `game/`, `src/recomp/`
(it is the game's translated code) or anything in `build/`. This repository and
xboxrecomp contain no game code or assets.
