# Dashboard: product audit

A review of the dashboard as the front door of the home stack. It has two jobs: be the **gateway** (sign in once, then get to Library, Calendar and Music) and be the **control room** (is everything up, has it been up, are backups fine, and fix it from here when it isn't).

The look is intentional: the slate-blue drafting field, the graph-paper grid, 1px structural borders and the corner ticks on the service tiles. Nothing here asks to make it more generic. Where a finding touches the look, it asks for *more* blueprint, not less, and it's a proposal for you to decide on.

**How this was tested.** I read the whole frontend (`App.jsx`, `auth.jsx`, `api.js`, the five pages, `ServiceIcon`, `index.css`), the FastAPI routes, `docker_control.py`, `services.py`, `system_stats.py`, the backup script's status file, the compose file and the nginx config. Then I ran the real app (production build, served by `app/spa.py`) against a throwaway SQLite database and a fake Docker daemon:
- six containers with the real names and `homehub.*` labels from `docker-compose.yml`: `home-nginx`, `dashboard`, `library`, `calendar`, `music` (exited) and `mcp`;
- stats counters that climb over time, logs, and start/stop/restart that take 1.5–2 s like a real daemon;
- a backup status file from a healthy run 7 h ago;
- an admin and a non-admin user.

I walked through it in Chrome at 1440×900 and at 390×844 with touch emulation: sign-in, 2FA enrolment with a real TOTP code, API tokens, adding users with bad input, resetting a password, stopping and restarting containers, a session expiring on the Monitor page, and the non-admin view. Nothing in the repo was changed apart from this file.

**Tags:** **[confirmed]** = seen in the running app. **[code]** = from reading the code, not reproduced.

---

## 1. Core purpose: what's missing for a gateway and control room

**1.1 There is no uptime anywhere** [confirmed]
- **What:** The dashboard only knows "running" or not, right now. There's no "up 3 d", no restart count, no "down for 12 min last night", no history at all. Reloading the Monitor page is the only way to see anything, and it forgets as soon as you leave.
- **Where:** `app/docker_control.py` `_metadata_row` (reads `Created`, not `State.StartedAt`); `MonitorPage.jsx` (no uptime column); nothing samples in the background.
- **Why:** "Is it up, and has it stayed up?" is the main question a home-stack monitor answers. A container that crash-loops every hour shows "running" every time you look.
- **Fix:**
  - Show **up for** (from `State.StartedAt`, already in `container.attrs`, no extra Docker call) and **restarts** (`RestartCount`) per container.
  - Add a small background sampler in the dashboard: every minute, record each service's state (container status + health, see 1.2) into a `service_samples` table, pruned after 90 days.
  - Show a **24 h / 30 d uptime strip** per service: a row of thin ticks, one per hour or day, filled for up and hollow for down, with the uptime % beside it. It reads like a gauge on a drawing and fits the blueprint skin.
- **Status:** Done. Up for and restart count per container; a sampler records every container each minute into hourly rows (`uptime_hours`, 90 days); 24-hour strips on Monitor and 30-day strips on the Services tiles, with uptime %.

**1.2 "Running" isn't "healthy"** [code]
- **What:** Library, Calendar and Music each have a Docker `healthcheck` that hits `/healthz` every 30 s, and nginx exposes those `/healthz` routes too. The dashboard ignores both. A running container whose app is wedged shows a green dot and an open link.
- **Where:** `docker-compose.yml` healthchecks; `app/services.py` `list_services` (status = running/stopped only); `docker_control.py` (never reads `State.Health.Status`).
- **Why:** The common failure for a Flask app isn't a stopped container, it's one that's up but returns 502s.
- **Fix:** Read `State.Health.Status` (`healthy` / `unhealthy` / `starting`) from the same attrs. Use three states everywhere: **up**, **degraded** (running but unhealthy or starting), **down**. The sampler in 1.1 records the same thing.
- **Status:** Done. Docker health is read from the same inspect data: up, degraded (running but unhealthy) and down everywhere, with "starting" shown while a healthcheck hasn't passed yet.

**1.3 Services gives no glance answer** [confirmed]
- **What:** The landing page is three tiles and a lot of empty grid. To learn whether the host is fine or last night's backup ran you have to go to Monitor. The tiles never refresh: a service that goes down while the page is open still shows "running".
- **Where:** `HomePage.jsx` (one fetch on mount, no host or backup data).
- **Why:** The gateway is the page you see every day. It should tell you in one line whether anything needs you, and otherwise get out of the way.
- **Fix:**
  - A single **status line** under the heading, in the drafting-annotation style: `ALL SYSTEMS NOMINAL · backup 7 h ago · disk 6 %`, or `MUSIC DOWN 12 min · backup stale` in danger colour. Admins only for host/backup parts.
  - Each tile shows its uptime strip from 1.1 and refreshes every 30 s while visible.
- **Status:** Done. One status line under the heading (services, last backup and fullest disk for admins), in danger colour when something needs you; tiles refresh every 30 s.

**1.4 You can't start a stopped container** [confirmed]
- **What:** An exited container offers **Stop** and **Restart**. There's no Start, although `POST /containers/{id}/start` exists. Clicking Stop on the exited `music` container asks "stop container "music"? This affects the running service." and then reports nothing. Restart does happen to start it, but you have to guess that.
- **Where:** `MonitorPage.jsx` action buttons; `app/main.py` start route (unused by the UI).
- **Why:** Bringing a stopped service back is the single most likely thing you'll do from the control room.
- **Fix:** Show **Start** for stopped containers and **Stop · Restart** for running ones. Also let admins start a stopped service from its Services tile (see 5.1).
- **Status:** Done. Start for stopped containers, Stop and Restart only for running ones.

**1.5 Logs exist but you can't see them** [code]
- **What:** `GET /containers/{id}/logs` returns the last N lines, and the MCP server uses it, but there's no way to read logs in the UI. When something's wrong, the next step is SSH.
- **Where:** `app/main.py` logs route; `MonitorPage.jsx`.
- **Why:** Seeing *why* a service is down is half of fixing it from the dashboard.
- **Fix:** Click a container name to open a **logs drawer** (right side, same pattern as the calendar's side panes): the last 200 lines in monospace, newest at the bottom, with Refresh and a "follow" toggle that polls every few seconds. Errors and warnings tinted.
- **Status:** Done. Click a container (or Logs) for a right-hand drawer with the last 200 lines, local times, errors and warnings tinted, Refresh and Follow. `?logs=<name>` opens it.

**1.6 No alert when something goes down** [code]
- **What:** If Music dies at 2 am, you find out when you next open Tapes.
- **Where:** none.
- **Why:** A monitor that only works while you're watching it is a status page.
- **Fix:** Optional, after 1.1: when the sampler sees a service go down for 3+ minutes, or a backup go stale, send one push (ntfy.sh or a self-hosted ntfy container is the simplest; it works on Android with no app of your own). One message on down, one on recovered.
- **Status:** Open (runner-up).

---

## 2. Missing states

**2.1 Opening /users directly shows raw JSON** [confirmed]
- **What:** Refreshing the Users page, or opening a bookmark to it, shows the JSON user list instead of the page. In production it's the same: nginx sends `/` to the dashboard, and FastAPI's `GET /users` API route wins over the SPA fallback.
- **Where:** `app/main.py` `@app.get("/users")` vs the SPA route `/users` in `App.jsx`; `app/spa.py`.
- **Why:** It looks broken, and it's the page you'd most likely bookmark as an admin.
- **Fix:** Rename the SPA route to `/admin/users` (and Monitor to `/admin/monitor` for symmetry), or move the API under `/api/…`. The first is the small change; keep `/users` → redirect for old bookmarks. Update `SPA_PATHS` in `LoginPage.jsx` and the MCP client if routes move.
- **Status:** Done. Pages moved to `/admin/monitor` and `/admin/users`; `/monitor` and `/users` redirect (the server sends browser visits to `/users` to the page).

**2.2 A stale Monitor looks live** [confirmed]
- **What:** When the session expired, both cards showed *"not authenticated"* in red, but the table kept its last numbers and both toggles still said **● Live** in green. Nothing sent me to sign in.
- **Where:** `MonitorPage.jsx` `load` / `HostSection` error handling; `api.js` (no 401 handling).
- **Why:** For a monitor, stale numbers presented as current are worse than no numbers.
- **Fix:**
  - On any 401 from `apiJson`, refresh auth and send the user to `/login?next=…`.
  - On other errors, dim the table, change the toggle to **● Stale · 2 min** in amber/danger, and keep retrying.
  - Show "updated 3 s ago" next to the toggle so freshness is always visible.
- **Status:** Done. Any 401 sends you to sign in. Monitor shows "updated 3 s ago", and on errors dims the data and turns the toggle into a red Stale with the age of the last update.

**2.3 Docker unreachable reads as "no services"** [code]
- **What:** If the dashboard can't reach the Docker socket, `/services` returns `[]` and the page says *"No services discovered. Add homehub.\* labels to a container in docker-compose.yml."*
- **Where:** `app/services.py` `list_services` (catches every exception, returns []).
- **Why:** It sends you to edit your compose file when the real problem is the daemon or the socket mount.
- **Fix:** Return a 503 with a reason from `/services` when Docker fails, and show *"Can't reach Docker on the Pi. Service links still work."*; still render the tiles from the last known list (cached in memory) so the gateway keeps working.
- **Status:** Done. `/services` returns 503 with the last known tiles; the page says Docker can't be reached and the links keep working. `/containers` returns 503 too.

**2.4 No action feedback** [confirmed]
- **What:** After confirming Stop, the button just sits there until Docker answers (up to 10 s on a real stop). Restart likewise. Nothing says it's working, and you can click again.
- **Where:** `MonitorPage.jsx` `action`.
- **Why:** You can't tell a slow stop from a click that didn't register.
- **Fix:** Disable the row's buttons and show **stopping…** / **restarting…** in the status cell until the call returns, then a short confirmation line ("calendar restarted").
- **Status:** Done. The row shows starting… / stopping… / restarting…, buttons disable, and a short result line follows.

**2.5 Loading states differ per page** [confirmed]
- **What:** Services shows a bare "Loading…", Users "Loading users…", Monitor a mix of "Loading…", "Loading containers…" and "…" in cells. The whole app flashes a centred "Loading…" on every auth refresh (see 4.1).
- **Where:** each page.
- **Fix:** One skeleton per card: the card's frame and heading drawn immediately with dashed placeholder lines, which suits the drafting look.
- **Status:** Partly. The full-page "Loading…" flash on every auth refresh is gone; per-card skeletons are not done.

---

## 3. Inconsistency within the app

**3.1 Two different skins in one app** [confirmed]
- **What:** Services tiles have the blueprint corner ticks and hover glow. Monitor, Users, Settings and Login are plain dark cards with Tailwind pills. Headings come from three different class sets (`bp-heading` on Services, ad-hoc `text-lg font-semibold` elsewhere). The `bp-label` class is used in three places but is never defined. The Login page covers the grid with a flat fill, so the front door is the least blueprint page of all.
- **Where:** `index.css`; every page; `LoginPage.jsx` root `bg-[var(--color-bg-inset)]`.
- **Why:** The aesthetic is strong on one page and missing on the rest, so it reads as a template with a themed home page.
- **Fix (proposal, your call):** Define the blueprint vocabulary once and use it everywhere:
  - `bp-label`: small monospace uppercase with letter-spacing, for table headers, metric labels, card captions ("CPU", "LAST RUN"), like annotations on a drawing.
  - Card headings as title-block captions: name on the left, a mono reference on the right (`HOST · pi5`, `CONTAINERS · 6`).
  - Corner ticks on every card (static, no glow), glow only on clickable ones.
  - Login on the grid, with the card as a small title block.
- **Status:** Open (declined for now).

**3.2 Status colours are off-palette** [confirmed]
- **What:** Status uses Tailwind `green-500`, `emerald-300`, `amber-500`, `red-500`, `slate-400`, chosen per page (Settings' "Enabled" is emerald, Monitor's "running" is green). The token file has accent and danger but no success or warning.
- **Where:** `HomePage.jsx` `STATUS`, `MonitorPage.jsx`, `SettingsPage.jsx`; `index.css` tokens.
- **Fix:** Add `--color-ok`, `--color-warn` (and reuse `--color-danger`) to the tokens, tuned to the slate-blue field, and use them for every dot, pill, bar and banner.
- **Status:** Open (declined for now).

**3.3 "Stopped" means different things** [confirmed]
- **What:** Services says **stopped** in amber; Monitor says **exited** in grey for the same container.
- **Fix:** One vocabulary across both pages: **up / degraded / down** (1.2), with Docker's raw state in a tooltip on Monitor.
- **Status:** Done. Up / degraded / down on both pages, with Docker's raw state in a tooltip on Monitor.

**3.4 Controls and shapes vary** [confirmed]
- **What:** Buttons are 8px-rounded, cards 4px, pills fully round. Backups' **Refresh** is a filled primary button, the loudest thing on the Monitor page, for a nightly job. Confirmations use the browser's `confirm()` and `prompt()`.
- **Fix:** Square-ish 2–4px everywhere (drafting), primary fill only for the one main action of a form, and a small in-app confirm popover for destructive actions (see 4.3).
- **Status:** Open (declined for now).

**3.5 Naming** [confirmed]
- **What:** The brand is "Home", the nav says "Settings" but the page says "Account settings", the tab title is "Home" on every page, and the favicon is Vite's default logo.
- **Where:** `App.jsx`, `index.html`, `public/vite.svg`.
- **Fix:** Per-page titles ("Monitor · Home"), a small blueprint-style favicon (a house in single-line drafting strokes, or a grid square with a tick), and nav and heading matching.
- **Status:** Open (declined for now). The heading now matches the nav ("Settings").

---

## 4. Fragility

**4.1 Turning on 2FA never shows the recovery codes** [confirmed]
- **What:** After entering a valid code, the page jumped straight to "Enabled · To turn 2FA off…". The one-time recovery codes were never shown. They're generated server-side and returned, but `refresh()` sets the user to `undefined`, `RequireAuth` swaps the page for "Loading…", the Settings page unmounts and its `recoveryCodes` state is thrown away.
- **Where:** `SettingsPage.jsx` `onConfirmEnable` (`setRecoveryCodes` then `await refresh()`); `auth.jsx` `refresh` (`setUser(undefined)`).
- **Why:** Lose the phone and you're locked out of the whole stack, with only the CLI on the Pi as a way back. This is the most serious bug found.
- **Fix:** Make `refresh()` keep the current user while it re-fetches (only the first load should show "Loading…"). That also removes the full-page flash in 2.5. Add a test that the codes are visible after enabling. Also offer **Copy** and **Download .txt** for the codes.
- **Status:** Done. `refresh()` keeps the user on screen; the codes show with Copy and Download .txt.

**4.2 No way to change your own password** [code]
- **What:** There's no "change password" for a signed-in user. Admins can set anyone's password from Users; a non-admin can't change theirs at all; an admin changing their own goes through the same `prompt()`.
- **Where:** `app/main.py` (no self-service route); `SettingsPage.jsx`.
- **Fix:** A **Password** card at the top of Settings: current password, new password, with the existing length and HIBP checks, and "sign out other sessions" ticked by default.
- **Status:** Done. A Password card at the top of Settings, with "sign out my other devices" ticked by default.

**4.3 Admin password reset is a plain-text prompt** [confirmed]
- **What:** **Password** opens `window.prompt`, which shows the new password in clear text, can't be pasted from a generator with confirmation, and gives no strength or breach feedback until after submit.
- **Where:** `UsersPage.jsx` `resetPassword`.
- **Also** [code]: setting a new password doesn't end the user's existing sessions (`set_user_password_endpoint` only updates the hash), so resetting a password after a lost phone leaves that phone signed in.
- **Fix:** An inline row form with a masked field, a "generate" button, the HIBP check, and a clear success line. Revoke the user's other sessions when their password is set.
- **Status:** Done. An inline masked form with Generate and Show; setting a password ends that user's sessions (yours survives).

**4.4 One click changes a role** [confirmed]
- **What:** The Admin checkbox in the table promotes or demotes a user instantly, with no confirmation and no undo message.
- **Where:** `UsersPage.jsx` `toggleAdmin`.
- **Fix:** Confirm promotions ("Make Sam an admin? They'll be able to stop containers and manage users."), and show a short "Sam is now an admin · Undo" line.
- **Status:** Done. Promotions ask first; every role change shows a line with Undo.

**4.5 No way to see or end sessions** [code]
- **What:** Sessions (`UserSession`) and sign-ins (`LoginEvent`) are stored server-side, but you can't see where you're signed in or sign out a lost phone. Deleting the user is the only way to end their sessions from the UI.
- **Fix:** A **Sessions** card in Settings: device (from user agent), last seen, "this device", and **Sign out** per session plus "sign out everywhere else". The recent sign-ins from `LoginEvent` (including failed ones) fit underneath.
- **Status:** Done. "Where you're signed in" lists sessions (device, address, last seen) with Sign out and Sign out all other devices, plus recent sign-ins.

**4.6 Disable-2FA is always open** [confirmed]
- **What:** Once 2FA is on, the card's only content is a code field and a filled red **Disable 2FA** button.
- **Fix:** Show the state ("On since 16 Oct · 8 recovery codes left") with **Regenerate recovery codes** and a quiet **Turn off…** link that reveals the code field.
- **Status:** Done. Shows the codes left (amber at 2 or fewer), **New recovery codes** (needs an authenticator code), and a quiet **Turn off…**.

---

## 5. Friction

**5.1 A stopped service is a dead end** [confirmed]
- **What:** A stopped tile is greyed with a not-allowed cursor. As an admin you have to go to Monitor, find the row and press Restart.
- **Fix:** For admins, a stopped/degraded tile shows **Start** (or **Restart**) and **Logs** right on the tile. Non-admins get *"Music is down. Ellery has been told."* if alerts (1.6) exist, or just "down since 02:14".
- **Status:** Done. Admins get Start and Logs on a down tile, Logs on a degraded one.

**5.2 Adding a household member needs SSH** [code]
- **What:** After adding a user in the dashboard, the READMEs say to run `scripts/sync_household_users.py` on the Pi so Library, Calendar and Music know them.
- **Where:** `README.md`; `scripts/sync_household_users.py`.
- **Fix:** Either have each app create its shadow user on first authenticated request (nginx already passes the username), or run the sync from the dashboard after a user is created or deleted. The first removes the step entirely.
- **Status:** Open (runner-up).

**5.3 Container table order is arbitrary** [confirmed]
- **What:** Rows come in Docker's order. A stopped container sits mid-table.
- **Fix:** Problems first (down, then degraded), then services, then infrastructure (`home-nginx`, `dashboard`, `mcp`) in a quieter group.
- **Status:** Done. Down, then degraded, then hub services, then infrastructure.

**5.4 Validation only after submit** [confirmed]
- **What:** Adding a user with a 1-character password or "Bad Name!" as a username only fails after submit, with a lowercase server message above the form.
- **Fix:** Show the rules under the fields (username: lowercase letters, numbers, dashes; password: 8+ characters) and validate as you type.
- **Status:** Partly. The password fields say "8+ characters" and the buttons wait for 8; the add-user form still validates on submit.

---

## 6. Copy

[confirmed] unless noted.

**Status:** Partly. Confirm dialogs are sentences that fit the action, server messages are shown as sentences, CPU shows one decimal or `<0.1 %`, and 2FA reads On/Off. The backup card and service descriptions are unchanged.
- Confirm dialogs start lowercase: *"stop container "music"? This affects the running service."* (the verb is passed in raw). Also says "running service" for a stopped one.
- Server messages are shown as-is: *"not authenticated"*, *"password must be at least 8 characters"*. Give them sentence case and a next step ("Your session ended. Sign in again.").
- Backups: *Duration 241s* → *4 min 1 s*; *Last run 7h ago* → *7 h ago · 02:00*; the stale message says *"check the timer on the Pi"*, which could name the unit (`home-stack-backup.timer`).
- Services descriptions come from labels and still say *"Mood tracker + events"* for the calendar, which is now a diary, and *"Cassette-deck streaming"* for Tapes, which is called Music on the tile. Update the labels in `docker-compose.yml`.
- *CPU %* shows raw values like `69.57` and `0`; round to one decimal and show `<0.1` instead of `0`.
- API tokens: an unnamed token is called *"API token"*; the token warning is a yellow block (off-palette, see 3.2).

---

## 7. Mobile (390 px, touch)

**7.1 Monitor actions are off-screen** [confirmed]
- **What:** At 390 px the container table is 606 px wide inside a 356 px card. RX/TX and the Stop/Restart buttons are only reachable by sideways scrolling, which nothing hints at.
- **Fix:** Below 640 px, render each container as a compact card: name and state on one line, CPU · memory · uptime on the next, actions as a ⋯ menu. The uptime strip spans the card.
- **Status:** Done. Below 640 px each container is a card: name and state, uptime, the 24-hour strip, CPU and memory, actions.

**7.2 Services tiles are tall** [confirmed]
- **What:** Each tile is ~140 px tall with a large icon, so three services fill the phone screen; with more services, the gateway becomes a scroll.
- **Fix:** On phones, a two-column grid of compact tiles (icon, name, state dot), or one-line rows.
- **Status:** Open.

**7.3 Top bar takes two rows** [confirmed]
- **What:** Brand and account on one row, nav on a second: ~100 px of chrome.
- **Fix:** One row on phones, with nav as a bottom bar (matches the tmux-style bar in Calendar) or a compact segmented control.
- **Status:** Done. One row on top; the nav is a bottom bar on phones.

**7.4 Users table on phones** [code]
- Same horizontal-scroll problem as 7.1 (I couldn't screenshot it because of 2.1). Same card treatment.
- **Status:** Done. Users are cards on phones, with the password form inline.

---

## 8. Speed and feel

**8.1 It's fast** [confirmed]
- The Monitor table renders in about 0.2 s, and the second sample fills CPU and rates after 1 s. Polling pauses for hidden tabs and skips overlapping requests. Nothing to fix here.

**8.2 Host stats block for half a second** [code]
- `psutil.cpu_percent(interval=0.5)` sleeps 0.5 s on every poll in a worker thread. Fine for one viewer; use `interval=None` with a primed first call (or reuse the sampler from 1.1) so it returns instantly.
- **Status:** Done. The CPU read is instant (measured since the previous call).

**8.3 Inter comes from Google Fonts** [code]
- The gateway depends on fonts.googleapis.com. When the internet is down but the LAN is fine, which is exactly when you'd open the dashboard, it falls back to Arial. Self-host the font in `public/`.
- **Status:** Open (runner-up).

**8.4 Keyboard** [code]
- No shortcuts. Small wins: `g s` / `g m` / `g u` to switch pages, `r` to refresh, `l` to toggle live, `?` for the sheet, as in Tapes and Calendar.
- **Status:** Open (runner-up).

---

## Found while fixing

**QR code never displayed** [confirmed]
- **What:** The 2FA setup QR was blank. The server rendered it with `qrcode`'s `SvgImage`, which writes namespaced `svg:rect` elements and no `viewBox`; inserted into the page's HTML, nothing draws. Black modules on the dark card would have been invisible anyway. Enrolment only worked through "Can't scan? Show secret".
- **Status:** Done. `SvgPathImage` (one path with a viewBox) on a white tile; a test checks the SVG's shape, and the screenshot decodes.

**"You" was never recognised on Users** [confirmed]
- **What:** `/me` didn't return the user's id, so Users never marked your own row: no "· you", and Delete and the admin checkbox weren't disabled for yourself (the server still refused).
- **Status:** Done. `/me` returns `id`.

---

## Top 10, ranked by how much better the app will feel

| Rank | Fix | Section | Size | Status |
|---|---|---|---|---|
| 1 | **Show the recovery codes:** keep the user while `refresh()` re-fetches so Settings doesn't unmount; Copy/Download for the codes; a test | 4.1, 2.5 | **Small** | Done |
| 2 | **Uptime and health:** up-for and restart count per container, Docker health as up/degraded/down, a background sampler, and a 24 h / 30 d tick strip per service | 1.1, 1.2, 3.3 | **Large** | Done |
| 3 | **Fix the Monitor controls:** Start for stopped containers, Stop/Restart only when running, pending state and a result line, problems sorted first | 1.4, 2.4, 5.3 | **Small** | Done |
| 4 | **Routes that survive a refresh:** move SPA pages to `/admin/users` and `/admin/monitor` (or the API under `/api`), redirect the old paths | 2.1 | **Small** | Done |
| 5 | **Honest freshness:** 401 → sign in; on errors dim the data and show "Stale"; "updated 3 s ago"; Docker-down message instead of "no services" | 2.2, 2.3 | **Small** | Done |
| 6 | **Services as a status page:** one status line (all nominal / what's wrong, backup age, disk), tiles that refresh, admin Start/Logs on a down tile | 1.3, 5.1 | **Medium** | Done |
| 7 | **Logs drawer:** click a container to read its last 200 lines, with follow | 1.5 | **Medium** | Done |
| 8 | **Your own account:** change password, sessions list with sign-out, 2FA card with regenerate codes, admin reset as a masked inline form, confirm role changes | 4.2–4.6 | **Medium** | Done |
| 9 | **One blueprint vocabulary (proposal):** define `bp-label`, title-block card headings, ticks on every card, Login on the grid, status colour tokens, squarer controls, a real favicon | 3.1, 3.2, 3.4, 3.5 | **Medium** | Not doing for now |
| 10 | **Phone layout for Monitor and Users:** container and user cards instead of wide tables, a one-row top bar | 7.1, 7.3, 7.4 | **Medium** | Done |

**Close runners-up:**
- Down/recovered push alerts via ntfy (1.6, medium, after 2).
- No SSH step to add a household member (5.2, small to medium).
- Copy pass, including the outdated service descriptions (6, small).
- Self-hosted Inter and an instant host-stats read (8.2, 8.3, small).
- Keyboard shortcuts with a `?` sheet (8.4, small).
