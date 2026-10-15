# MCP server: audit and missing endpoints

**Date:** 2026-10-15

**Scope:**
- the new `homehub-mcp` server (tools, OAuth, deployment);
- every app endpoint it relies on;
- what an assistant still can't do.

**Status key:** **Fixed** means done in this pass, on the branches listed in §5.
**Open** means a recommendation, not yet done.

**Severity key:**
- **H** = could expose or lose data;
- **M** = a real gap or risk with a workaround;
- **L** = polish.

---

## 1. Decisions still yours

**1.1 Cloud clients (claude.ai, ChatGPT) can't reach `home.local`.** *(Open, M)*

These clients call MCP servers from the vendor's servers, so they need a
public route.

Options:
- **(a)** Tailscale Funnel or a Cloudflare Tunnel that exposes **only** `/mcp`,
  `/authorize`, `/token`, `/register`, `/revoke`, `/.well-known/oauth-*` and
  `/oauth/*`;
- **(b)** stay LAN/Tailscale-only and use desktop or local clients.

Everything already works for (b). For (a), set `MCP_PUBLIC_URL` to the public
origin; the OAuth issuer follows from it.

Recommendation: (b) until you actually want phone ChatGPT. If you do take (a),
keep the dashboard and the apps off the tunnel.

**1.2 Diary text reaches the model vendor.** *(Open, M, inherent)*

Notes, people and places are returned to whichever model the client uses.
Today that is all-or-nothing per connection. A "no notes" read mode per grant
would be a small addition if you want one.

---

## 2. Fixed in this pass

| # | Sev | Where | Finding | Fix |
|---|---|---|---|---|
| 2.1 | **H** | library | A standard user could read or **change** a restricted book: metadata GET/POST, bookmark, mark-finished, cover and **cover upload** all resolved any book by filename with no access check. The listings hid such books, but these endpoints didn't. | `get_accessible_book_or_404`: restricted books answer 404 to non-admins, so a filename can't be probed for. 13 regression tests. |
| 2.2 | M | dashboard | Login ignored `next=` for anything outside the SPA. After signing in on the way to `/calendar/` (or the new `/oauth/consent`) you landed on the hub, because React Router "navigated" to a page it doesn't serve. `next` also wasn't checked for `//other-host` (an open-redirect shape). | `safeNext()` accepts only same-origin paths. Non-SPA paths get a full page load. |
| 2.3 | M | calendar | No way to fetch one entry or moment by id. | `GET /events/<id>`, `GET /events/subevents/<id>` |
| 2.4 | M | calendar | No range listing (only per day / per month). | `GET /events/range?from&to` (inclusive, ≤ 366 days) |
| 2.5 | M | calendar | Creating a moment didn't return its id. | The id is now in the response. |
| 2.6 | M | calendar | An entry with moments could not be moved by any API client. The entry may not strand its moments, and a moment may not leave its entry first: a deadlock. | `move_moments: true` on `PUT /events/<id>` shifts the moments with the start. |
| 2.7 | M | tapes | No server-side track search; the deck filters in the browser. | `GET /api/tracks?q=&limit=` (word-wise across title, artist and album; max 100) |
| 2.8 | M | library | Author-only lookups (`/books?author=Herbert`) could never match: with no title the score tops out at 0.3, under the 0.6 cutoff. | With no title, the author carries the whole score. |
| 2.9 | L | MCP | Flask's stock 404 text ("The requested URL was not found…") is meaningless to a model. | The backend maps it to "Not found." |

---

## 3. Open findings

### Security

**3.1 Any container on the compose network can act as any user.** *(M)*

The apps trust `X-Forwarded-User` from anything that can reach them. Only
nginx and now `mcp` should. The ports are only `expose`d, so this is
container-to-container only, but a compromised `music` (which runs yt-dlp on
arbitrary links, see 3.2) could call the calendar as you.

Fix:
1. The apps require `X-Internal-Auth == INTERNAL_AUTH_SECRET` alongside the
   user header, when that variable is set.
2. nginx sends it, using an envsubst template. This needs the
   `nginx/templates/` layout instead of a static `conf.d` mount.
3. `mcp` already sends it when the variable is set (tested).

**3.2 Blind SSRF from tapes.** *(M)*

