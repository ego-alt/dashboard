# Dashboard roadmap

Left over from the product audit (October 2026; the audit itself is in git history). Everything else from it is done.

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
