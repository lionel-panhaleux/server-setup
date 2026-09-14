# Fleet operations notes

Things that are true about the running fleet and are not derivable from this
repo alone. Kept here because the traps below have each cost real time. How the
fleet got here is logged at the end, in [Fleet history](#fleet-history).

## Who deploys what

This repo is the foundation, converged per host with `setup.yml` (the `Setup`
workflow, or a laptop with the vault password): base packages, SSH hardening,
UFW, nginx defaults (the websocket map, gzip, the certbot reload hook), the
postgres cluster with its backup and verify timers, and observability. It also
ships the `nginx_site` and `postgres_db` roles as the `lionel_panhaleux.server_setup`
collection. Every app deploys from its own repo:

| Repo | Host | Playbook | Run by |
|---|---|---|---|
| `krcg-api` | strasbourg | `deploy/` | CI on a published release, or `workflow_dispatch` |
| `codex-of-the-damned` | strasbourg | `deploy/` | CI, `workflow_dispatch` only (after a PyPI release) |
| `warroom-app` | strasbourg | `ansible/` | CI on push to `main` |
| `krcg-static` | strasbourg | `ansible/` (vhost) | a laptop; content by the `Deployment` and `Data` actions |
| `vtes-lackeyccg` | strasbourg | `ansible/` (vhost) | a laptop; the plugin by the `Deployment` and `Playtest Deployment` actions |
| `krcg-bot` | gravelines | `ansible/` | CI on a published release, or `just deploy` |
| `timer` | gravelines | `ansible/` | `just deploy` |
| `rulings-website` | gravelines | `ansible/` | `just deploy` |
| `archon-vibe` | frankfurt | `ansible/` | its `just` recipes |

Playbooks connect as `deploy`: CI with `DEPLOY_SSH_KEY`, `DEPLOY_HOST` and
`DEPLOY_HOST_KEY`, which `just sync` / `just sync-key` push from
`deploy-targets.yml`; a laptop with `~/.ssh/deploy`. Only the `krcg-api`,
`codex-of-the-damned`, `warroom-app` and `krcg-bot` workflows read those values:
`deploy-targets.yml` also lists `krcg-static`, `vtes-lackeyccg`, `rulings-website`
and `archon-vibe`, whose playbooks run from a laptop.

**Content rsync is the exception.** The `static.krcg.org` and `lackey.krcg.org`
files are rsynced as `lpanhaleux` into `/home/lpanhaleux/projects/<domain>/dist`,
with the `KRCG_DEPLOY_KEY` and `KRCG_SBG_HOST_ID` secrets of each repo's
`krcg.org` environment. **No playbook manages that directory**, and the key is
only in `lpanhaleux`'s `authorized_keys` because it was put there:
`add-admin.yml -e username=lpanhaleux -e ssh_key_file=<its .pub>` re-adds it
without touching the other keys. On strasbourg `projects/` holds exactly those two
sites; on the other hosts it is empty, and anything appearing there is not a
deployment.

## nginx and certificates

- `nginx_site` writes `/etc/nginx/sites-available/<site_name>.conf` and enables
  it with a **symlink**; `archon-vibe` writes its own vhosts on frankfurt. A plain
  `<domain>.http.conf` / `<domain>.https.conf` file in `sites-enabled` comes from
  no current deploy.
- `conf.d/gzip.conf` sets every gzip setting **except `gzip on`**, which Debian's
  `nginx.conf` already has: nginx refuses the directive twice, and the reload
  handler does not run `nginx -t` first.
- certbot's timer renews the files but does not reload nginx, which keeps serving
  the old certificate from memory — and expires on it if nothing reloads within
  30 days. `/etc/letsencrypt/renewal-hooks/deploy/reload-nginx.sh`, from
  `tasks/base.yml`, does the reload. `archon-vibe`'s `nginx_tls` writes the same
  path on frankfurt: **keep the two contents identical**, or each converge
  rewrites the other's.

### The renewal webroot

Two ACME webroots exist, and a certificate renews only through the one its
renewal conf names — the one of the deploy that issued it:

| written by | webroot |
|---|---|
| collection `nginx_site` | `/var/www/certbot` |
| `archon-vibe` `nginx_tls` (frankfurt) | `/var/www/acme` |

A certificate issued through another webroot keeps renewing there after its site
moves onto `nginx_site`: **the deploy succeeds, the site serves, and every
unattended renewal 404s** until the cert expires. `nginx_site` reads its domain's
renewal conf and, when it names another webroot, re-issues through its own with
`--force-renewal` — but only when that site is deployed. It reads only its own
`nginx_site_domain`, so it never touches `archon-vibe`'s certificates. To check a
host by hand, compare each `/etc/letsencrypt/renewal/<name>.conf`
`[[webroot_map]]` against the `root` of the `acme-challenge` location nginx serves
for that domain on port 80.

A site taking over a domain from another vhost must **remove that vhost before
`nginx_site` runs**: while it still answers on port 80, the re-issue's challenge
404s behind it, and counts against Let's Encrypt's failed-validation limit.

## Postgres access lines

`pg_hba.conf` carries `local <db> <user> scram-sha-256` lines, one per (user,
database) pair, that no playbook in this repo writes — so a role can appear on
several lines, and **nothing removes a line when its database is dropped**. Edit
them as in step 6 of [Retiring a service](#retiring-a-service--the-order-that-bites).

## Backup layout (restic)

`files/pg-backup.sh` builds `RESTIC_REPOSITORY="$RESTIC_REPOSITORY_BASE/<dbname>"`
— **one repo per database name, with no host segment**, and every host shares one
bucket.

- Two hosts with a same-named database **share one repo**. Before treating a repo
  as one host's archive — or deleting it — run
  `restic snapshots --group-by host` and read every group.
- **Never delete the `globals/` prefix.** It holds `pg_dumpall --globals-only` for
  the cluster: every login role and password hash the apps connect with. It is the
  one prefix with no owning database, so an orphan-style sweep can mistake it for
  garbage; `pg-backup.sh` skips it explicitly for that reason.
- Dropping a database does **not** prune its repo. Local dumps age out by date, but
  the bucket prefix stays forever and the nightly run logs an orphan-repo warning
  until it is deleted by hand.
- The hosts have **no named rclone remote**. `pg-backup.sh` builds an on-the-fly
  `:s3,provider=Other,env_auth:` remote from `/etc/postgres-backup/remote.env`;
  mirror that for any manual `rclone` call rather than expecting a config file.

## Retiring a service — the order that bites

1. **Remove its entry from `deploy-targets.yml` first.** `just sync` and
   `just sync-key` re-create each listed repo's GitHub environment and re-push
   `DEPLOY_HOST` / `DEPLOY_HOST_KEY` / `DEPLOY_SSH_KEY`. Deleting the environment
   while the line remains is silently undone by the next sync.
2. **Stop and `disable` the unit before revoking its credential.** These units are
   `Restart=always`; revoking a token first turns the service into a
   `RestartSec=5` auth-failure loop.
3. **For a Discord bot, the slash commands live on Discord, not the host.** Once
   the process is stopped nothing can clear them — delete the application (or
   clear its global commands) or they linger in every guild as dead entries.
4. **Dump and copy off-host before dropping the database.** Use
   `DROP DATABASE <db> WITH (FORCE)` when a connection pool holds idle
   connections (psycopg_pool keeps `min_size=4` open, which blocks a plain drop —
   and those idle connections are not evidence of use).
5. **A postgres role shared by several databases drops only after the last one.**
   Dropping a role that still holds grants elsewhere either fails on dependent
   privileges or succeeds and silently breaks the other app.
6. Edit `pg_hba.conf` with `sed`, not `sudo -e`, if you are driving the host over
   `ssh '… sh -s'`; validate with
   `select * from pg_hba_file_rules where error is not null` **before**
   `pg_reload_conf()`.

## `backup: true` keeps superseded secrets on disk

`krcg-bot/ansible/deploy.yml` sets `backup: true` on the token file and on the
unit, so a converge that changes either leaves the previous version beside it.

The backup is **not** more exposed than the live file: `backup_local` copies via
`preserved_copy`, which is `shutil.copy2` plus an explicit `chown`, so mode and
owner carry over (and mtime, which is why a backup can look older than the
converge that made it). The trap is lifecycle, not permissions — **a rotation is
not finished until `/etc/krcg-bot/env.*~` is deleted.** That directory is clean
today only because the token has never been rotated.

## Fleet history

What happened, oldest first. Most apps were once deployed by `myserver`, a
legacy repo, now archived; a date below is the day a deploy left it. Its inventory groups, for reading its git
history: `krcg_gra` is gravelines, `krcg_sbg` strasbourg, `krcg_lim` frankfurt
(once named `krcg_mun`, same host).

| Date | Change |
|---|---|
| 2026-01-24 | `myserver` drops DNS round-robin; its `register-ssl` role starts installing the certbot reload hook. |
| 2026-07-26 | `krcg-bot` moves to its own `ansible/` on gravelines, taking over a hand-made `krcg-bot.service` (token inline) under the same unit name. |
| 2026-09-13 | `myserver` drops archon-bot; rulings moves to `rulings-website` (a one-way schema change to the shared `vtes-rulings` database) and the archon website to `archon-vibe`; the v2 KRCG API is retired. |
| 2026-09-13 | `krcg-api` and `codex-of-the-damned` move to `deploy/`. One-shot `cleanup.yml` playbooks, since deleted, removed their Flask/uWSGI units, vhosts and project directories; the round-robin ACME stubs (`rulings.krcg.org.http.conf`, `v2.api.krcg.org.http.conf`) and a bare `api.krcg.org` certificate went too. |
| 2026-09-13 | `timer` moves to `ansible/` (`/opt/timer-bot`); with it go the last `python-worker` venv under `projects/` and that role, which put the token inline in the unit. |
| 2026-09-13 | Collection 1.0.9: `codex-beta.krcg.org` and `rulings.krcg.org` are found renewing through `myserver`'s `/usr/share/nginx/html` after moving onto `nginx_site`, inside certbot's 30-day window; the role starts repairing renewal confs. `myserver`'s `postgresql-database` role, which wrote the `pg_hba.conf` lines above, is gone by then. |
| 2026-09-13 | `warroom-app`, `vtes-lackeyccg` and `krcg-static` move their sites onto `nginx_site`; each first deploy removed the `myserver` vhosts (and warroom's old content directory) and re-issued the certificate. `myserver` deploys nothing after this. Collection 1.0.13 adds public sites. |
| 2026-09-13 | This repo adds gzip for every site, and takes over the certbot reload hook: until then only `register-ssl`'s leftover copy reloaded nginx after a renewal. |
| 2026-09-14 | The app deploys drop their migration-only steps (the `myserver` vhost removals, `cleanup.yml`, cutover notes), and `krcg-static` stops trusting gravelines' host key. `myserver` is archived: `add-admin.yml` and `setup.yml` cover its bootstrap playbooks. |
