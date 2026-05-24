# Home-stack UI spec

Goal: **structural unity, chromatic identity.** A button in calendar, library,
and dashboard should *sit* the same way (same padding, radius, focus ring,
hover transition) even though each app's palette is different. Users moving
between apps feel "same product family"; each app keeps its own visual voice.

The spec has three layers:

1. **Token interface** — semantic CSS-variable role names. Every app defines
   the same names. The *values* differ per app.
2. **Primitive components** — `.btn` + variants, `.input`. Same rules in
   every app, sourced from the token interface above.
3. **App-specific extensions** — anything visual that is unique to one app
   (calendar's mood circles, library's bookshelf spines, dashboard's service
   tiles) lives in that app's CSS and does not enter the spec.

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

    /* Spacing scale */
    --space-2;              /*  8px — tight gap inside controls */
    --space-3;              /* 12px — gap between controls */
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
    --font-sans;            /* primary UI font (Arial, Helvetica, sans-serif) */
    --font-mono;            /* form inputs / terminal-flavoured surfaces */
}
```

**14 color tokens + 4 sizes + 4 spaces + 4 radii.** Apps **may** add their own
role-style tokens for unique surfaces (calendar adds `--color-bg-overlay-strong`,
`--color-border-soft`, `--color-stripe`, etc.). These are app-local and don't
enter the spec.

### Reference values (current apps)

| Role | Calendar (Gruvbox) | Library (Soft) | Dashboard (Slate, target) |
|---|---|---|---|
| `--color-bg-base` | `#282828` | `#FFF1E5` | `#f8fafc` |
| `--color-text-primary` | `#ebdbb2` | `#34495E` | `#0f172a` |
| `--color-accent` | `#689d6a` | `#6AACFF` | `#0f172a` |
| `--color-danger` | `#cc241d` | `#C0392B` | `#e11d48` |

(Dashboard column is the target — not yet implemented.)

---

## Layer 2 — Primitive components

Mandatory. Vanilla-CSS apps (calendar, library) include this file verbatim;
Tailwind apps (dashboard) can either include it or wire the same shapes via
Tailwind's `@apply`.

```css
.btn {
    display: inline-flex;
    align-items: center;
    justify-content: center;
    gap: var(--space-2);
    padding: var(--space-2) var(--space-3);
    font: inherit;
    border: 1px solid transparent;
    border-radius: var(--radius-md);
    cursor: pointer;
    transition: background-color 0.2s ease, border-color 0.2s ease, color 0.2s ease;
}
.btn:focus-visible { outline: 2px solid var(--color-accent-hover); outline-offset: 2px; }
.btn-primary   { background: var(--color-accent); color: #fff; }
.btn-primary:hover   { background: var(--color-accent-hover); }
.btn-secondary { background: transparent; border-color: var(--color-border); color: var(--color-text-secondary); }
.btn-secondary:hover { background: var(--color-highlight-soft, var(--color-bg-inset)); color: var(--color-text-primary); }
.btn-danger    { background: var(--color-danger); color: #fff; }
.btn-danger:hover    { background: var(--color-danger-hover); }
.btn-ghost     { background: transparent; color: var(--color-text-muted); padding: var(--space-2); }
.btn-ghost:hover     { color: var(--color-text-primary); }

.input {
    background: var(--color-bg-inset);
    color: var(--color-text-primary);
    border: 1px solid var(--color-border);
    border-radius: var(--radius-sm);
    padding: var(--space-2);
    font-family: var(--font-sans);  /* override to --font-mono per-app where appropriate */
    font-size: var(--text-base);
    transition: border-color 0.2s ease;
}
.input:focus { outline: none; border-color: var(--color-accent); }
.input::placeholder { color: var(--color-text-faint); }
```

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

For a personal stack of three repos:

- **Calendar** keeps `static/css/index.css` with the token block + primitives
  at the top. Source of truth lives there.
- **Library** mirrors the token block + primitives in `static/css/index.css`
  (and copies the relevant subset into `reader.css`).
- **Dashboard** declares the same tokens in `:root` of its global CSS and
  references them from Tailwind utilities (Tailwind v4 reads CSS vars
  natively).

If drift becomes painful, lift the primitives to a `home-ui-spec/` git
submodule that all three apps include. Premature today (changes are infrequent
and small).

---

## Current adoption

- ✅ **Calendar** — tokens + primitives shipped (`309d3ef`).
- 🟡 **Library** — token interface adopted (rename of existing variables);
  primitives defined but not applied to elements yet. Pending visual review
  + Bootstrap-vs-`.btn` collision plan.
- ❌ **Dashboard** — uses Tailwind's slate palette directly today; tokens
  not declared. Quick win: add `:root` token block, wire Tailwind theme to
  read from it. No structural change needed.

## Open questions

- **Bootstrap collision in library.** Library loads Bootstrap 5 from CDN for
  grid utilities (`.container`, `.row`, `.col-md-*`). Bootstrap also defines
  `.btn` and `.btn-*` variants. Two paths: (a) replace Bootstrap's grid with
  vanilla flex/grid and remove the CDN load; (b) rename the spec primitive
  in library only (e.g. `.ui-btn`) to avoid the clash.
- **Dashboard Tailwind integration.** Two ways to consume the tokens: keep
  Tailwind utility classes pointing at the token vars (palette unifies, no
  primitives), or also use `.btn`/`.input` for select components (deeper
  unification, more divergence from typical React-Tailwind UX). Pick when
  dashboard's token adoption happens.