`tapes_add_podcast` and `tapes_download` make the tapes container fetch any
URL, including `http://dashboard:8000/…` or other LAN hosts. This was already
reachable from the UI. An assistant makes it reachable from prompt-injected
text as well (3.3).

Fix: in `podcasts.parse_feed` and the feed refresh, resolve the host and refuse
loopback, private, link-local and compose-network addresses. yt-dlp is harder
to fence; the simplest guard is the same host check before queueing.

**3.3 Third-party text reaches the model.** *(M, inherent to agents)*

Tool results include text that you didn't write:
- podcast and episode titles from RSS feeds;
- track titles from YouTube metadata;
- book metadata from EPUBs.

A malicious feed could carry instructions aimed at the assistant, which holds
delete tools.

What limits the damage:
- assistants have **no delete tools** (removed 2026-10-15), so the worst an
  injected instruction can do is add or edit, and edits are visible;
- the activity log at `/oauth/connections` shows what ran.

Remaining exposure:
- edits can overwrite diary notes or rename shared tracks;
- 3.2 (server-side fetches).

**3.4 Consent phishing.** *(L)*

Anyone on the network can register a client called "Claude" and send you its
consent link. Approving would send a code to *their* redirect URI. The consent
page shows the redirect host for this reason ("you'll be returned to …"), and
`/register` is rate-limited.

Only approve connections you started yourself.

**3.5 Dashboard API tokens are permanent and full-scope.** *(L)*

A pasted token never expires and can do everything the user can. Within 60
seconds of revocation it stops working at the MCP server (the PAT cache).

Recommendation:
- optional expiry;
- a read-only scope (the MCP tool annotations already make that a filter);
- a "Connected apps" link from Settings to `/oauth/connections`.

### Data safety

**3.6 Deleting a playlist is permanent.** *(L, app-only now)*

It's the only delete with no trash. Assistants can no longer delete anything,
so this only affects the music app's own UI.

Fix: soft-delete playlists like tracks (`deleted_at` + restore).

**3.7 No way to list the trash.** *(M)*

Restores need the id. Deletes now happen in the apps, so an assistant asked to
"bring back what I deleted" has no way to find it.

Fix: `GET /events/trash`, `GET /api/tracks/trash`, `GET /books/trash`, plus
three small list tools.

**3.8 `tapes_update_track` edits the shared library for everyone, for any
signed-in user.** *(L)*

Track delete is admin-gated (`TAPES_ADMINS`), but rename isn't. The app UI has
the same rule, so this is a policy question rather than an MCP one.

**3.9 One call can queue up to 500 rips.** *(L)*

A playlist link expands to up to 500 jobs, with no per-user queue cap.

Fix: cap per call (e.g. 100) and say so in the tool's error.

### Correctness and polish

**3.10 Orphan tags in the library.** *(L)*

Removing a tag from its last book leaves the tag row, so `/tags`, and the
autocomplete, keep offering it. Found during the live run ("Fave" lingered).

**3.11 First calendar write after a cold start can block for minutes.** *(L)*

If the search model isn't cached and warm-up is off, the first write downloads
the embedding model. Production has `SEARCH_WARMUP` on by default; it was seen
only in the throwaway test instance.

**3.12 Self-signed TLS.** *(L, docs)*

Remote-HTTP clients reject the home cert unless it is trusted
(`NODE_EXTRA_CA_CERTS` for Node-based clients). stdio sidesteps this with
`HOMEHUB_CA`. A Tailscale cert would fix it everywhere.

---

## 4. Missing endpoints: what an assistant still can't do

| Want | Status | Needs |
|---|---|---|
| Add a book from a link | missing | `POST /upload_book` takes multipart only. A `{url}` variant would fetch the EPUB (with the 3.2 host check). |
| Calendar photos (list, caption) | endpoints exist, not exposed | `GET /attachments` gives captions; uploading binary over MCP is poorly supported across clients, so read-only tools first. |
| Play or download a podcast episode | endpoint exists, not exposed | `POST /api/podcast/episodes/<id>/play` queues the download; a `tapes_fetch_episode` tool is a 10-line add. |
| Mark an episode played | endpoint exists, not exposed | `POST /api/podcast/episodes/<id>/played` |
| Reorder a playlist | endpoint exists, not exposed | `PUT /api/playlists/<id>/order` |
| Add many songs to a playlist in one call | missing | `POST /api/playlists/<id>/tracks` takes one `track_id`; the tool loops. Accept `track_ids[]`. |
| One download's status | missing | Only the whole panel list exists; fine at home scale. |
| List the trash (to restore from it) | missing | 3.7 |
| Delete anything | removed on purpose | Deleting stays in the apps (3.3). |
| "Find me this song online" | out of scope | Tapes rips links. The assistant brings its own web search. |
| Calendar export | exists, not exposed | A zip download; not useful through a chat client. |

