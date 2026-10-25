# Home-stack UI spec

Goal: **shared discipline, own voice.** The apps don't share a stylesheet; each one has its own type, sizes, corners and palette to match its theme (calendar is a terminal, tapes a cassette deck, library a gallery wall). What they share is a handful of rules, so each app stays tidy on its own terms and they all behave the same way to use.

Each Flask app (calendar, library, tapes) has:

- **`tokens.css`** — every size and colour the app uses: spacing, corners, type, fonts, motion, colours. Its own values.
- **`controls.css`** — its one definition of buttons and inputs (`.btn`, `-primary`, `-secondary`, `-ghost`, `.input`), in its own style.
- Its own CSS for everything else, written only in its tokens.

Dashboard (React/Tailwind) keeps the same colour role names in its global CSS.

There used to be a shared `structural.css`, meant to be byte-identical across the apps. It drifted as each app's look developed, and was retired in October 2026.

---

## The rules

1. **No raw sizes or colours outside `tokens.css`.** Stylesheets use `var(--text-*)`, `var(--space-*)`, `var(--color-*)`. Relative sizes (`em`, `%`) are fine where something is sized to the text around it (a book's headings, an icon). Each app's `tests/test_style_tokens.py` fails on a raw `font-size` (or `font:` shorthand size) outside `tokens.css`.
2. **At most five type sizes, as tokens.** Name them `--text-xs`, `-sm`, `-base`, `-lg`, `-xl`; the values are the app's own (a monospace face wants different sizes from Inter). No two a pixel apart. The test fails above five. Text an app doesn't own (a book's own styles in library's reader) keeps its sizes.
3. **One spacing scale, one set of corners** per app, as tokens.
4. **One button definition per app**, in `controls.css`: a main action, a quiet one and a bare-words one. Nowhere else redefines them; a component may only position or size one.
5. **Colour role names are shared** (below), so the same word means the same job everywhere. Values are each app's own. Apps may add their own roles.
6. **One mobile breakpoint, 640px.** CSS can't read a `var()` inside `@media`, so it's a convention: `@media (max-width: 640px)`.
7. **The same behaviour everywhere:** a visible focus ring on everything focusable, touch targets of at least 44px on phones, motion off under `prefers-reduced-motion`, and contrast of at least 4.5:1 for text.

---

## Colour role names

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
    --color-accent;         /* main action, focus ring */
    --color-accent-hover;

    /* Status */
    --color-danger;         /* destructive actions, error text */
    --color-danger-hover;

    /* Decoration */
    --color-shadow;         /* box-shadow tint */
    --color-highlight-soft; /* hover background, subtle separators */
}
```

Apps add their own roles for surfaces only they have: calendar's `--color-bg-chrome`, `--color-bg-pane` and `--color-syn-*`; library's `--color-success`, `--color-scrim`, `--wood`; tapes' `--color-bg-pane`.

### Reference values

| Role | Calendar (Gruvbox) | Library (day) | Library (night) | Tapes (Gruvbox + orange) | Dashboard (Slate) |
|---|---|---|---|---|---|
| `--color-bg-base` | `#1d2021` | `#f6f4ef` | `#141210` | `#282828` | `#182230` |
| `--color-text-primary` | `#ebdbb2` | `#1f1d1a` | `#eadfca` | `#ebdbb2` | `#d4dde8` |
| `--color-accent` | `#689d6a` | `#535f5f` slate | `#d4b36a` gold | `#fe8019` | `#6f9bc4` |
| `--color-danger` | `#cc241d` | `#a6352b` | `#e46b5f` | `#cc241d` | `#e0697d` |

### Type scales

| | xs | sm | base | lg | xl |
|---|---|---|---|---|---|
| Calendar | 11 | 14 | 16 | 20 | 32 |
| Library | 12 | 14 | 16 | 20 | 24 |
| Tapes | 12 | 14 | 16 | 20 | 24 |

---

## Each app's voice

- **Calendar** — a terminal: buttons and inputs in 14px monospace, square corners (except the mood tiles), the tmux-style bottom bar and the logbook text marks in the drawers.
- **Library** — a gallery wall in warm light (a glow, a paper grain and frosted panels by day and night); covers hang with square corners; buttons are outlines, never filled, with small corners like the reader's settings; search and status are hairlines and underlines. The reader drops the light for a flat, calm page.
- **Tapes** — Gruvbox with an orange accent, a drawn cassette whose label is handwritten and scales with the cassette.
- **Dashboard** — slate; every page opens with `PageHeader.jsx`, cards share `Panel.jsx` + `.bp-panel*`, row actions use `.btn-link`. Status colours are still Tailwind's green/amber/red rather than tokens.
