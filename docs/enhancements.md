# Enhancements: what is done and what is next

Tracking list for TimeSplitters 2. Each candidate has an estimate and a
split: **toolkit** work goes in xboxrecomp and every title gets it;
**TS2** work is this repository. The general list, and the reasoning behind
the split, is in `xboxrecomp/docs/technical/xbox-game-enhancements.md`.

Estimates are working time; calendar time will be longer. They date from
30 September 2026.

## Done

| Enhancement | Where | Notes |
| --- | --- | --- |
| Widescreen (16:9) | Both | Camera widened where the game builds it (culling agrees); front end, HUD and Arcade screens laid out for 16:9 by call site. `RECOMP_TS2_MENUS=43` brings back the 4:3 front end. |
| Internal resolution | Toolkit | `RECOMP_RES_SCALE=1..8` |
| Vulkan renderer | Toolkit | `RECOMP_D3D8_BACKEND=vulkan`. Needs `third_party/dxc` (the DXC GitHub release) for the build |
| Launcher mouse input | Toolkit | Arrow hit boxes match what is drawn (xboxrecomp #24) |
| Variable refresh rate | Toolkit | Borderless fullscreen (Alt+Enter), VRR presents on both renderers; launcher rows Fullscreen and Variable refresh rate (xboxrecomp #29) |
| Frame interpolation | Both | `frame_interp = 2..4` (launcher row): 120+ frames a second shown while the game runs at 60. TS2 names its matrix registers (c60 projection, c64-c75 model-view and bones) in `src/recomp_manual.c`. See below |

### Widescreen leftovers

- Not yet surveyed, so still on the renderer's width guess: Challenge,
  MapMaker, Options, end-of-level results, split screen.
- Story HUD sites not yet in the table (pickup and objective messages,
  single-weapon extras): `000E4888` and its neighbours, `000C47C1`,
  `000C480A`, `000AA5AD`.
- On the story screens the panel glow's rays end at the old right edge.
  Needs an "extend to the edge" placement in the toolkit.
- Vulkan has not been checked in play; the scripted runs do not reach it.

### Frame interpolation leftovers

- Snow and other particles the CPU positions step at 60 among 120.
- A 144 Hz display needs VRR for even pacing; a render thread would serve
  fixed refresh rates (toolkit, 3-4 weeks).
- Not yet checked: the first-person weapon and muzzle flashes while
  firing, guards animating (the bone matrices), the pause menu, a death.
- Measurements and how it works:
  `xboxrecomp/docs/technical/frame-interpolation.md`.

How to survey a screen: F11 with `RECOMP_TS2_UI_SITES=1` set, then
`d3d8_replay --each-tag` / `--each-tag-hidden` on the capture and
`--place <site>=<placement>` to try a placement before it goes into
`src/recomp_manual.c`.

## Candidates

| Enhancement | Toolkit | TS2 | Total | Confidence |
| --- | --- | --- | --- | --- |
| [Netplay (System Link)](#netplay-system-link) | 2–4 weeks | 1–2 weeks | 3–8 weeks, by reach | Low to medium |
| [Modern controller icons](#modern-controller-icons) | 2–3 weeks | ~1 week | 3–4 weeks (first milestone 1.5–2) | High to medium |
| [Native mouselook](#native-mouselook) | 1–2 weeks | 2–4 weeks | 3–6 weeks (+2–3 for mouse menus) | Medium to low |
| Widescreen leftovers (above) | Days | 1–2 weeks | 1–2 weeks | High |

Two of these share groundwork: the controller icons need texture
replacement by content hash, which is also the first step for texture mods.
Netplay is more robust with the frame-rate work's fixed 60 Hz tick.

---

### Netplay (System Link)

TS2 has System Link (LAN) and no Xbox Live. The plan is to emulate the
network card in the toolkit so the game's own network code runs unchanged.
Full plan in [multiplayer.md](multiplayer.md).

| Reach | Estimate |
| --- | --- |
| LAN: two copies on one PC or one network | 3–5 weeks |
| Internet through XLink Kai | 4–6 weeks |
| Internet through our own server | 5–8 weeks |

The largest unknown is TS2's bring-up: its network code has never run under
the recompiler. Every copy of the toolkit reports the same MAC address today,
which has to change first.

### Modern controller icons

Replace the game's Xbox button icons with the matching modern set for the
pad in use: Xbox Series, PlayStation, Switch.

How TS2 draws them: each button is its own 32x32 texture (B, A, Y, X in
`textures/misc/xbstdbutton1-4.xbt`), plus a 128x64 atlas with Start, Back
and arrows. Every menu and dialog prompt is text with an inline icon code,
so about 560 strings in five languages go through those four textures. The
textures are byte-identical in every level pak, so one content hash
identifies each.

Approach: toolkit texture replacement by content hash, one replacement set
per pad family, following the pad used last (SDL3 gives its type). TS2
supplies a small manifest (hash → button, atlas layout).

| Scope | Toolkit | TS2 |
| --- | --- | --- |
| **First milestone:** Xbox Series and PlayStation, chosen by a setting | 4–6 days | 2–3 days |
| Full: live switching, Switch, the atlas, launcher text, follows bindings | 10.5–16 days | 3.5–6 days |
| Optional: per-player icons in split screen | 2–4 days | 1–2 days |
| Optional: controller-picture screens; button names written in text | – | 4–7 days (low confidence) |

To decide: the art (Kenney's Input Prompts are CC0 and cover all three;
CC0 waives copyright, not trademark, so whether glyph art ships in the repo
is a maintainer's call). Icons must follow the button's position and the
player's bindings, not the letter printed on it: a Switch pad's bottom button
reads "B" and acts as the game's A.

### Native mouselook

The toolkit has no mouse input today.

| Step | Where | Estimate |
| --- | --- | --- |
| Mouse input: raw input, cursor lock in game and release in menus and on alt-tab, sensitivity and invert, mouse buttons and wheel as bindable controls, launcher UI | Toolkit | 1–2 weeks |
| Find TS2's view angles and where stick input becomes turn rate (the in-game camera, `sub_00032DC0` / `0x4B2CA0` in PAL and `sub_00032D90` / `0x4B2F60` in USA, is the starting point) | TS2 | 1–2 weeks |
| Apply the mouse to the view angles directly: pitch limits; auto-aim, look-spring and aim smoothing off for the mouse | TS2 | 3–5 days |
| Edge cases: aim mode, scope zoom, turrets, cutscenes and pause, respawn, split screen (player 1 only) | TS2 | 1–2 weeks |
| Optional: clicking TS2's menus with the mouse | TS2 | 2–3 weeks |

A cheaper option, the mouse as a virtual right stick (1–2 weeks, toolkit
only), does not feel like mouselook: the game's stick acceleration, dead
zone and top turn speed still apply.

## Not estimated yet

- **Cutscene skip:** find where in-engine cutscenes start and whether the
  game already has a skip.
- **Texture mods:** naming dumped textures by pak entry; shares the
  replacement work with the controller icons.
- **MSAA and filters:** toolkit work; TS2 only needs exceptions for passes
  that break.
