# Orb Redesign: Theme Engine + Archetypes - Design

**Date:** 2026-07-16
**Status:** Draft - awaiting user review
**Repo:** laris (frontend/ + overlay_app.py + server endpoint)
**Phase:** 3 of the LARIS/MIRIS roadmap (phase 2 = menu bar app consumes what this ships)

## What

Replace the current hardcoded JARVIS-ish orb (generic wireframe sphere, noisy
rings, cyan-to-pink shift, organic wobble - diagnosed by the user as "all four
wrong") with a **theme engine**: archetype (form + motion) x palette (single
accent + hot highlight), plus configurable screen position. Validated live with
the user via browser mockups and a real transparent-panel desktop preview.

## Decisions (all validated live on 2026-07-16)

| Decision | Choice | Why |
|----------|--------|-----|
| Default archetype | **Waveform** - circular spectrum analyzer: hot core, radial bars with ghost afterglow, dashed tech ring, thin outer ring, rare glitch tic (~every 4-8s). NO radar sweep (user rejected it) | Picked over Reactor (concentric HUD arcs) and Faceted (rigid lit plates) from three live candidates; "the voice IS the interface" |
| Other archetypes | **Reactor** and **Faceted** ship as selectable archetypes (prototypes already validated on screen 2) | "variantes com que as pessoas se identifiquem" |
| Palettes | 4 per archetype, `{accent, hot}`: **Blade** (default) #3fb6c4/#d8f4f7, **Neon Noir** #c94f92/#f7d8ea, **Acid** #79c94f/#e9f7d8, **Ember** #cf9b3a/#f7ecd8. Single desaturated accent + hot highlight; hierarchy by brightness, never by hue | Mature/cyberpunk profile; kills the cotton-candy cyan-to-pink |
| Motion rules | Mesh deformation FORBIDDEN. Mechanical motion only: constant rotations, brightness, snaps. Keep from current code: VU ballistics (fast attack / slow release), activation pulse, idle frame-skip | The wobble read as "gosma"; these rules are the antidote to "esquisito" |
| Size / position default | **190px, screen center** | User iterated 120 -> 150 -> 190 on live desktop preview; center felt right |
| Position config | `position` presets: `top-left, top-center, top-right, bottom-left, bottom-right, center` + `custom: [x, y]` | User freedom; picker lands in the phase-2 menu bar |
| Visibility semantics | UNCHANGED from current laris: the panel only shows while PTT is held or hands-free is on (daemon-driven show/hide). The orb's dim state = "listening, momentary silence" and stays present (75% intensity), not near-invisible | Orb is an "I'm listening" indicator, not a permanent desktop widget - so presence wins |
| Rendering tech | Waveform + Reactor: pure 2D canvas. Faceted: three.js (only archetype that needs it) | 2D canvas is lighter than three.js for an all-day daemon |
| Config + API | `~/.config/voice-at/orb-theme.json` `{archetype, palette, position, size}`; overlay server gains `GET /theme` + `POST /theme` (auth token as existing endpoints); overlay_app repositions/resizes live on POST | This endpoint is the contract the phase-2 menu bar consumes |
| Dev harness | `?demo=1` on the overlay page = fake-voice driver (idle/speaking cycle + glitch scheduler), no daemon needed | It's how every mockup was built; becomes the official visual smoke tool |

## Architecture

```
laris/frontend/
  voice-orb.js        # becomes the engine: shared driver (ballistics, pulse,
                      #   glitch scheduler, demo mode) + THEMES registry
  themes/waveform.js  # draw(ctx, state, palette) - default
  themes/reactor.js   # draw(ctx, state, palette)
  themes/faceted.js   # three.js scene, same state contract
  voice-orb.css       # unchanged except size var
laris/
  server.py           # + GET/POST /theme (reads/writes orb-theme.json,
                      #   pushes theme over the existing /ws/voice socket)
  overlay_app.py      # position/size from orb-theme.json at boot;
                      #   "reposition x y w" stdin command for live moves
  config.py           # + ORB_THEME_PATH
```

State contract every theme receives per frame:
`{ t, active, v (0..1 smoothed+pulse), glitch (bool), phase (caption key) }`.
Palette contract: `{ accent, hot }` hex pair. A theme never reads the
websocket or config directly - the engine feeds it. Adding archetype #4 =
one new file registered in THEMES.

Transparent-canvas constraint (WKWebView): no opaque clears, no translucent
full-canvas fills for trails - afterglow is done with stored ghost band
snapshots, already proven in the mockups.

## Error handling

- Missing/corrupt orb-theme.json -> defaults (waveform/blade/center/190) and
  rewrite the file.
- Unknown archetype/palette in POST /theme -> 422, list valid options.
- three.js load failure (Faceted only) -> engine falls back to Waveform.

## Testing / validation

- pytest (laris suite): /theme endpoint GET/POST roundtrip, validation errors,
  config file creation/defaults, overlay_app rect math for every preset
  (pure function extracted as `position_rect(preset, custom, size, screen)`).
- Frontend has no JS test infra (house pattern) - visual validation via
  `?demo=1` in a plain browser tab + the desktop preview panel.
- Mockup lineage for reference: `.superpowers/brainstorm/75670-1784247156/content/`
  (waveform-cyberpunk-v2.html = approved look, orb-desktop-live-v3.html =
  approved size/brightness/position).

## Out of scope

- Menu bar app (phase 2: consumes GET/POST /theme; ships the theme/position picker)
- Drag-to-move (click-through panel would need a "move mode"; presets + custom cover it)
- MIRIS state on the orb (recording indicator lives in the phase-2 menu bar icon)
- New palettes/archetypes beyond the 3x4 set
