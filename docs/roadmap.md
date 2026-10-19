# Dashboard roadmap

Left over from the product audit (October 2026; the audit itself is in git history). Everything else from it is done.

**Urgent**
- **Off-site backups are failing.** Every nightly restic run since 8 October 2026 has failed with "the billing account for the owning project is disabled": the Google Cloud billing account behind the backup bucket is closed. Re-enable billing, or point restic at another repository (Backblaze B2, another bucket, or a USB disk on the Pi). Until then, only local database copies exist.

**Away from home**
- **A trusted certificate over Tailscale.** The stack serves a self-signed `home.local` certificate, so browsers warn on the Pi's MagicDNS name and installed apps can't use their offline mode. With HTTPS enabled for the tailnet, `tailscale cert <pi>.<tailnet>.ts.net` issues a real certificate; mount it in nginx, renew it monthly with a timer, and set `MCP_PUBLIC_URL` to the same name. (The name then appears in public certificate logs.)

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
