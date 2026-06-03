# Keysight Theme System — Dark & Day Modes

**Source project:** IxNetwork Session Explorer (IxNSE)
**Last updated:** 2026-05-18
**Purpose:** Portable reference for replicating this visual language in a new portal.

---

## Table of Contents

1. [Design Philosophy](#design-philosophy)
2. [Brand Palette](#brand-palette)
3. [Token Architecture](#token-architecture)
4. [Dark Mode Tokens](#dark-mode-tokens)
5. [Day Mode Tokens](#day-mode-tokens)
6. [Theme Invariants](#theme-invariants)
7. [Semantic Color Mapping](#semantic-color-mapping)
8. [Typography](#typography)
9. [Geometry & Spacing](#geometry--spacing)
10. [Component Patterns](#component-patterns)
11. [Implementing Dual-Theme in a New Project](#implementing-dual-theme-in-a-new-project)
12. [Anti-Patterns to Avoid](#anti-patterns-to-avoid)

---

## Design Philosophy

This system is a **NOC Terminal** aesthetic with a **Keysight enterprise veneer** applied in day mode. Two rules govern every decision:

1. **Color is semantic, not decorative.** Cyan/Red = interactive. Green = healthy. Amber = degraded. Crimson = danger. No exceptions — never use a status color for decorative purposes.
2. **Theme switching is a token swap.** All component styles reference CSS custom properties only. The theme layer (`:root` vs `body[data-theme="day"]`) is the only place hex values appear.

The surface layer model is the same in both modes. Only the luminosity flips (dark → light). The header is **always dark purple** — it never participates in the theme swap. This is the primary brand anchor.

---

## Brand Palette

Keysight Technologies' official colors used directly:

| Name | Hex | Role |
|---|---|---|
| Keysight Red | `#E90029` | Primary interactive (day mode accent) |
| Keysight Purple | `#291B44` | Header background — pinned in both modes |
| Keysight Purple Dark | `#3d2860` | Header border |
| Keysight Gray | `#524F56` | Muted body text (day mode `--text-muted`) |
| Keysight Yellow | `#FFA623` | Warning / degraded (maps to `--amber`) |
| Keysight Dark Blue | `#225792` | Table header text (day mode only) |
| Keysight Teal | `#07858b` | KCOS deployment chip; toast success (day mode only) |

These brand colors are only ever applied in the day mode override block or as hardcoded values on the pinned header. They never appear in dark mode.

---

## Token Architecture

Both themes share **identical CSS variable names**. Components are written once against the token names. The theme layer reassigns the values.

```
:root { ... }                      ← dark mode (default)
body[data-theme="day"] { ... }     ← day mode overrides
```

### Token Groups

| Group | Variables | Purpose |
|---|---|---|
| Surfaces | `--bg`, `--surface`, `--surface-alt`, `--surface-raised`, `--surface-hover` | Background layering |
| Borders | `--border`, `--border-med`, `--border-bright`, `--border-focus` | Dividers and interactive outlines |
| Text | `--text`, `--text-muted`, `--text-dim`, `--text-xdim` | Content hierarchy |
| Accent | `--cyan`, `--cyan-dim`, `--cyan-glow`, `--cyan-hover` | Primary interactive color (electric cyan in dark, Keysight Red in day) |
| Status | `--green`, `--green-dim`, `--green-border` | Healthy / active |
| Warning | `--amber`, `--amber-dim`, `--amber-border` | Degraded / warning |
| Danger | `--crimson`, `--crimson-dim`, `--crimson-hover` | Error / destructive |
| Typography | `--font-ui`, `--font-mono` | Font stacks |
| Geometry | `--radius-sm`, `--radius`, `--radius-lg`, `--radius-xl` | Border radii |
| Motion | `--ease`, `--ease-med`, `--ease-spring` | Transition timing |
| Toast | `--toast-ok-text`, `--toast-error-text` | Toast variant text colors |

> **Rule:** If a component needs a color, it picks a token from this list. If no token fits, a new token is added to the list — never a hardcoded hex in the component.

---

## Dark Mode Tokens

Default theme. Applied on `:root`. The NOC Terminal aesthetic — near-black surfaces, cool blue-grey text, electric cyan accent.

```css
:root {
  /* ── Surfaces (darkest → lightest) ───────────────────────────────── */
  --bg:              #04060d;   /* page canvas                         */
  --surface:         #080c15;   /* header, control bar, server headers */
  --surface-alt:     #0c1120;   /* inputs, dropdown backgrounds        */
  --surface-raised:  #111827;   /* table <thead>, modal footer         */
  --surface-hover:   #141d2e;   /* row hover                           */

  /* ── Borders ─────────────────────────────────────────────────────── */
  --border:          #161f30;   /* default row dividers                */
  --border-med:      #1e2d42;   /* button borders, secondary dividers  */
  --border-bright:   #2a3f5c;   /* hover/active borders, card accent   */
  --border-focus:    rgba(0, 200, 232, 0.50);

  /* ── Text ────────────────────────────────────────────────────────── */
  --text:            #e2eaf4;   /* primary body copy                   */
  --text-muted:      #8da8c0;   /* table cells, secondary labels       */
  --text-dim:        #4a6478;   /* metadata, timestamps, form labels   */
  --text-xdim:       #1e3040;   /* placeholders                        */

  /* ── Accent — Electric Cyan ──────────────────────────────────────── */
  --cyan:            #00c8e8;
  --cyan-dim:        rgba(0, 200, 232, 0.08);
  --cyan-glow:       rgba(0, 200, 232, 0.20);
  --cyan-hover:      #22d4f0;

  /* ── Status: Healthy ─────────────────────────────────────────────── */
  --green:           #00e676;
  --green-dim:       rgba(0, 230, 118, 0.08);
  --green-border:    rgba(0, 230, 118, 0.25);

  /* ── Status: Warning ─────────────────────────────────────────────── */
  --amber:           #f59e0b;
  --amber-dim:       rgba(245, 158, 11, 0.08);
  --amber-border:    rgba(245, 158, 11, 0.30);

  /* ── Status: Danger ──────────────────────────────────────────────── */
  --crimson:         #f43f5e;
  --crimson-dim:     rgba(244, 63, 94, 0.08);
  --crimson-hover:   #fb5573;

  /* ── Typography ──────────────────────────────────────────────────── */
  --font-ui:         'Inter', system-ui, -apple-system, sans-serif;
  --font-mono:       'JetBrains Mono', 'Fira Code', 'Consolas', monospace;

  /* ── Geometry ────────────────────────────────────────────────────── */
  --radius-sm:       3px;
  --radius:          6px;
  --radius-lg:       8px;
  --radius-xl:       12px;

  /* ── Motion ──────────────────────────────────────────────────────── */
  --ease:            150ms ease;
  --ease-med:        220ms ease;
  --ease-spring:     250ms cubic-bezier(0.34, 1.3, 0.64, 1);

  /* ── Toast text ──────────────────────────────────────────────────── */
  --toast-ok-text:    rgba(0, 230, 118, 0.85);
  --toast-error-text: rgba(255, 130, 150, 0.90);
}
```

### Dark Mode — Surface Layer Visualization

```
--bg              #04060d   ← page canvas
  --surface         #080c15   ← header / control bar / server card headers
    --surface-alt     #0c1120   ← inputs / dropdown BG
      --surface-raised  #111827   ← table thead / modal footer
        --surface-hover   #141d2e   ← row hover
```

Never skip a layer. Do not place `--surface-raised` directly on `--bg` — the jump is too harsh.

---

## Day Mode Tokens

Activated by `body[data-theme="day"]`. Overrides surface, border, text, and accent tokens only. Typography, geometry, and motion are unchanged.

```css
body[data-theme="day"] {
  color-scheme: light;

  /* ── Surfaces ────────────────────────────────────────────────────── */
  --bg:              #F4F2F7;   /* warm-purple tinted white             */
  --surface:         #FFFFFF;
  --surface-alt:     #EDE9F4;
  --surface-raised:  #E4E0EE;
  --surface-hover:   #E9E5F2;

  /* ── Borders ─────────────────────────────────────────────────────── */
  --border:          #D5D0E0;
  --border-med:      #BDB8CC;
  --border-bright:   #9A94AD;
  --border-focus:    rgba(233, 0, 41, 0.50);

  /* ── Text ────────────────────────────────────────────────────────── */
  --text:            #1A1528;   /* near-black with purple undertone     */
  --text-muted:      #524F56;   /* Keysight Gray                        */
  --text-dim:        #7B768A;
  --text-xdim:       #C0BBCC;

  /* ── Accent — Keysight Red replaces Electric Cyan ────────────────── */
  --cyan:            #E90029;
  --cyan-dim:        rgba(233, 0, 41, 0.08);
  --cyan-glow:       rgba(233, 0, 41, 0.18);
  --cyan-hover:      #FF1A3D;

  /* ── Status: Healthy — darker green for light bg legibility ─────── */
  --green:           #00875A;
  --green-dim:       rgba(0, 135, 90, 0.10);
  --green-border:    rgba(0, 135, 90, 0.28);

  /* ── Status: Warning ─────────────────────────────────────────────── */
  --amber:           #D4870A;
  --amber-dim:       rgba(212, 135, 10, 0.10);
  --amber-border:    rgba(212, 135, 10, 0.32);

  /* ── Status: Danger ──────────────────────────────────────────────── */
  --crimson:         #B5001F;
  --crimson-dim:     rgba(181, 0, 31, 0.08);
  --crimson-hover:   #D4002A;

  /* ── Toast ───────────────────────────────────────────────────────── */
  --toast-ok-text:    #07858b;   /* Keysight Teal                       */
  --toast-error-text: #871518;   /* Dark Red                            */
}
```

### Day Mode — Body Background

The page background uses a subtle radial gradient to prevent the pure white feel and maintain the purple brand warmth:

```css
body[data-theme="day"] {
  background-image:
    radial-gradient(ellipse 80% 40% at 10% -10%, rgba(41, 27, 68, 0.04) 0%, transparent 60%),
    radial-gradient(ellipse 60% 40% at 90% 110%, rgba(233, 0, 41, 0.03) 0%, transparent 60%);
}
```

Top-left: faint purple bloom (brand warmth). Bottom-right: faint red bloom (accent echo). Both are imperceptible at a glance but prevent the UI from reading as a generic white app.

### Day Mode — Surface Layer Visualization

```
--bg              #F4F2F7   ← page canvas (warm purple-white)
  --surface         #FFFFFF   ← cards, panels
    --surface-alt     #EDE9F4   ← inputs
      --surface-raised  #E4E0EE   ← table thead / modal footer
        --surface-hover   #E9E5F2   ← row hover
```

---

## Theme Invariants

These elements **do not change between themes**. They are hardcoded rather than tokenized.

### Pinned Dark Header

The `<header>` is always `#291B44` (Keysight Dark Purple) regardless of theme. It is the single constant visual anchor that makes the UI feel "Keysight" in both modes.

```css
/* Applied in both :root (inherited) and explicitly in day mode */
body[data-theme="day"] header {
  background: #291B44;
  border-bottom-color: #3d2860;
}
```

**Text on dark purple header** always uses white-based opacity values — never `--text` tokens — because the header surface never participates in theme switching:

| Element | Color |
|---|---|
| Logo "Ix" | `#E90029` (Keysight Red) — same in both modes |
| Logo "NSE" | `rgba(255,255,255,0.55)` |
| Title h1 | `rgba(255,255,255,0.90)` |
| Subtitle | `rgba(255,255,255,0.40)` |
| Divider | `rgba(255,255,255,0.15)` |
| Buttons (rest) | text `rgba(255,255,255,0.80)`, border `rgba(255,255,255,0.18)`, bg `rgba(255,255,255,0.06)` |
| Buttons (hover) | text `#ffffff`, bg `rgba(255,255,255,0.12)`, border `rgba(255,255,255,0.30)` |
| Active button | `#E90029` text, `rgba(233,0,41,0.50)` border, `rgba(233,0,41,0.12)` bg |
| Live badge | bg `rgba(255,255,255,0.08)`, border `rgba(255,255,255,0.18)` |
| Live text | `rgba(255,255,255,0.55)` |

### Typography, Geometry, Motion

Font stacks, border-radius scale, and transition timing are declared once in `:root` and are not overridden in day mode.

---

## Semantic Color Mapping

The same semantic intent maps to different hues depending on theme. Always use the token — never the hex — so components are theme-agnostic:

| Intent | Token | Dark mode hex | Day mode hex |
|---|---|---|---|
| Primary interactive / selected / focus | `--cyan` | `#00c8e8` | `#E90029` |
| Interactive hover | `--cyan-hover` | `#22d4f0` | `#FF1A3D` |
| Active / healthy / utilized | `--green` | `#00e676` | `#00875A` |
| Degraded / warning | `--amber` | `#f59e0b` | `#D4870A` |
| Error / destructive | `--crimson` | `#f43f5e` | `#B5001F` |
| Primary text | `--text` | `#e2eaf4` | `#1A1528` |
| Secondary text | `--text-muted` | `#8da8c0` | `#524F56` |
| Metadata / labels | `--text-dim` | `#4a6478` | `#7B768A` |
| Focus ring | `--border-focus` | `rgba(0,200,232,0.50)` | `rgba(233,0,41,0.50)` |

### Day-Mode-Only Colors (not tokenized)

These are used only in specific day mode component overrides — not part of the shared token system:

| Color | Hex | Used for |
|---|---|---|
| Keysight Dark Blue | `#225792` | Table header (`<th>`) text |
| Keysight Teal | `#07858b` | KCOS deployment chip; toast success text |
| Toast success (day) | `#07858b` | `--toast-ok-text` override |
| Toast error (day) | `#871518` | `--toast-error-text` override |

---

## Typography

Identical in both themes. No overrides in day mode.

### Font Stacks

```css
--font-ui:    'Inter', system-ui, -apple-system, sans-serif;
--font-mono:  'JetBrains Mono', 'Fira Code', 'Consolas', monospace;
```

`--font-mono` is the default for body, table cells, buttons, and inputs. `--font-ui` is available for any context requiring proportional type (not used in IxNSE, but available for a new portal that needs it).

### Type Scale

| Role | Size | Weight | Letter-spacing | Transform |
|---|---|---|---|---|
| Page base | `0.8125rem` / 13px | 400 | — | — |
| Logo mark | `1.3rem` | 400 | — | — |
| Header title h1 | `0.85rem` | 400 | `0.08em` | uppercase |
| Header subtitle | `0.62rem` | 400 | `0.18em` | uppercase |
| Table `<th>` | `0.65rem` | 700 | `0.16em` | uppercase |
| Table `<td>` | `0.75rem` | 400 | — | — |
| Session name | `0.78rem` | 500 | `0.03em` | — |
| Button (default) | `0.75rem` | 500 | `0.04em` | — |
| Button (small) | `0.70rem` | 500 | `0.04em` | — |
| Modal title | `0.78rem` | 400 | `0.10em` | uppercase |
| Form label | `0.68rem` | 400 | `0.10em` | uppercase |
| Tag chip | `0.65rem` | 500 | `0.06em` | — |
| Metadata / timestamp | `0.72rem` | 400 | `0.04em` | — |

**Weight rule:** 400 for display/label text, 500 for interactive controls and names, 700 for table headers exclusively.

---

## Geometry & Spacing

### Border Radius Scale

```css
--radius-sm:  3px;    /* chips, status icon boxes, tag badges  */
--radius:     6px;    /* buttons, inputs, toasts, pills        */
--radius-lg:  8px;    /* cards, server blocks                  */
--radius-xl:  12px;   /* modals                                */
```

Circular elements (live dot, heartbeat dots, link-state dots) use `border-radius: 50%`.

### Key Spacing Values

| Context | Value |
|---|---|
| Header height | `56px` |
| Header inline padding | `24px` |
| Control bar padding | `8px 24px` |
| Max content width | `1440px` |
| Content side padding | `24px` |
| Table `<th>` padding | `7px 12px` |
| Table `<td>` padding | `8px 12px` |
| Button padding (default) | `5px 11px` |
| Button padding (small) | `3px 8px` |
| Card/block gap | `14px` |
| Modal body padding | `16px 20px` |
| Modal footer padding | `12px 20px` |

---

## Component Patterns

### Buttons

All buttons use the same structure. Color is semantic — pick the variant that matches intent.

```css
/* Base */
.btn {
  display: inline-flex;
  align-items: center;
  gap: 5px;
  padding: 5px 11px;
  border: 1px solid transparent;
  border-radius: var(--radius);
  font-family: var(--font-mono);
  font-size: 0.75rem;
  font-weight: 500;
  letter-spacing: 0.04em;
  cursor: pointer;
  transition: background 150ms ease, border-color 150ms ease,
              box-shadow 150ms ease, opacity 150ms ease;
}
.btn:disabled { opacity: 0.35; cursor: not-allowed; }
```

| Variant | Resting state | Hover state |
|---|---|---|
| Primary | bg `--cyan-dim`, border `rgba(--cyan, 0.35)`, text `--cyan` | bg stronger, border `--cyan`, shadow `0 0 10px --cyan-glow` |
| Neutral | bg transparent, border `--border-med`, text `--text-muted` | bg `--surface-raised`, border `--border-bright`, text `--text` |
| Danger | bg `--crimson-dim`, border `rgba(--crimson, 0.35)`, text `--crimson` | bg stronger, border `--crimson`, shadow `0 0 10px rgba(--crimson, 0.2)` |

On the pinned dark header, buttons override their colors with white-opacity values (see [Theme Invariants](#theme-invariants)).

### Modals

```
Overlay:  position fixed; inset 0; bg rgba(2,5,10,0.8); backdrop-filter blur(4px)
Dialog:   bg --surface; border 1px solid --border-med
          border-top: 2px solid --cyan   ← semantic accent line
          border-radius: --radius-xl
          box-shadow: 0 20px 60px rgba(0,0,0,0.7), 0 0 40px --cyan-glow
```

Danger modals: swap `border-top-color` to `--crimson`; modal title color to `--crimson`.

Dialog enter animation: `translateY(-4px) → translateY(0)`, `250ms ease`, `opacity 0 → 1`.

### Cards / Server Blocks

```
border: 1px solid --border
border-left: 3px solid --border-bright    ← thicker left accent
border-radius: --radius-lg
overflow: hidden
```

On hover: left accent transitions to `rgba(--cyan, 0.4)`.

### Status Indicators

**CP / DP plane cells** — 18×18 px square, `border-radius: --radius-sm`:

| State | Background | Border | Text / Icon |
|---|---|---|---|
| Active | `--green-dim` | `--green-border` | `--green` · ✓ |
| Inactive | `--crimson-dim` | `rgba(--crimson, 0.30)` | `--crimson` · ✗ |

**Heartbeat dots** — 10×10 px, `border-radius: 50%`:

| State | Color | Glow |
|---|---|---|
| Healthy | `#22c55e` | `0 0 8px rgba(34,197,94,0.45)` |
| Degraded | `#ca8a04` | `0 0 6px rgba(234,179,8,0.35)` |
| Error | `#dc2626` | `0 0 6px rgba(239,68,68,0.40)` |

**Link-state dots** — 6×6 px, inline next to port numbers:

| State | Color | Glow |
|---|---|---|
| Link up | `--green` | `0 0 5px rgba(--green, 0.5)` |
| Link down | `--amber` | `0 0 5px rgba(--amber, 0.5)` |
| None | `--text-dim` | none |

### Deployment Chips (day mode overrides)

These chips use Keysight-specific colors that only appear in day mode:

```css
/* KCOS */
color: #07858b; border-color: rgba(7,133,139,0.40); background: rgba(7,133,139,0.08);

/* Standalone */
color: #225792; border-color: rgba(34,87,146,0.40); background: rgba(34,87,146,0.08);

/* On-Chassis */
color: #D4870A; border-color: rgba(212,135,10,0.40); background: rgba(212,135,10,0.08);
```

In dark mode these chips use the default cyan/amber/text-muted token styles.

### Toast Notifications

```
position: fixed; bottom: 24px; right: 24px; z-index: 2000

Individual toast:
  background: --surface-raised
  border: 1px solid --border-med
  border-left: 3px solid <semantic color>   ← the colored accent
  border-radius: --radius
  padding: 9px 14px
  max-width: 340px
  box-shadow: 0 8px 24px rgba(0,0,0,0.5)
```

Entry: `translateX(110% → 0)` in `220ms` with `cubic-bezier(0.34, 1.3, 0.64, 1)` (slight overshoot). Auto-dismiss after 5 seconds.

In day mode: `background: #ffffff`, `box-shadow: 0 4px 16px rgba(0,0,0,0.12)`, text uses `--text`.

### Form Inputs

```css
background: var(--surface-alt);
border: 1px solid var(--border-med);
border-radius: var(--radius);
color: var(--text);
font-family: var(--font-mono);
font-size: 0.80rem;
padding: 8px 12px;
transition: border-color 150ms ease, box-shadow 150ms ease;

/* Focus */
border-color: var(--border-focus);   /* --cyan at 50% opacity */
box-shadow: 0 0 0 3px var(--cyan-dim);
```

Placeholder: `--text-xdim`. Disabled: `opacity: 0.45`.

---

## Implementing Dual-Theme in a New Project

### Step 1 — Paste the token blocks

Copy both the `:root` (dark) and `body[data-theme="day"]` blocks exactly as defined above. Do not modify hex values.

### Step 2 — Apply the pinned header

```html
<header>...</header>
```

```css
header {
  background: #291B44;
  border-bottom: 1px solid #3d2860;
  /* All text inside uses white-opacity values, never --text tokens */
}
```

This never changes between themes. Do not tokenize it.

### Step 3 — Write components against tokens only

```css
/* Good */
.my-card {
  background: var(--surface);
  border: 1px solid var(--border);
  color: var(--text-muted);
}

/* Bad — breaks theme switching */
.my-card {
  background: #080c15;
  border: 1px solid #1e2d42;
  color: #8da8c0;
}
```

### Step 4 — Theme toggle

```html
<button id="theme-toggle">Day / Dark</button>
```

```js
document.getElementById('theme-toggle').addEventListener('click', () => {
  const current = document.body.dataset.theme;
  document.body.dataset.theme = current === 'day' ? '' : 'day';
  localStorage.setItem('theme', document.body.dataset.theme);
});

// On load
const saved = localStorage.getItem('theme');
if (saved) document.body.dataset.theme = saved;
```

### Step 5 — Day mode component exceptions

After the base `body[data-theme="day"]` block, add targeted overrides for components that need them. Pattern:

```css
/* Pattern: scoped overrides after the token block */
body[data-theme="day"] .my-table th {
  color: #225792;   /* Keysight Dark Blue — not in token system */
}
body[data-theme="day"] .chip--kcos {
  color: #07858b;
  border-color: rgba(7, 133, 139, 0.40);
  background: rgba(7, 133, 139, 0.08);
}
```

Only add overrides where the token-based styles produce an unacceptable result in day mode (usually contrast issues or brand requirement for specific hues).

### Step 6 — Google Fonts import

```css
@import url('https://fonts.googleapis.com/css2?family=JetBrains+Mono:wght@300;400;500;600;700&family=Inter:wght@300;400;500;600;700&display=swap');
```

If offline-first is required, download the WOFF2 files and host locally.

---

## Anti-Patterns to Avoid

| Anti-pattern | Why it breaks |
|---|---|
| Hardcoding hex values in component CSS | Breaks theme switching — one hex can't serve both modes |
| Placing `--surface-raised` directly on `--bg` | Surface layer skipping creates jarring contrast jumps |
| Using `--cyan` for non-interactive decoration | Dilutes the semantic signal — users learn to associate cyan/red with "I can click this" |
| Tokenizing the header background | The purple header must be constant; tokenizing it invites accidental theme changes |
| Using `box-shadow` for depth on content surfaces | Shadows read as consumer-product. Use background-layer differences and `1px` borders instead |
| `font-weight: 700` outside table headers | In monospace type, bold weight is visually aggressive; reserve it for data-dense column headers only |
| Mixing `--green` with non-status contexts | If something is green, users assume it is healthy/active. Green decorative elements create false positives in a NOC context |
| Adding `color: --crimson` to non-error text | Same principle — crimson means something is wrong or dangerous |
