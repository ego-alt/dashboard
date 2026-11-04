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
| Situation | the world map | graphite; amber for FLASH, blue for PRIORITY | Flightradar24, the FT's and Reuters' live maps |

- **Tapes**: Gruvbox with an orange accent. The cassette's label is printed in a fixed retro palette (red, orange, mustard, brown on cream), and its handwriting scales with the cassette. The library borrows the cassette's construction: each bar's edge is a seam; search, +, menus and forms open as recessed slots; going into a list, a slot opens under the row and the row rises into the bar. Each level in is a step darker. The slots work as one mechanism: one open at a time, nested ones shut inner first, rows below a closing slot ride up with it, and a tall slot takes longer to close than a small one (about the square root of its height). The control that opens a slot also closes it, so there are no × buttons. Inside an album, songs don't repeat the album and artist.
- **Calendar**: a terminal logbook in Inter and a self-hosted IBM Plex Mono (the system monospace differed per device). Sizes go by job: 16 a title, 14 what you read and tap (mood labels, notes, buttons, entries), 11 system output and chrome (the bar, messages and status lines, key hints, the time gutter). Buttons and inputs are 14px monospace with square corners (except the mood tiles), with a tmux-style bottom bar and logbook text marks in the drawers. From and To are one field each: the date as the logbook writes it (`Fri 6 Nov 2026`, the native date field laid invisibly over it, so a tap opens the phone's own picker), a hairline, then a typed 24-hour `hh:mm`. No browser icons in the form. One 2px aqua focus ring for everything. Messages are terminal output: grey monospace log lines, no colour and no boxes. A problem is marked `!`, under the field it's about (that field's edge turns lighter) or as a one-line strip on the bottom bar; news is marked `›`, like the status line. Bar lines never wrap: what failed, then `·` and why (`! Couldn't save the mood · offline`); a longer one ends in `…` and opens on tap. They're printed at once, not animated. Loading, empty and hint lines are status lines too (`› Loading…`, `› No entries in December.`), left-aligned. A list that didn't load says so in place, with an `[r] try again` command (R on a keyboard). In the form, a message under the To row takes the hint's place. Red is only for buttons that destroy something.
- **Library**: a gallery wall in warm light, with a glow, paper grain and frosted panels by day and night. Covers hang with square corners. Buttons are outlines, never filled, with small corners like the reader's settings; search and status are hairlines and underlines. The reader drops the light for a flat, plain page.
- **Dashboard**: an engineering blueprint in slate. Every page opens with `PageHeader.jsx`, cards share `Panel.jsx` and `.bp-panel*`, and row actions use `.btn-link`. Beside Sign out, admins get a quiet power icon that asks first, then shuts the Pi down. Status colours are still Tailwind's green, amber and red rather than tokens.
- **Situation**: a newsroom wall: graphite glass, a frameless map in the Patterson cylindrical projection (true to shape where most news happens) that fills its panel edge to edge, facts in Plex Mono and headlines in Inter. No pins: a country in the news is tinted in its tier's colour and named on itself atlas style: thin, widely spaced grey capitals with no outline (no halo or stroke on any map text), kept inside the map; close up, a city is a small dot. A picked or opened country is outlined. The list leads with the top story (a bigger headline and a small locator map of its country); each story's facts are one quiet sans line: where, how long ago, how many outlets, and a Live tag for running stories. The bar has one status, "Updated 4m ago" with a dot that turns amber when anything's wrong. Opening a story frames its places within their country, never a province alone. Close up, the country gets only a soft wash of its colour and the regions the news names carry it, drawn above their neighbours so each outline is one even width; picked ones get a brighter edge in their own colour, never white. Cities in the news are a tier-coloured dot with a plain name; reference cities are small grey names, only in countries in the news; no label goes under the map's buttons. Buttons are small bordered mono chips. Its Papers tab is a weekly front page in the same glass and type: a spaced mono nameplate (the subject), a folio between rules, then the lead with a rail and rows of modules whose shape changes row to row. Wide slots float the figure top-left so text wraps around and under it; each row's text runs to the row's foot, cut at a whole line with the last line faded, and a click opens the whole story in place; only an opened story links out (paper, free copy, commentary). No pull quotes, no broadsheet columns. On a phone it's a list: the lead with its figure, then each story with its figure as a 72px thumbnail beside the title and two lines of abstract (the commentary's summary instead, when it has one); the rest of a long week stays titles only. Tapping a figure opens it full screen to zoom. No disclosure triangles: a story opens with a tap anywhere on it. Opening a story only reveals; a figure already shown whole (the lead's) keeps its size, and only cropped figures and thumbnails grow to show the whole image. The edition steps repeat at the foot, under a single rule, above the footer's double one.

---

## Rules

Each Flask app (calendar, library, situation, tapes) has:

- **`tokens.css`**: every size and colour it uses (spacing, corners, type, fonts, motion, colours), with its own values;
- **`controls.css`**: its one definition of buttons and inputs;
- its own CSS for everything else, written only in its tokens.

The dashboard (React with Tailwind) keeps the same colour role names in its global CSS.

1. **No raw sizes or colours outside `tokens.css`.** `tokens.css` also sets `color-scheme` to the theme's (dark or light), so what the browser draws itself (date pickers, open dropdowns, scrollbars, autofill, a search field's ×) matches.
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
   - a visible focus ring on everything focusable, from one `:focus-visible` rule in `controls.css` (the browser's default ring is near-black on a dark page);
   - touch targets of at least 44px on phones;
   - motion off under `prefers-reduced-motion`: transitions use the `--dur-*` tokens, which that query sets to 0;
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
| Situation | 11 | 13 | 15 | 17 | 24 |
