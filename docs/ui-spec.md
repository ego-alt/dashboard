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
    --font-sans;            /* 'Inter', Arial, Helvetica, sans-serif */
    --font-mono;            /* ui-monospace, SFMono-Regular, Menlo, Consolas, monospace */
}
```

**14 color tokens + 4 sizes + 4 spaces + 4 radii.** Apps **may** add their own
role-style tokens for unique surfaces (calendar adds `--color-bg-overlay-strong`,
`--color-border-soft`, `--color-stripe`, etc.). These are app-local and don't
enter the spec.

Inter is loaded via Google Fonts in each app's HTML entry point with the
preconnect pair + a `wght@400..700` variable subset. Falls back to Arial when
the CDN is blocked.

### Reference values (current apps)

| Role | Calendar (Gruvbox) | Library (Soft, light) | Library (dark) | Dashboard (Slate) |
|---|---|---|---|---|
| `--color-bg-base` | `#282828` | `#FFF1E5` | `#282828` | `#f8fafc` |
| `--color-text-primary` | `#ebdbb2` | `#34495E` | `#ebdbb2` | `#0f172a` |
| `--color-accent` | `#689d6a` | `#6AACFF` | `#689d6a` | `#0f172a` |
| `--color-danger` | `#cc241d` | `#C0392B` | `#cc241d` | `#e11d48` |

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

- ✅ **Calendar** — tokens, primitives, headings, font all shipped.
- ✅ **Library** — same, plus dark mode unified to calendar's Gruvbox palette.
  Reader page also migrated off Bootstrap's `.btn-outline-*` to spec primitives.
- 🟡 **Dashboard** — tokens + primitives in place; LoginPage + SettingsPage
  migrated to `.btn` / `.input`. HomePage + MonitorPage still use Tailwind
  utilities (palette flows through via the same tokens; structural primitives
  not applied). Heading conventions not yet enforced.

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
