# Dashboard roadmap

What's left to do for the dashboard, the stack around it and the MCP server. The audits it came from (October 2026) are in git history; everything else from them is done.

A trusted Tailscale certificate was tried and reverted in October 2026: the stack is reached by IP address, which no public certificate can cover, and the ts.net name is too clunky to use instead.

**The stack contract** ([APPS.md](APPS.md#the-contract))
- **Only nginx and `mcp` may say who the user is.** The apps trust `X-Forwarded-User` from anything on the compose network, so a compromised container (Tapes runs yt-dlp on any link) could call Calendar as you. Fix: the apps require `X-Internal-Auth` to equal `INTERNAL_AUTH_SECRET` when it's set; nginx sends it from an envsubst template (`nginx/templates/` instead of a static `conf.d` mount); `mcp` already sends it.
- **Tapes and Situation don't fail safe on their own.** Without the header, Tapes lets anyone in as one local user and Situation has no sign-in at all.
- **Which apps each user may open,** decided in `/auth/verify` (it already knows which app a request is for), so the apps never need to know.

**Security**
- **Server-side fetches from Tapes.** Adding a podcast or a download link makes the Tapes container fetch any URL, including `http://dashboard:8000/…` or other LAN hosts, and an assistant can be talked into it by text in a feed. Fix: resolve the host and refuse loopback, private, link-local and compose-network addresses, in the feed reader and before queueing a rip.
- **API tokens never expire and can do everything.** Add an optional expiry and a read-only scope, and link Settings to `/oauth/connections`.
- **One call can queue up to 500 rips** (a playlist link). Cap it per call, around 100, and say so.

**MCP**
- **List the trash,** so "bring back what I deleted" can find it: `GET /events/trash`, `/api/tracks/trash`, `/books/trash` and three list tools.
- **More tools from endpoints that exist:** fetch or mark a podcast episode played, reorder a tape, calendar photos and their captions (read-only).
- **Add many songs to a tape in one call** (the endpoint takes one `track_id`), and add a book from a link (with the host check above).
- **A "no notes" read mode** per connection, if diary text shouldn't reach a model vendor.
- Not rechecked since the October audit: removing a tag from its last book may leave the tag offered in autocomplete.

**Monitoring**
- **Down and recovered alerts.** When a service is down for 3+ minutes, or the backup goes stale, send one push (ntfy is the simplest; it works on Android), and one when it recovers. Builds on the uptime sampler.

**Feel**
- **Loading skeletons**: each card drawn straight away with placeholder lines, instead of "Loading…".
- **Keyboard shortcuts** like the other apps: `g s` / `g m` / `g u` to switch pages, `r` refresh, `l` live, `?` for the list.

**Copy**
- The backup card: `241s` → `4 min 1 s`, and the time of day next to "9 h ago".
- Service descriptions in `docker-compose.yml` labels are out of date ("Mood tracker + events" for what is now a diary).
- Add-user form: show the rules (username characters, 8+ character password) and check them as you type.

**Users**
- Run `scripts/sync_household_users.py` automatically after adding or deleting someone, rather than by hand (apps already create accounts on first visit, so this is only about having them ready).

**Blueprint look** (set aside for now)
- One vocabulary everywhere: small monospace annotation labels, title-block card headings, corner ticks on every card, the Login page on the grid.
- Status colours as tokens (`--color-ok`, `--color-warn`) instead of Tailwind's green, amber and red.
- A real favicon (it's still Vite's) and per-page tab titles ("Monitor · Home").
