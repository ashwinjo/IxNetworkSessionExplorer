# Design System — NOC Terminal UI

**Project:** IxNetwork Session Explorer (IxNSE)
**Status:** Approved
**Last updated:** 2026-05-09
**Authors:** Ashwin Joshi

---

## Table of Contents

1. [Summary](#summary)
2. [Background & Goals](#background--goals)
3. [Design Principles](#design-principles)
4. [Color System](#color-system)
5. [Typography](#typography)
6. [Spacing & Geometry](#spacing--geometry)
7. [Motion](#motion)
8. [Layout](#layout)
9. [Components](#components)
    - [Header](#header)
    - [Control Bar](#control-bar)
    - [Buttons](#buttons)
    - [Status Indicators](#status-indicators)
    - [Server Block (Accordion)](#server-block-accordion)
    - [Data Table](#data-table)
    - [Tags](#tags)
    - [Modals](#modals)
    - [Toast Notifications](#toast-notifications)
    - [Form Elements](#form-elements)
    - [Empty / Loading / Error States](#empty--loading--error-states)
10. [Accessibility](#accessibility)
11. [Alternatives Considered](#alternatives-considered)
12. [Open Questions](#open-questions)

---

## Summary

IxNSE uses a **NOC Terminal** (Network Operations Center) aesthetic — a fully dark, monospace-first interface that communicates operational seriousness and density. The system is intentionally spartan: no gradients on content surfaces, tight typographic scale, and a single electric-cyan accent color. Status semantics are conveyed purely through color (green / amber / crimson) with no reliance on iconography alone.

This document is the single source of truth for every visual decision in the project. Any new screen or component built for IxNSE — or any project that wants to share this design language — should derive all values from the tokens defined here.

---

## Background & Goals

Lab administrators need to triage IxNetwork sessions across many servers simultaneously. The existing workflow requires SSH-ing into each server individually — an experience that already feels terminal-native. Rather than fighting that mental model with a "modern" rounded-card web UI, we lean into it.

**Goals:**
- Feel instantly familiar to engineers who live in terminals and SSH sessions.
- Maximize information density without sacrificing readability.
- Use color semantics that are unambiguous at a glance (green = active, amber = degraded, red = dead).
- Ship an interface that looks professional enough to be left on a NOC monitor all day.

**Non-goals:**
- Light mode support (dark-only by explicit product decision).
- Mobile responsiveness (minimum viewport: 800 px wide; this is a desktop tool).
- Heavy animation or decorative illustration.

---

## Design Principles

1. **Terminal-first.** Monospace type everywhere; proportional fonts only where strictly needed for legibility (none in current implementation).
2. **Ink is cheap; color is expensive.** Neutral surfaces are near-black. Color is reserved exclusively for semantic state (cyan = interactive/selected, green = healthy, amber = degraded, crimson = error/danger).
3. **Borders, not shadows, for structure.** Depth is communicated with layered background tones and `1px` borders, not `box-shadow` blur.
4. **Text labels over icon-only controls.** Every button carries a text label. Icons are decorative companions, never the sole affordance.
5. **No layout shifts.** Loading states occupy the same spatial footprint as the content they replace.

---

## Color System

### CSS Custom Properties (Design Tokens)

All colors are declared as CSS variables on `:root`. Never hard-code a hex value outside this block.

```css
:root {
  /* ── Background layers (darkest → lightest) ─────────────────────── */
  --bg:              #05070a;   /* page background                     */
  --surface:         #0b0f14;   /* header, control bar, server headers */
  --surface-alt:     #0f1520;   /* input fields, hover targets         */
  --surface-raised:  #141a24;   /* table header, modal footer          */

  /* ── Borders ─────────────────────────────────────────────────────── */
  --border:          #1a2230;   /* default dividers                    */
  --border-med:      #243040;   /* secondary dividers, button borders  */
  --border-bright:   #2e4060;   /* hover/active borders                */

  /* ── Text ────────────────────────────────────────────────────────── */
  --text:            #dce8f0;   /* primary body copy                   */
  --text-muted:      #8baabb;   /* secondary / table cell default      */
  --text-dim:        #4a6680;   /* labels, timestamps, metadata        */
  --text-xdim:       #1e3040;   /* placeholders                        */

  /* ── Accent — Electric Cyan ──────────────────────────────────────── */
  --cyan:            #00c8e8;
  --cyan-dim:        rgba(0, 200, 232, 0.12);
  --cyan-glow:       rgba(0, 200, 232, 0.25);
  --cyan-hover:      #20d8f8;

  /* ── Status: Success / Healthy ───────────────────────────────────── */
  --green:           #00e676;
  --green-dim:       rgba(0, 230, 118, 0.10);

  /* ── Status: Warning / Degraded ─────────────────────────────────── */
  --amber:           #ffab00;
  --amber-dim:       rgba(255, 171, 0, 0.12);

  /* ── Status: Error / Danger ──────────────────────────────────────── */
  --crimson:         #ff3355;
  --crimson-dim:     rgba(255, 51, 85, 0.10);
  --crimson-hover:   #ff1a40;
}
```

### Semantic Color Usage

| Intent | Token | Hex |
|---|---|---|
| Interactive element, selection, focus | `--cyan` | `#00c8e8` |
| Active / healthy / utilized | `--green` | `#00e676` |
| Degraded / warning / on-chassis | `--amber` | `#ffab00` |
| Error / danger / kill action | `--crimson` | `#ff3355` |
| Primary text | `--text` | `#dce8f0` |
| Secondary / table body | `--text-muted` | `#8baabb` |
| Metadata, timestamps | `--text-dim` | `#4a6680` |

### Background Layer Model

```
Page (--bg)
└── Surface (--surface)          ← header, control bar, server row headers
    └── Surface Alt (--surface-alt)   ← input fields, hovered rows
        └── Surface Raised (--surface-raised) ← table <thead>, modal footer
```

Surfaces are used for visual separation without borders alone. Never skip a layer (e.g., do not place `--surface-raised` directly on `--bg`).

### Status Pill / Badge Color Mapping

| State | Text color | Border | Background |
|---|---|---|---|
| Standalone (VM) | `--cyan-hover` | `rgba(0,200,232,0.4)` | `--cyan-dim` |
| On-Chassis | `#ffc44d` | `rgba(255,193,86,0.55)` | amber gradient |
| Unreachable | `#ff6680` | `rgba(255,51,85,0.40)` | `rgba(255,51,85,0.08)` |
| Auth Failed | `#ffab40` | `rgba(255,171,64,0.45)` | `rgba(255,171,64,0.08)` |
| Unknown | `--text-dim` | `--border-med` | `rgba(74,102,128,0.08)` |

---

## Typography

### Font Stack

```css
--font-display: 'Syne Mono', 'JetBrains Mono', 'Fira Code', monospace;
--font-mono:    'JetBrains Mono', 'Fira Code', 'Consolas', monospace;
```

- **`--font-display`** — used for logotype, section headings, modal titles, and any text that needs to read as a "system label." Syne Mono's geometric letterforms give it a slightly designed quality at low weights without sacrificing monospacedness.
- **`--font-mono`** — used for all body copy, table cells, button labels, and form inputs. JetBrains Mono is the baseline; other monospace faces serve as fallbacks.

There is no proportional (sans-serif or serif) type in this system.

### Type Scale

| Role | Size (rem) | Weight | Letter-spacing | Transform |
|---|---|---|---|---|
| Page base | `0.8125rem` (13 px) | 400 | — | — |
| Logo mark | `1.3rem` | 400 | `0em` | — |
| Header title | `0.85rem` | 400 | `0.08em` | uppercase |
| Header subtitle / badge | `0.62rem` | 400 | `0.18em` | uppercase |
| Table header (`<th>`) | `0.65rem` | 700 | `0.16em` | uppercase |
| Table body (`<td>`) | `0.75rem` | 400 | — | — |
| Session name | `0.78rem` | 500 | `0.03em` | — |
| Button label | `0.75rem` | 500 | `0.04em` | — |
| Small button | `0.70rem` | 500 | `0.04em` | — |
| Modal title | `0.78rem` | 400 | `0.10em` | uppercase |
| Form label | `0.68rem` | 400 | `0.10em` | uppercase |
| Tag | `0.65rem` | 500 | `0.06em` | — |
| Timestamp / metadata | `0.72rem` | 400 | `0.04em` | — |
| Toast | `0.75rem` | 400 | `0.02em` | — |

**Rule:** `font-weight: 400` for display/label text; `500` for interactive controls and session names; `700` for table headers only.

### Line Height

- Body / table cells: `1.55`
- Modal body: `1.6`
- All other contexts: implicit (`1`)

---

## Spacing & Geometry

### Grid / Container

- Max content width: `1440px`, centered with `margin: 0 auto`
- Content padding (sides): `24px`
- Content padding (top): `20px`

### Border Radius Scale

```css
--radius-sm: 2px;   /* status icon boxes, tag chips           */
--radius:    4px;   /* buttons, inputs, toast, pills          */
--radius-lg: 6px;   /* server block cards                     */
```

Fully circular elements (heartbeat dots, live dot, link dots) use `border-radius: 50%`.

### Spacing Reference

| Context | Value |
|---|---|
| Header height | `56px` |
| Header padding (inline) | `24px` |
| Control bar padding | `8px 24px` |
| Control bar gap between groups | `12px` |
| Server block margin-bottom | `14px` |
| Server header padding | `10px 16px` |
| Table `<th>` padding | `7px 12px` |
| Table `<td>` padding | `8px 12px` |
| Button padding (default) | `5px 11px` |
| Button padding (small) | `3px 8px` |
| Modal padding (body) | `16px 20px` |
| Modal padding (footer) | `12px 20px` |
| Toast padding | `9px 14px` |
| Toast position (bottom-right) | `24px` |

---

## Motion

All transitions follow two durations:

```css
--ease:     150ms ease;   /* micro-interactions: button hover, border-color */
--ease-med: 250ms ease;   /* layout transitions: modal open/close, accordion */
```

### Specific Animations

| Element | Type | Duration | Easing |
|---|---|---|---|
| Button hover (background, border, shadow) | `transition` | `150ms` | `ease` |
| Server accordion collapse | `max-height` transition | `250ms` | `cubic-bezier(0.4, 0, 0.2, 1)` |
| Modal overlay fade-in | `opacity` transition | `250ms` | `ease` |
| Modal dialog slide-up | `translateY(-4px → 0)` | `250ms` | `ease` |
| Live dot pulse | `box-shadow` keyframe | `2.4s` | `ease` infinite |
| Spinner | `rotate(360deg)` keyframe | `0.65s` | `linear` infinite |
| Toast slide-in | `translateX(110% → 0)` keyframe | `220ms` | `cubic-bezier(0.34, 1.3, 0.64, 1)` |

**Rule:** Never animate `width`, `height`, or `top/left`. Prefer `transform` and `opacity` for GPU-composited performance.

---

## Layout

### Page Structure

```
┌─ <header> ───────────────────────────────────────── sticky, z:100 ─┐
│  Logo | Title                              Manage Servers | LIVE     │
└────────────────────────────────────────────────────────────────────┘
┌─ #control-bar ──────────────────────────────────────────────────────┐
│  › polled <timestamp> | [Refresh] [Expand] [Collapse] | [Auto] | 🔍│
└────────────────────────────────────────────────────────────────────┘
┌─ #main-content (max 1440px, centered) ──────────────────────────────┐
│  .server-block (accordion)                                          │
│    .server-header ──────────────────────────────── collapsible      │
│    .server-sessions                                                 │
│      <table class="sessions-table">                                 │
│        <thead> SESSION | CHASSIS | PORT | CP | DP | UTILIZED | ACT │
│        <tbody> [session rows with optional port sub-rows]           │
│               [.details-row with LLDP inline sub-table]             │
└────────────────────────────────────────────────────────────────────┘
```

### Z-Index Stack

| Layer | z-index |
|---|---|
| Page content | `0` |
| Sticky header | `100` |
| Modal overlays | `1000` |
| Toast container | `2000` |

---

## Components

### Header

**Structure:** `position: sticky; top: 0` — always visible.

- **Top accent line:** `2px` linear gradient (`transparent → --cyan → transparent`) at 60% opacity. Conveys "live system" without being loud.
- **Logo:** `<span class="logo-ix">Ix</span><span class="logo-se">NSE</span>` — `--cyan` / `--text-muted` split. Font: `--font-display` at `1.3rem`.
- **Vertical divider:** `1px` × `24px`, color `--border-med`, separates logo from title group.
- **Title group:** Primary label uppercase at `0.85rem`; sub-label at `0.62rem` / `0.18em` letter-spacing / `--text-dim`.
- **Live badge:** `border: 1px solid rgba(0,230,118,0.25)`, `background: rgba(0,230,118,0.05)`. Contains an animated pulse dot (`--green`) + "LIVE" in `--font-display`.

---

### Control Bar

Sits below the header. Background `--surface`, `border-bottom: 1px solid --border`.

- **Prompt chevron:** `›` in `--cyan` at 70% opacity — pure aesthetic, reinforces terminal feel.
- **Poll timestamp:** `font-size: 0.72rem; color: --text-dim`. The timestamp value itself is `--text-muted`.
- **Separator:** `1px × 18px` at `--border-med`.
- **Search input:** right-aligned via `margin-left: auto`. Width `220px`. See [Form Elements](#form-elements).

---

### Buttons

All buttons share the `.btn` base class.

```
Base: display:inline-flex; align-items:center; gap:5px;
      padding:5px 11px; border:1px solid transparent;
      border-radius:var(--radius); font-family:var(--font-mono);
      font-size:0.75rem; font-weight:500; letter-spacing:0.04em;
      transition: [background, border-color, box-shadow, opacity] 150ms ease;
Disabled: opacity:0.35; cursor:not-allowed;
```

#### Variants

| Class | Resting | Hover |
|---|---|---|
| `.btn-primary` | bg: `--cyan-dim`, border: `rgba(0,200,232,0.35)`, text: `--cyan` | bg: `rgba(0,200,232,0.18)`, border: `--cyan`, shadow: `0 0 10px --cyan-glow` |
| `.btn-neutral` | bg: transparent, border: `--border-med`, text: `--text-muted` | bg: `--surface-raised`, border: `--border-bright`, text: `--text` |
| `.btn-danger` | bg: `--crimson-dim`, border: `rgba(255,51,85,0.35)`, text: `--crimson` | bg: `rgba(255,51,85,0.18)`, border: `--crimson`, shadow: `0 0 10px rgba(255,51,85,0.2)` |
| `.btn-toggle` | bg: transparent, border: `--border-med`, text: `--text-dim` + grey pip | Active state: bg `--green-dim`, border `rgba(0,230,118,0.3)`, text `--green`, pip glows green |

#### Row-level Action Buttons

Smaller controls (`padding: 3px 8px; font-size: 0.7rem`) placed inside table action cells:

| Class | Hover color |
|---|---|
| `.btn-details` | `--cyan` |
| `.btn-tag` | `--amber` |
| `.btn-logs` | `--cyan` |
| `.btn-kill` | `--crimson` |

All row-level buttons rest with `border: 1px solid --border-med; color: --text-muted` and only pick up their semantic color on hover.

#### Button Icons

SVG icons (`width: 12px; height: 12px; flex-shrink: 0`) are placed before the label. Stroke-based, `stroke-width: 1.8`, `stroke-linecap: round`, `stroke-linejoin: round`. Color inherits from parent button.

---

### Status Indicators

#### CP / DP Plane Cells

18×18 px square with `border-radius: --radius-sm`:

```
Active   → bg: rgba(0,230,118,0.12), border: rgba(0,230,118,0.25), text: --green,   content: ✓
Inactive → bg: rgba(255,51,85,0.10), border: rgba(255,51,85,0.30), text: --crimson, content: ✗
```

#### Utilized Badge

`min-width: 50px; padding: 2px 8px; border-radius: --radius; font-family: --font-display; font-size: 0.62rem; letter-spacing: 0.1em; font-weight: 600`

```
YES → bg: rgba(0,230,118,0.10), border: rgba(0,230,118,0.3),  text: --green,    shadow: 0 0 8px rgba(0,230,118,0.08)
NO  → bg: transparent,           border: --border,             text: --text-dim
```

#### Heartbeat Dots (Server-level)

`10×10 px`, `border-radius: 50%`:

```
Green  → #22c55e, glow: 0 0 8px rgba(34,197,94,0.45)
Yellow → #ca8a04, glow: 0 0 6px rgba(234,179,8,0.35)
Red    → #dc2626, glow: 0 0 6px rgba(239,68,68,0.40)
```

#### Link-state Dots (Port-level)

`6×6 px`, `border-radius: 50%`, displayed inline next to port numbers:

```
link-up      → --green,    glow: 0 0 5px rgba(0,230,118,0.5)
link-down    → --amber,    glow: 0 0 5px rgba(255,171,0,0.5)
link-none    → --text-dim
link-unknown → --text-xdim
```

---

### Server Block (Accordion)

```
border: 1px solid --border
border-left: 3px solid --border-bright   ← thicker left accent
border-radius: --radius-lg
overflow: hidden
```

On hover the left accent transitions to `rgba(0,200,232,0.4)`.

**Collapsed state:** CSS class `.collapsed` sets `max-height: 0` on `.server-sessions` and rotates the toggle chevron `-90deg`.

**Server header row:** `background: --surface; padding: 10px 16px`. Contains (left to right):
1. Toggle chevron (`▾`)
2. Heartbeat dot
3. Server name (`--font-display`, uppercase, `0.82rem`)
4. Host in parentheses (`--font-mono`, `--text-dim`, `0.72rem`)
5. Deployment pill (see Status Pill table above)
6. IxNetwork version pill (`--surface-raised` bg, rounded, `0.64rem`)
7. Session count pill (right-aligned via `margin-left: auto`)
8. "Console ↗" link button (`--cyan`, opens new tab)

---

### Data Table

```css
.sessions-table {
  width: 100%;
  border-collapse: collapse;
  font-size: 0.75rem;
}
```

**Header row:** `background: --surface-raised; border-bottom: 1px solid --border-med`.
`<th>`: `color: rgba(0,200,232,0.65); font-size: 0.65rem; letter-spacing: 0.16em; text-transform: uppercase; font-weight: 700`.

**Body rows:** `border-bottom: 1px solid --border`. On hover: `background: rgba(255,255,255,0.015); color: --text`.

**Multi-port sessions:** A session with N ports spans N rows. The SESSION, CP, DP, UTILIZED, and ACTIONS cells use `rowspan="N"` on the first row only. Sub-rows carry only the CHASSIS and PORT cells.

**Inline details row:** `.details-row` — a full-width row with `background: rgba(0,200,232,0.03); border-top: 1px solid rgba(0,200,232,0.12); border-bottom: 2px solid --border-med`. Contains a nested `.details-table` with LLDP peer data indented `44px` from the left edge.

#### Column Widths

| Column | Width |
|---|---|
| SESSION | min `160px`, `vertical-align: top` |
| CHASSIS | min `120px` |
| PORT | min `80px` |
| CP | `46px`, centered |
| DP | `46px`, centered |
| UTILIZED | `72px`, centered |
| ACTIONS | `120px`, `white-space: nowrap` |

---

### Tags

```css
.tag {
  background: rgba(255, 171, 0, 0.12);
  border: 1px solid rgba(255, 171, 0, 0.4);
  border-radius: var(--radius-sm);       /* 2px */
  color: var(--amber);
  font-size: 0.65rem;
  padding: 1px 7px;
  font-family: var(--font-mono);
  letter-spacing: 0.06em;
  font-weight: 500;
  box-shadow: 0 0 6px rgba(255, 171, 0, 0.08);
}
```

Tags are displayed in a `.tag-list` (`display:flex; flex-wrap:wrap; gap:4px; margin-top:5px`) below the session name.

---

### Modals

**Overlay:** `position:fixed; inset:0; background: rgba(2,5,10,0.8); backdrop-filter: blur(4px)`. Visible via `.visible` class (opacity + pointer-events transition).

**Dialog box:**
```
background: --surface
border: 1px solid --border-med
border-top: 2px solid --cyan      ← colored top accent
border-radius: --radius-lg
box-shadow: 0 20px 60px rgba(0,0,0,0.7), 0 0 40px rgba(0,200,232,0.04)
```

On open: dialog slides from `translateY(-4px)` to `translateY(0)` in `250ms`.

**Danger modals** (kill session, delete server): `border-top-color: --crimson`. Modal title uses `color: --crimson`.

**Sections:**
- **Title bar:** `padding: 16px 20px; border-bottom: 1px solid --border`. Font: `--font-display`, `0.78rem`, uppercase, `0.10em` letter-spacing.
- **Body:** `padding: 16px 20px; font-size: 0.80rem; line-height: 1.6; color: --text-muted`.
- **Footer:** `padding: 12px 20px; border-top: 1px solid --border; background: rgba(0,0,0,0.2)`. Right-aligned flex row of buttons.

**Modal widths:**
- Default: `min-width: 360px; max-width: 520px; width: 90vw`
- Wide (`.modal--wide`): `max-width: 700px`

**Closing:** Overlay click, Escape key, or explicit cancel/close button — all close the modal. Focus is trapped to the dialog when open.

---

### Toast Notifications

```
position: fixed; bottom: 24px; right: 24px
flex-direction: column-reverse; gap: 6px; z-index: 2000
```

Individual toast:
```
background: --surface-raised
border: 1px solid --border-med
border-left: 3px solid <semantic color>
border-radius: --radius
padding: 9px 14px
font-size: 0.75rem; font-family: --font-mono
box-shadow: 0 8px 24px rgba(0,0,0,0.5)
max-width: 340px
```

| Variant | Left border color | Text color |
|---|---|---|
| Default | `--border-bright` | `--text-muted` |
| `.toast-ok` | `--green` | `rgba(0,230,118,0.85)` |
| `.toast-error` | `--crimson` | `rgba(255,120,140,0.9)` |

Toasts auto-dismiss after 5 seconds. Entry animation: `translateX(110% → 0)` in `220ms` with a slight overshoot (`cubic-bezier(0.34, 1.3, 0.64, 1)`).

---

### Form Elements

All inputs share:
```css
background: var(--surface-alt);
border: 1px solid var(--border-med);
border-radius: var(--radius);
color: var(--text);
font-family: var(--font-mono);
font-size: 0.80rem;           /* 0.75rem for search input */
padding: 8px 12px;
outline: none;
letter-spacing: 0.03em;
transition: border-color 150ms ease, box-shadow 150ms ease;
```

**Focus state:**
```css
border-color: rgba(0, 200, 232, 0.5);
box-shadow: 0 0 0 3px rgba(0, 200, 232, 0.06);
```

**Placeholder:** `color: --text-xdim`

**Disabled:** `opacity: 0.45; cursor: not-allowed`

**Form labels:** `.modal-label` — `font-family: --font-display; font-size: 0.68rem; letter-spacing: 0.10em; text-transform: uppercase; color: --text-dim; margin-bottom: 6px`.

**Error banners (inline):** `.modal-error` —
```
background: rgba(255,51,85,0.07)
border: 1px solid rgba(255,51,85,0.25)
border-radius: --radius
color: rgba(255,120,140,0.9)
font-size: 0.73rem; font-family: --font-mono
padding: 7px 12px
```

**Password field:** standard input with a `.btn-pw-toggle` overlaid at `right: 8px` — SVG eye icon, `color: --text-dim` resting, `--text-muted` on hover.

**Textarea:** Inherits from `.modal-input`, adds `resize: vertical; line-height: 1.7`.

---

### Empty / Loading / Error States

All three share the same container treatment:
```
padding: 56px 24px; text-align: center;
font-size: 0.82rem; font-family: --font-mono; letter-spacing: 0.04em;
```

| State | Text color | Extra |
|---|---|---|
| Loading | `--text-dim` | Spinner: `14px` circle, `border-top: 1.5px solid --cyan`, `0.65s linear infinite` |
| Empty | `--text-dim` | Plain text message |
| Error | `--crimson` | Plain text message |

---

## Accessibility

- All interactive elements are reachable by keyboard (Tab order follows visual order).
- Server accordion headers expose `role="button"`, `tabindex="0"`, `aria-expanded`, and `aria-controls`.
- Modal overlays use `role="dialog"`, `aria-modal="true"`, and `aria-labelledby` pointing to the title element. Focus is moved into the dialog on open.
- `aria-live="polite"` on the toast container announces new notifications to screen readers.
- Status cells carry `aria-label` (e.g., `aria-label="Active"` / `aria-label="Inactive"`).
- Heartbeat dots include `role="img"` and `aria-label` with their current health state.
- `.sr-only` utility class (absolute positioned, clipped, 1×1 px) is used for visually-hidden labels (e.g., search input label).
- Color alone is never the sole distinction between states — each status always has a distinct icon or text label in addition to color.
- Selection controls use `accent-color: --cyan`.
- Minimum contrast: `--text` on `--bg` exceeds WCAG AA for body text.

---

## Alternatives Considered

### Light / dual-mode theme

**Rejected.** The tool is purpose-built for NOC-room monitors (often high-brightness screens in dark rooms) and for engineers who use dark terminal environments all day. A light mode would require a second full color token set and substantially more QA surface. The product decision is dark-only.

### Card-based layout (Material-style)

**Rejected.** Rounded cards with drop shadows communicate a consumer product aesthetic. The NOC Terminal aesthetic immediately signals "this is an operational tool" and reduces the cognitive overhead of context-switching from a terminal session.

### Icon-only action buttons (no text labels)

**Rejected.** Lab administrators may be unfamiliar with which icon means "kill session" vs. "view logs." Text labels are unambiguous and satisfy WCAG 2.5.3 (Label in Name).

### Proportional sans-serif type

**Rejected.** Monospace type ensures alignment of IP addresses, port numbers, and session IDs without any extra CSS. It also reinforces the NOC Terminal visual concept.

---

## Open Questions

| # | Question | Owner | Status |
|---|---|---|---|
| 1 | Should the "Auto-refresh" interval be user-configurable via a UI control? | Ashwin | Open |
| 2 | Port-level CP/DP status is derived client-side from port objects. Should this become a first-class API field? | Backend | Open |
| 3 | When a session has 10+ ports, the row group becomes very tall. Should port rows be truncated with a "show more" control? | Design | Open |
