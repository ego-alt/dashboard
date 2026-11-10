# Design

How every home-stack app is designed: the principles they share, how design work is done, each app's own theme, and the stylesheet rules every app follows.

The apps don't share a stylesheet. Each has its own type, sizes, corners and palette to match its theme; what they share is the principles and the rules here. Only rules that hold across apps belong in this file: how one app does a detail is written beside the code that does it.

---

## Principles

### 1. Each app is built around one thing

Everything else serves it (see [each app](#each-app)).

- Context sits beside it in drawers and side panes and never replaces it.
- Controls stay off it: the ways to reach other views and drawers live in the app's bars, not on the centrepiece.
- A bar tells places from drawers: a view is a tab, and a drawer that belongs to a view is a toggle beside it that never looks like a tab, so only one place is ever lit.
- Each app has its own accent, set as a hex value.
- Judge an app against its own intent, not generic conventions.

### 2. Little decoration

Details are small and exact; nothing is added for effect.

- Effects stay subtle. A loud texture, a blinking cursor or a theme laid over the controls gets cut.
- Nothing is there only for show: the bookshelf view and the deck's speaker went.
- Prefer the plain option: a plain font, a plain circle icon, a plain header.
- A small touch is fine when it's quiet and fits, like placeholder covers for books without art.
- Don't dim part of a text to steer the eye: the context matters as much as the point.

### 3. One way to do each thing

Pick one existing version as the model and match it; never build a second.

- One component per job: one dropdown, one icon set, one button style, one dialog, with the same corners throughout.
- The same kind of task looks and works the same way. Rip a link, follow a podcast, new tape and new show all use one field.
- The same thing offers the same options everywhere: every container gets the same buttons.
- Controls side by side share size, font and width; tiles in a row share a height.
- Text keeps its size from one level to the next: going into a list doesn't make its title or rows bigger than where you came from.
- One part of an app is the model for the rest: comics follow books, and a feature one lacks isn't added to the other.

### 4. Exact spacing and alignment

- Judge spacing by eye as well as by numbers: two gaps that measure the same can look different and still need fixing.
- The same gap between a header and its first element on every page.
- Centre what should be centred; keep mirrored layouts symmetric.
- Align icons to the top line of the text beside them; close lists with a bottom line on the last row.
- On phones, keep things flush with the edges.
- Don't break lines early; let text fill its width.
- Text wraps around a figure in the corner rather than leaving a gap beneath it, and columns side by side end level.

### 5. Space goes to content

- Headers, strips and bars that hold little are removed or merged.
- Bars are thin and single-row.
- Rows are compact enough to scan without feeling cramped; tiles are neither tall nor squashed.
- Bars, menus and dialogs use the content's text sizes or smaller: a dialog's title matches the tabs, its buttons the menu items.

### 6. Remove before adding

- Cut what isn't used: the Today button, full screen, logout, the sleep timer, keyboard shortcuts in a phone-first app.
- Choose a good default instead of offering a setting nobody will change: Tapes always levels volume and keeps playing.
- Remove the path that creates an awkward state rather than designing a screen to manage it. Nothing should produce a comic without a series, so "Needs a series" went.
- No screens, settings or features that one part of an app has and its model doesn't.

### 7. Show only what applies

- Menus offer only what belongs where they're opened. Under Music, "+" rips songs and makes tapes; under Podcasts, it follows and makes shows.
- Settings appear only when they apply: an English book shows no Chinese voice settings.
- People see only what they can use, and a view hides controls that don't apply to it.
- Few options at a time; details open on request.
- Say each thing once on a page: a name or a count shown in one place isn't repeated in a label, a link and a header.
- Check the parts the browser draws, not only our CSS: date pickers, dropdown lists, a search field's ×, scrollbars, autofill, selection and the default focus ring all come out light (or near-black) on a dark page until the app says otherwise.
- A control that looks like the app's voice beats a native one when the native one speaks differently: the calendar's times are `hh:mm` text fields because the browser's time picker shows its own clock, AM/PM included.
- Keep the reader in the app. Tapping content opens it in place; links out to another site sit inside the opened item, labelled with where they go and an ↗, never on the headline that also opens it.
- Say what a tap will do: something that opens shows a quiet sign of it (a chevron that turns over). A tap anywhere on it shuts it again, with no separate Close; links and figures inside it do their own thing.
- Put the next step where the reader finishes, not only at the top: a long page ends with the way on (the previous and next edition), within thumb reach.
- Leave people where they were: Back, Forward and switching tabs and returning return to the same place and scroll position.
- Reserve an image's space before it loads, so nothing below it jumps.
- On touch screens, hover styles only under `@media (hover: hover)` (they stick after a tap), and small links keep their look but get a 44px tap area from a `::after`.
- Muted text still reaches 4.5:1 against the page it sits on.
- A figure worth reading opens on its own over the page, to zoom in place, and Back closes it.

### 8. Design for how the app is used

- Tapes replaces Spotify on an Android phone, so it's designed phone-first, for Android.
- Where the screen is the experience, use gestures instead of buttons: full screen is only the cassette.
- For long sessions, comfort comes first: the reader gets maximum space and keyboard paging.

### 9. Progress, errors and attention

- Once people have given what's needed, don't hold them up: progress shows where the result will appear.
- Things open where they were asked for and never cover unrelated content: a menu opens under its row or bar, and the centrepiece stays in view.
- Motion runs alongside a change, never as a wait before it.
- Motion is consistent and physical: parts move as if connected, nothing appears or vanishes without a cause, and longer moves take a little longer.
- Only real failures are reported: a slow job isn't announced as "stalled".
- Return people to where they were, like the last tab, and mark stale data with a quiet notice, not an alarm.
- Avoid demanding attention. Situation exists because notifications get swiped away.

### 10. Wording

- Short and literal: "Save", not "Save changes"; nothing cute.
- No repetition. A field gets a title and one hint, not a title, a label and a placeholder repeating each other; a list doesn't repeat what its heading already says.
- Name things by what they do, like Get and Downloads.
- READMEs are professional, with the right amount of detail and no filler.

---

## How design work is done

- Propose before changing anything visible, unless the change was asked for.
- Base options on how well-researched products solve the same problem, rather than on taste. Look at several:
  - design systems: Apple's Human Interface Guidelines, Google's Material Design, Microsoft Fluent, IBM Carbon, Atlassian, Shopify Polaris, and GOV.UK (for forms and wording);
  - research: Nielsen Norman Group, Baymard Institute (for forms and checkout), Laws of UX;
  - the best apps in the same field (each app's list is under [each app](#each-app)).
- Show options to compare, side by side or in separate tabs, and let the owner pick. A "make it nicer" request starts with two or three small mock-ups, never a restyle.
- Send screenshots on desktop and phone before pushing.
- If a change misses, revert it cleanly rather than stacking fixes on top.

---

## Each app

| App | Centrepiece | Accent | Best in the field, to learn from |
|---|---|---|---|
| Tapes | the cassette deck | orange | Spotify, Apple Music, Pocket Casts, Overcast |
| Calendar | the month grid | green | Fantastical, Google Calendar, Things |
| Library | the covers, lit in warm light | slate by day, gold by night | Apple Books, Kindle, Libby |
| Dashboard | the service tiles | slate blue | Linear, Vercel, Grafana |
| Situation | the world map | graphite; amber for FLASH, blue for PRIORITY | Flightradar24, the FT's and Reuters' live maps |

- **Tapes**: Gruvbox with an orange accent. The cassette's label is printed in a fixed retro palette (red, orange, mustard, brown on cream). The library borrows the cassette's construction: bars meet at seams, and lists, search and forms open as recessed slots, each level in a step darker.
- **Calendar**: a terminal logbook in Inter and IBM Plex Mono. Square corners, a tmux-style bottom bar, and messages printed as grey monospace log lines (`!` a problem, `›` news), with no colour and no boxes. Red is only for buttons that destroy something.
- **Library**: a gallery wall in warm light, with a glow, paper grain and frosted panels by day and night. Covers hang with square corners; buttons are outlines, never filled. The reader drops the light for a flat, plain page.
- **Dashboard**: an engineering blueprint in slate. Every page opens with `PageHeader.jsx`, cards share `Panel.jsx`, and row actions use `.btn-link`. Status colours are still Tailwind's green, amber and red rather than tokens.
- **Situation**: a newsroom wall: graphite glass, a frameless world map in the Patterson projection filling its panel, facts in Plex Mono and headlines in Inter. Countries in the news are tinted in their tier's colour, with no pins. Dispatch is a weekly issue in the same glass and type, set as a front page of sections.

---

## Stylesheet rules

Each Flask app (calendar, library, situation, tapes) has:

- **`tokens.css`**: every size and colour it uses (spacing, corners, type, fonts, motion, colours), with its own values;
- **`controls.css`**: its one definition of buttons and inputs;
- its own CSS for everything else, written only in its tokens.

The dashboard (React with Tailwind) keeps the same colour role names in its global CSS.

1. **No raw sizes or colours outside `tokens.css`.** That includes letter-spacing, line heights and the finger-target size: a short scale of each, so values a hair apart (0.08em beside 0.1em) can't creep in, and one rule for a small control's larger tap area rather than one per control. `tokens.css` also sets `color-scheme` to the theme's (dark or light), so what the browser draws itself (date pickers, open dropdowns, scrollbars, autofill, a search field's ×) matches.
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
