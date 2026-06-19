# Home-stack UI spec

Goal: **structural unity, chromatic identity.** A button in calendar, library,
and dashboard should *sit* the same way (same padding, radius, focus ring,
hover transition) even though each app's palette is different. Users moving
between apps feel "same product family"; each app keeps its own visual voice.

The spec is two shared pieces + per-app freedom:

1. **Shared base** (`structural.css`) — the non-thematic skeleton: spacing,
   radii, type, fonts, motion tokens, **and** the `.btn`/`.input` primitives.
   Byte-identical across the Flask apps (dashboard mirrors the shapes via its
   React global CSS).
2. **Per-app theme** (`tokens.css`) — the colour role-tokens. Same names
   everywhere; values unique per app.
3. **App-specific extensions** — anything visual unique to one app (calendar's
   mood circles, library's bookshelf spines, dashboard's service tiles) lives in
   that app's own CSS and isn't part of the spec.

---

## Layer 1 — Token interface

Mandatory. Each app declares these in `:root` (light) with optional
`.dark-mode` (or media-query) overrides. Names are the contract; values vary.

```css
:root {
    /* Surfaces */
    --color-bg-base;        /* page background */
    --color-bg-elevated;    /* sidebars, modals, raised cards */
    --color-bg-inset;       /* nested panels, form-field surface */
    --color-bg-overlay;     /* modal backdrop / dimming layer */

    /* Borders */
    --color-border;         /* form/card borders */

    /* Text — three levels */
    --color-text-primary;   /* default body text */
    --color-text-secondary; /* slightly de-emphasised */
    --color-text-muted;     /* metadata, captions, placeholders */

    /* Accent */
    --color-accent;         /* primary-button bg, focus ring */
    --color-accent-hover;   /* primary-button hover, soft accent fills */

    /* Status */
    --color-danger;         /* destructive-button bg, error text */
    --color-danger-hover;

    /* Decoration */
    --color-shadow;         /* box-shadow tint */
    --color-highlight-soft; /* hover bg, subtle separators */

    /* Spacing scale (numbers are × 4px) */
    --space-1;              /*  4px — micro gap (icon padding, tag chips) */
    --space-2;              /*  8px — tight gap inside controls */
    --space-3;              /* 12px — gap between controls */
    --space-4;              /* 16px — card / form-row rhythm */
    --space-5;              /* 20px — section padding */
    --space-8;              /* 40px — top-level layout rhythm */

    /* Radii */
    --radius-sm;            /*  4px — inputs, small chrome */
    --radius-md;            /*  8px — cards, buttons, modals */
    --radius-lg;            /* 16px — mobile bottom-sheet */
    --radius-pill;          /* full-round — pills, circular dots */

    /* Type scale — four sizes */
    --text-sm;              /* 14px — captions, secondary */
    --text-base;            /* 16px — body */
    --text-lg;              /* 20px — h2, emphasis */
    --text-xl;              /* 32px — h1 */

    /* Fonts */
    --font-sans;            /* 'Inter', Arial, Helvetica, sans-serif */
    --font-mono;            /* ui-monospace, SFMono-Regular, Menlo, Consolas, monospace */

    /* Motion — `ease` is the default curve; --ease-emphasized for entrances/pops */
    --dur-fast;             /* 0.12s — hover / opacity micro-transitions */
    --dur-base;             /* 0.20s — default control transitions (matches .btn) */
    --dur-slow;             /* 0.30s — panels, drawers, progress fills */
    --ease-emphasized;      /* cubic-bezier(0.16, 1, 0.3, 1) — menus, toasts */
}
```

**14 color tokens + 4 sizes + 6 spaces + 4 radii + 4 motion.** Apps **may** add their own
role-style tokens for unique surfaces (calendar adds `--color-bg-overlay-strong`,
`--color-border-soft`, `--color-stripe`, etc.). These are app-local and don't
enter the spec.

Library additionally defines a semantic status token `--color-success` (used by
toast notifications). Treat as an app-local extension until a second app needs
the same role.

Inter is loaded via Google Fonts in each app's HTML entry point with the
preconnect pair + a `wght@400..700` variable subset. Falls back to Arial when
the CDN is blocked.

**Breakpoint.** One mobile breakpoint across the stack: **640px**. CSS can't read
a `var()` inside `@media`, so this is a convention, not a token — write
`@media (max-width: 640px)`. An app whose layout genuinely pivots elsewhere may
add its own, but converge on 640px for the primary mobile collapse. (Current
drift to reconcile: calendar uses 480px, library 575.98/600/768px; tapes is at
640px.)

