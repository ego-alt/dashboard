# Home-stack UI spec

Each app's theme, the products it learns from, and the stylesheet rules every app follows. The general principles are in [design-guidelines.md](design-guidelines.md).

The apps don't share a stylesheet. Each has its own type, sizes, corners and palette to match its theme; what they share is the guidelines and the rules below.

---

## Each app

| App | Centrepiece | Accent | Best in the field, to learn from |
|---|---|---|---|
| Tapes | the cassette deck | orange | Spotify, Apple Music, Pocket Casts, Overcast |
| Calendar | the month grid | green | Fantastical, Google Calendar, Things |
| Library | the covers, lit in warm light | slate by day, gold by night | Apple Books, Kindle, Libby |
| Dashboard | the service tiles | slate blue | Linear, Vercel, Grafana |
| Situation | the world map | phosphor green; amber for FLASH, cyan for PRIORITY | Flightradar24, the FT's and Reuters' live maps |

- **Tapes**: Gruvbox with an orange accent. The cassette's label is printed in a fixed retro palette (red, orange, mustard, brown on cream), and its handwriting scales with the cassette. The library borrows the cassette's construction: each bar's edge is a seam; search, +, menus and forms open as recessed slots; going into a list, a slot opens under the row and the row rises into the bar. Each level in is a step darker.
- **Calendar**: a terminal logbook. Buttons and inputs are 14px monospace with square corners (except the mood tiles), with a tmux-style bottom bar and logbook text marks in the drawers.
- **Library**: a gallery wall in warm light, with a glow, paper grain and frosted panels by day and night. Covers hang with square corners. Buttons are outlines, never filled, with small corners like the reader's settings; search and status are hairlines and underlines. The reader drops the light for a flat, plain page.
- **Dashboard**: an engineering blueprint in slate. Every page opens with `PageHeader.jsx`, cards share `Panel.jsx` and `.bp-panel*`, and row actions use `.btn-link`. Status colours are still Tailwind's green, amber and red rather than tokens.
- **Situation**: an operations-room wall: near-black glass, a phosphor-green map, facts in Plex Mono and headlines in Inter. Buttons are small bordered mono chips.

---

## Rules

Each Flask app (calendar, library, situation, tapes) has:

- **`tokens.css`**: every size and colour it uses (spacing, corners, type, fonts, motion, colours), with its own values;
- **`controls.css`**: its one definition of buttons and inputs;
- its own CSS for everything else, written only in its tokens.

The dashboard (React with Tailwind) keeps the same colour role names in its global CSS.

1. **No raw sizes or colours outside `tokens.css`.**
   - Stylesheets use `var(--text-*)`, `var(--space-*)` and `var(--color-*)`.
   - Relative sizes (`em`, `%`) are fine for things sized to the text around them.
   - Each app's `tests/test_style_tokens.py` fails on a raw font size outside `tokens.css`.
2. **At most five type sizes and two typefaces.**
   - Sizes are tokens named `--text-xs`, `-sm`, `-base`, `-lg` and `-xl`, with the app's own values, no two a pixel apart. The test fails above five.
   - Text an app doesn't own (a book's own styles in the reader) keeps its sizes.
3. **One spacing scale and one set of corners** per app, as tokens.
4. **One button definition per app**, in `controls.css`: a main action, a quiet one and bare words. Nothing else restyles them; a component may only place or size one.
5. **Shared colour role names** (below), so the same word means the same job everywhere. Values are each app's own, and apps may add roles of their own.
6. **One mobile breakpoint, 640px**: `@media (max-width: 640px)` (CSS can't read a `var()` there).
7. **Accessible everywhere:**
   - a visible focus ring on everything focusable;
   - touch targets of at least 44px on phones;
   - motion off under `prefers-reduced-motion`;
   - text contrast of at least 4.5:1.

### Colour role names

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

Apps' own roles:
- calendar: `--color-bg-chrome`, `--color-bg-pane`, `--color-syn-*`;
- library: `--color-success`, `--color-scrim`, `--wood`;
- tapes: `--color-bg-pane`;
- situation: the tiers (`--color-flash*`, `--color-priority*`) and the map (`--color-sea`, `--color-land*`, `--color-region*`).

### Reference values

| Role | Calendar | Library (day) | Library (night) | Tapes | Situation | Dashboard |
|---|---|---|---|---|---|---|
| `--color-bg-base` | `#1d2021` | `#f6f4ef` | `#141210` | `#282828` | `#070a0b` | `#182230` |
| `--color-text-primary` | `#ebdbb2` | `#1f1d1a` | `#eadfca` | `#ebdbb2` | `#d3dedb` | `#d4dde8` |
| `--color-accent` | `#689d6a` | `#535f5f` | `#d4b36a` | `#fe8019` | `#5fd3a6` | `#6f9bc4` |
| `--color-danger` | `#cc241d` | `#a6352b` | `#e46b5f` | `#cc241d` | (FLASH `#ffb020`) | `#e0697d` |

### Type scales (px)

| | xs | sm | base | lg | xl |
|---|---|---|---|---|---|
| Calendar | 11 | 14 | 16 | 20 | 32 |
| Library | 12 | 14 | 16 | 20 | 24 |
| Tapes | 12 | 14 | 16 | 20 | 24 |
| Situation | 11 | 13 | 15 | 17 | — |
