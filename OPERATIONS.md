# Fleet operations notes

Things that are true about the running fleet and are not derivable from this
repo alone. Kept here because the traps below have each cost real time.

## This repo is not the whole picture

Two ansible repos deploy to these hosts:

- **`server-setup`** (this one) — the foundation: base packages, SSH hardening,
  UFW, the postgres cluster and its backup/verify timers, observability, plus the
  `nginx_site` / `postgres_db` roles shipped as the `lionel_panhaleux.server_setup`
  collection.
- **`myserver`** — a **legacy repo that still owns live deployments**. Do not
  conclude a service is undeployed because it is absent from this repo.

The migration direction is per-app `ansible/` (or `deploy/`) directories,
consuming the collection where they need its roles — a bot with no database and
no vhost needs none, only this repo's foundation (Alloy ships its journal to
Loki whatever the unit). `krcg-bot`, `timer`, `rulings-website`, `archon-vibe`,
`krcg-api` and `codex-of-the-damned` have all made the move; each playbook was deleted from
`myserver` only after the new deploy was verified running on the host. A
playbook still in `myserver` is one not yet migrated.

### What still deploys from `myserver`

| Playbook | Group | Host |
|---|---|---|
| `krcg-static.yml`, `lackey-static.yml`, `warroom.yml` | `krcg_sbg` | strasbourg |
| `add-pubkey.yml`, `initial.yml`, `setup.yml` | `all` | — |

For the three strasbourg sites, CI or the playbook ships the *content* (`static`
and `lackey` rsync from GitHub Actions; `warroom.yml` syncs a local `dist/`), but
the nginx vhost and the certificate still come from `myserver`. In
`sites-enabled` the two generations are easy to tell apart: `myserver` writes
**plain files** named `<domain>.http.conf` / `<domain>.https.conf`; the
collection writes **symlinks** named `<site_name>.conf`.

**Frankfurt is no longer a `myserver` target at all** — everything on it comes
from `archon-vibe`'s own deploy.

Its group names differ from this repo's inventory hostnames:

| `myserver` group | here | IP | |
|---|---|---|---|
| `krcg_gra` | gravelines | 152.228.170.51 | **vestigial** |
| `krcg_sbg` | strasbourg | 51.178.45.139 | |
| `krcg_lim` | frankfurt | 57.129.110.107 | **vestigial** |

`krcg_gra` and `krcg_lim` are still declared in `myserver/hosts.ini` but **no
playbook targets them any more** — gravelines lost its last one when `timer`
moved. An unused inventory group reads exactly like a live one, so check for
a playbook before assuming it deploys something.

It was once `krcg_mun` — the group was renamed, the host did not change. When
reading `myserver` git history, a playbook "moving hosts" may be a rename or a
real move; check the IP.

## What legacy `myserver` roles left on the hosts

- The `python-worker` role — venv under `/home/lpanhaleux/projects/<app>`, the
  token inline in the unit, logs under `SYSLOG_IDENTIFIER=bash` — **is gone**; it
  went with `timer-bot.yml`, the last playbook to use it.
- The legacy `postgresql-database` role added a `local <db> <user> scram-sha-256`
  line to `pg_hba.conf` per (user, database) pair — so one role could appear on
  several lines. **That role no longer exists in `myserver`** (it went with the
  last two playbooks that used it), but the lines it wrote are still on the hosts:
  nothing removes them when a database is dropped.

## Moving a site onto `nginx_site` — the renewal webroot

Three ACME webroots exist on the fleet, and a certificate renews only through
the one its renewal conf names:

| written by | webroot |
|---|---|
| `myserver` `register-ssl` | `/usr/share/nginx/html` |
| collection `nginx_site` | `/var/www/certbot` |
| `archon-vibe` `nginx_tls` (frankfurt) | `/var/www/acme` |

A lineage keeps the renewal conf of whatever **issued** it. Move a site from
`myserver` onto `nginx_site` while its cert is still valid and the role used to
request nothing — the cert covered every name — so certbot kept writing tokens
to `/usr/share/nginx/html` while the new vhost served `/var/www/certbot`. **The
deploy succeeds, the site serves, and every unattended renewal 404s** until the
cert expires. It happened to `codex-beta.krcg.org` (strasbourg) and
`rulings.krcg.org` (gravelines), both found inside certbot's 30-day window.

Since collection 1.0.9 `nginx_site` reads the renewal conf and, when it names
another webroot, re-issues through its own with `--force-renewal`. But it only
does so **when that site is deployed** — a migration is not finished until the
app has deployed once on 1.0.9 or later. To check a host by hand, compare each
`/etc/letsencrypt/renewal/<name>.conf` `[[webroot_map]]` against the `root` of
the `acme-challenge` location nginx serves for that domain on port 80.

`/var/www/acme` is **not** stale: `archon.krcg.org` and `api.archon.krcg.org`
come from `archon-vibe`'s own `nginx_tls` role, which serves that path. The
role's check only reads the lineage of its own `nginx_site_domain`, so it never
touches them. When `static`, `lackey` or `warroom` move off `myserver`, their
lineages will go through this repair on the first deploy.

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

`krcg-bot/ansible/deploy.yml` sets `backup: true` on the token file, deliberately
— on the first converge the hand-made unit held the only copy of that token.

The backup is **not** more exposed than the live file: `backup_local` copies via
`preserved_copy`, which is `shutil.copy2` plus an explicit `chown`, so mode and
owner carry over (and mtime, which is why a backup can look older than the
converge that made it). The trap is lifecycle, not permissions — **a rotation is
not finished until `/etc/krcg-bot/env.*~` is deleted.** That directory is clean
today only because the token has never been rotated.

## Known, not yet done

Nothing outstanding.

`/home/lpanhaleux/projects/` on gravelines is empty: the last `python-worker` venv
(`timer-bot`) was deleted after `timer` moved to `/opt/timer-bot`. Anything
appearing there is a leftover, not a deployment.

On strasbourg the same directory holds exactly `lackey.krcg.org`,
`static.krcg.org` and `warroom.krcg.org` — the three sites still deployed from
`myserver`. The uWSGI-era `api.krcg.org` and Codex units, vhosts and project
directories are gone, and so are the two round-robin ACME stubs
(`rulings.krcg.org.http.conf`, `v2.api.krcg.org.http.conf`) and the orphan bare
`api.krcg.org` certificate. Every certificate on the fleet renews through the
webroot its vhost serves.
