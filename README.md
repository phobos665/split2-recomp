# split2-recomp

TimeSplitters 2 (Xbox) as a native Windows program. It is built from **your own
copy of the game**: the game's code is translated to C on your machine and
compiled against the [xboxrecomp](https://github.com/phobos665/xboxrecomp)
toolkit. No game code or data is in this repository.

It plays: the front end and story mode have been played through a level, at
60 fps, with higher internal resolution, a frame counter and rebindable
controls. Other modes have not been tested yet.

## What you need

- Windows 10 or 11, 64-bit
- Visual Studio 2022 (or 2019) with the **Desktop development with C++** workload
- [CMake](https://cmake.org/download/) 3.20 or newer, on PATH
- Python 3.10 or newer, with `capstone`: `py -3 -m pip install capstone`
- Git
- **TimeSplitters 2, PAL or USA release**, extracted from your disc. The build
  reads `default.xbe` to tell which one it is, and stops if it is neither; see
  [Other versions](#other-versions).

## Build

```bat
git clone --recursive https://github.com/phobos665/split2-recomp.git
cd split2-recomp
```

Copy the extracted disc into a folder called `game`, so that `game\default.xbe`
exists (with `data\`, `music\` and the rest beside it). Then:

```bat
py -3 ./scripts/build.py
```

The first run translates the game (a few minutes) and then compiles it (longer).
Later runs only recompile. When it finishes it prints where the program is:

```text
build\Release\split2_recomp.exe             the game
build\Release\split2_recomp_launcher.exe    settings window, then starts the game
```

If you cloned without `--recursive`: `git submodule update --init`.

## Play

Run `build\Release\split2_recomp_launcher.exe` to choose settings and play, or
`split2_recomp.exe` to start straight away. Either can be shortcut from anywhere.

| Key | Does |
| --- | --- |
| F9 | show or hide the frame rate |
| F10 | step the frame cap: adaptive, 60, 30, off |
| F11 | save a screenshot and a capture of the frame, beside the executable, for bug reports |

An Xbox or XInput controller works as itself. On the keyboard: arrows = D-pad,
Enter = Start, Backspace = Back, Z = A, X = B, A = X, S = Y, Q = White,
W = Black, E = left trigger, R = right trigger. Rebind both in the launcher's
Input tab.

**Where things are kept:**

- Saves: `game\UDATA\4553000a\`
- Settings: `%APPDATA%\xboxrecomp\titles\4553000A.conf` (the launcher writes it)
- Controls: `%APPDATA%\xboxrecomp\input_bindings.json`
- Log: `build\Release\split2_recomp.log`, when started without a console

## Settings

In the launcher's Video tab, or in the settings file:

| Setting | What it does |
| --- | --- |
| Resolution scale | Renders at 2x to 8x the console's 640x480, then filters down. 2 is cheap and much sharper |
| Texture sharpness | Anisotropic filtering, 1 to 16 |
| Frame cap | Adaptive (the default: 60, but a late frame shows at once rather than waiting a whole extra frame), 60, 30, or off |
| Widescreen / wide camera | **Experimental.** The game has no 16:9 mode of its own, so widescreen alone stretches it. Wide camera (register 60) widens the 3D view, but the HUD is stretched too |

"Off" for the frame cap lets the game run as fast as your PC can. The game was
built for 60 and some things may run fast or break.

## Other versions

The build tells the releases apart by the SHA-1 of `default.xbe`:

| Release | `default.xbe` SHA-1 | Addresses |
| --- | --- | --- |
| PAL | `2809eb147385723eaa90c425be89ee4db033fc5a` | `config/pal/` |
| USA (NTSC) | `3ec95fe3ae9e7794d83a5b489ad8583f352e0c18` | `config/us/` |

Each folder holds addresses inside that release's `default.xbe`: the seeds, the
XDK symbols and the functions the game's own fixes attach to. Any other disc,
such as the Japanese release or another revision, needs a folder of its own;
the build stops and prints its SHA-1. Please open an issue with it.

## Updating

```bat
git pull
git submodule update
py -3 scripts\build.py --relift
```

`--relift` translates the game again. Do it whenever the toolkit or `config/`
changes.

## Problems

- **"no default.xbe in ..."**: the disc contents are not in `game\`.
- **Black window, nothing happens**: read `build\Release\split2_recomp.log`.
- **A rendering bug in one place**: press F11 there and attach the `.bmp` and
  `.d3dcap` it writes to an issue.

## Legal

You need your own copy of TimeSplitters 2. Do not share `game\`, `src\recomp\`
(it is translated game code) or anything under `build\`. This repository and
xboxrecomp contain no game code or assets.