---

## 4b. Request path and efficiency

**Tool calls don't pass through the dashboard.**

*Remote (`/mcp`):* client → nginx → `mcp` container → app, direct on the
compose network.
- An OAuth token is checked in the container's own SQLite. That is one indexed
  lookup with no dashboard hop, plus a "last used" write at most once a minute.
- A dashboard API token is checked with the dashboard's `/auth/verify`, cached
  for 60 s.
- The dashboard is only on the path for sign-in and the consent page.

*Local (stdio):* laptop → nginx → `auth_request` to the dashboard → app, on
every app call. That's how the token is checked without the apps knowing about
tokens.

Changes in this pass:

| Where | Before | After |
|---|---|---|
| dashboard `lookup_api_token` | a SQLite **write** (`last_used_at`) on every request with a token, i.e. every app call in stdio mode | at most one write per token per minute, like sessions' sliding expiry |
| `calendar_create_entry` | POST, then GET to read it back | POST only; the result is built from what the app accepted |
| `calendar_update_entry` | GET, PUT, GET | GET (needed to merge), PUT |
| `library_get_book` | two GETs in a row | two GETs in parallel |
| `library_update_book` | GET, POST, GET | GET, POST; reads back only when shared fields (title, author, genre) were sent, to report the admin-only rule |
| `tapes_get_playlist` | fetched the **whole catalogue** for "all", then showed 80 | `?limit=81`, applied in SQL (new, optional on the tapes endpoint) |

Already efficient:
- one pooled HTTP client per process (keep-alive to each app);
- stateless HTTP, with no per-session server state;
- tool list built once.

Still open (L):
- `tapes_add_to_playlist` makes one request per song, because the endpoint
  takes one `track_id` (§4);
- in stdio mode the `auth_request` hop stays. nginx could cache it, but the
  throttled write was the real cost.

---

## 5. What changed, and how it was checked

**Branches** (nothing merged; merging `master`/`main` deploys):

| Repo | Branch | Commits |
|---|---|---|
| calendar | `mcp-endpoints` | entry/moment GET + range + moment id; `move_moments` |
| tapes | `mcp-endpoints` | `GET /api/tracks?q=` |
| library | `mcp-endpoints` | restricted-book access fix; author-only matching |
| dashboard | `mcp-server` | `mcp/` package, compose service, nginx routes, CI job, deploy step, login `next` fix, docs |

**Tests:**
- **App suites:** calendar 95, tapes 38, library 202, dashboard 100, all passing.
- **MCP suite:** 37 tests, all passing; ruff is clean.
  - It drives the real HTTP app end to end: discovery, registration
    (redirect-URI rules), consent (same-site bounce, login redirect, CSRF,
    deny), PKCE, single-use codes, refresh rotation, revoke, API-token
    fallback, audit.
  - It also checks per-tool logic against fake apps:
    - partial updates keep untouched fields;
    - moving keeps the length and moves the moments;
    - tags merge;
    - the marker is never exposed;
    - schemas are flat.

**Live run** against all three real apps:
- **Setup:** each app ran in proxy mode with throwaway data, behind the full
  OAuth flow.
- **Coverage:** every tool was exercised, plus as a standard user via an API
  token. That run confirmed that restricted books stay hidden, delete is
  refused and each user's diary is separate.
- **Result:** 0 failures.
- **stdio:** a smoke test through a stand-in for nginx, with a bad token
  giving a readable error.

**Not verified here:**
- the Docker image build;
- nginx in a container (no Docker on this Mac; the config was parsed with
  `crossplane`);
- the dashboard frontend build (local Node is v11). CI builds it.
