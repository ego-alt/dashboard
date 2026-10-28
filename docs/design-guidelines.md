# Design guidelines

The general principles every home-stack app follows, and how design work is done. Each app's own theme, references and stylesheet rules are in [ui-spec.md](ui-spec.md).

---

## Principles

### 1. Each app is built around one thing

Everything else serves it (see [each app](ui-spec.md#each-app)).

- Context sits beside it in drawers and side panes and never replaces it.
- Each app has its own accent, set as a hex value.
- Judge an app against its own intent, not generic conventions.

### 2. Little decoration

Details are small and exact; nothing is added for effect.

- Effects stay subtle. A loud texture, a blinking cursor or a theme laid over the controls gets cut.
- Nothing is there only for show: the bookshelf view and the deck's speaker went.
- Prefer the plain option: a plain font, a plain circle icon, a plain header.
- A small touch is fine when it's quiet and fits, like placeholder covers for books without art.

### 3. One way to do each thing

Pick one existing version as the model and match it; never build a second.

- One component per job: one dropdown, one icon set, one button style, one dialog, with the same corners throughout.
- The same kind of task looks and works the same way. Rip a link, follow a podcast, new tape and new show all use one sheet with a single field.
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

### 8. Design for how the app is used

- Tapes replaces Spotify on an Android phone, so it's designed phone-first, for Android.
- Where the screen is the experience, use gestures instead of buttons: full screen is only the cassette.
- For long sessions, comfort comes first: the reader gets maximum space and keyboard paging.

### 9. Progress, errors and attention

- Once people have given what's needed, don't hold them up: progress shows where the result will appear.
- Things open where they were asked for and never cover unrelated content: a menu opens under its row or bar, and the centrepiece stays in view.
- Motion runs alongside a change, never as a wait before it.
- Only real failures are reported: a slow job isn't announced as "stalled".
- Return people to where they were, like the last tab, and mark stale data with a quiet notice, not an alarm.
- Avoid demanding attention. Situation exists because notifications get swiped away.

### 10. Wording

- Short and literal: "Save", not "Save changes"; nothing cute.
- No repetition. A field gets a title and one hint, not a title, a label and a placeholder repeating each other.
- Name things by what they do, like Get and Downloads.
- READMEs are professional, with the right amount of detail and no filler.

---

## How design work is done

- Propose before changing anything visible, unless the change was asked for.
- Base options on how well-researched products solve the same problem, rather than on taste. Look at several:
  - design systems: Apple's Human Interface Guidelines, Google's Material Design, Microsoft Fluent, IBM Carbon, Atlassian, Shopify Polaris, and GOV.UK (for forms and wording);
  - research: Nielsen Norman Group, Baymard Institute (for forms and checkout), Laws of UX;
  - the best apps in the same field (each app's list is in [ui-spec.md](ui-spec.md#each-app)).
- Show options to compare, side by side or in separate tabs, and let the owner pick. A "make it nicer" request starts with two or three small mock-ups, never a restyle.
- Send screenshots on desktop and phone before pushing.
- If a change misses, revert it cleanly rather than stacking fixes on top.