**Structural vs chromatic.** Everything above *except the colour tokens* is
structural — no brand meaning, identical everywhere. It lives (together with the
`.btn`/`.input` primitives) in `structural.css`; the per-app colours live in
`tokens.css`. Swap the theme and the skeleton never moves.

### Reference values (current apps)

| Role | Calendar (Gruvbox) | Library (Soft, light) | Library (dark) | Tapes (Gruvbox+orange) | Dashboard (Slate) |
|---|---|---|---|---|---|
| `--color-bg-base` | `#282828` | `#FFF1E5` | `#282828` | `#282828` | `#f8fafc` |
| `--color-text-primary` | `#ebdbb2` | `#34495E` | `#ebdbb2` | `#ebdbb2` | `#0f172a` |
| `--color-accent` | `#689d6a` | `#6AACFF` | `#689d6a` | `#fe8019` | `#0f172a` |
| `--color-danger` | `#cc241d` | `#C0392B` | `#cc241d` | `#cc241d` | `#e11d48` |

Library's dark mode adopts calendar's Gruvbox values so the two apps converge
at night; light mode keeps library's soft-academia identity.

### Heading conventions (per-app, not spec tokens)

Applied identically in calendar + library; dashboard headings use Tailwind
utility classes mapping to the same scale.

| Element | Rule |
|---|---|
| `h1` | `font-size: var(--text-xl)` · `font-weight: 550` · `letter-spacing: -0.01em` · `color: var(--color-text-muted)` |
| `h2` | `font-size: var(--text-lg)` · `font-weight: 600` |

---

## Layer 2 — Primitive components

`.btn` (+ `-primary` / `-secondary` / `-danger` / `-ghost`) and `.input`. The
canonical rules live **in `structural.css`** alongside the tokens — the Flask
apps load that one file; dashboard carries the same shapes in its React global
CSS. Transitions use `--dur-base`. An app may override a single primitive in its
own CSS (calendar, for instance, keeps monospace inputs over a base surface).

### Conventions

- **`.btn-primary`** — single most-important action on a surface (Save,
  Sign in, Submit).
- **`.btn-secondary`** — alternative action (Cancel, Close).
- **`.btn-danger`** — destructive (Delete, Disable 2FA).
- **`.btn-ghost`** — icon-only header buttons; no fill, no border.

Markup pattern: every button gets `class="btn btn-{variant}"`. Layout-only
classes (`.save-btn`, `.login-button` etc.) can coexist on the same element
purely for positioning / width.

---

## Layer 3 — App-specific extensions

Not part of the spec. Each app owns its own additional CSS for:

- **Calendar** — mood color circles (`data-mood` attribute selectors), week
  view, diary sidebar, day cells.
- **Library** — bookshelf spines + planks, book-card overlays, EPUB reader
  controls, status tags (`--tag-*`).
- **Dashboard** — service tiles, container monitor cards, sparkline charts.

These should reference the token interface (so palette swaps cascade) but
otherwise are free to define their own shapes.

---

## Distribution

Each Flask app (tapes, calendar, library) carries two files: a shared
**`structural.css`** (tokens + primitives — byte-identical across the three) and
a per-app **`tokens.css`** (colours), loaded in that order. Dashboard
(React/Tailwind) declares the same colour tokens in its global CSS and styles
`.btn`/`.input` there directly.

Keep `structural.css` in sync by copying it verbatim between the apps — it
changes rarely. Colours and app-specific extensions diverge freely.

---

## Current adoption

- ✅ **Calendar / Library / Tapes** — shared `structural.css` (tokens +
  primitives + motion) + per-app `tokens.css`. Library's dark mode unifies to
  calendar's Gruvbox palette; calendar keeps monospace inputs as its one
  primitive override.
- 🟡 **Dashboard** — colour tokens + `.btn`/`.input` in its React global CSS;
  LoginPage + SettingsPage migrated, HomePage + MonitorPage still on Tailwind
  utilities (palette flows through the same tokens). Heading conventions not yet
  enforced.

## Open questions

- **Library still loads Bootstrap CDN** for grid utilities (`.container`,
  `.row`, `.col-md-*`) on the index page and additional utilities on the reader
  page. Buttons + inputs are off Bootstrap now; only the grid + a handful of
  spacing utilities remain. If those are replaced with vanilla flex/grid, the
  CDN load can go.
- **Dashboard primitive coverage**. HomePage / MonitorPage are still
  Tailwind-styled. Migrating means rewriting utility-class chains to `.btn`
  variants on a per-component basis. Worth it for consistency, awkward for
  Tailwind-native devs.
