# Changelog

## 2.0.0

- pyinfra replaces Ansible. The repo is the `server_setup` Python package: apps
  import `nginx_site`, `certificate` and `postgres_db` from a pinned git tag instead of
  installing the collection. `ansible-final` tags the collection's last release
  (1.0.13) for the apps still on Ansible.
- sops replaces ansible-vault: `secrets.sops.yaml`, encrypted to the SSH keys
  listed in `.sops.yaml`, `just secrets` to edit. Keys lose their `vault_`
  prefix.
- Host keys live in a committed `known_hosts` that every connection checks
  strictly; setup no longer writes them back into the inventory.
- The postgres backup units are static files: the local directory, retention
  and schedule are fixed, and a host's excluded databases move to
  `/etc/postgres-backup/backup.env`. Remote backup and observability are no
  longer optional.
- Restore is `pg-restore` on the host, installed beside `pg-backup`, instead of
  the role's `restore` and `restore-remote` task files.
- `postgres_db` no longer requires a password: apps on the host log in by peer
  auth.
- `nginx_site` hardening: HSTS (one year, this host only) and `nosniff` on every
  response, repeated in each location that sets its own headers; Mozilla's
  intermediate TLS ciphers; one shared session cache; `X-Forwarded-For` is the
  client address instead of appending the chain the client sent. A whole-site
  open API is refused on static and spa sites, which own `location /`.
- Setup adds a catch-all default server: names no site serves get no site. Its
  port 80 answers ACME challenges.
- `certificate(domain, extra_domains)` is its own deploy, for apps that write
  their own vhosts. It issues before any site config exists, through the default
  server, so `nginx_site` no longer writes an HTTP-only config first (and no
  longer answers 503 while waiting for the certificate).
- Every nginx reload is preceded by `nginx -t`.
- Tests: molecule goes. Unit tests render every `nginx_site` variant and cover
  the certificate decisions; CI runs `nginx -t` over them and converges
  `postgres_db` on the runner.

## 1.0.13

- `nginx_site`: `nginx_site_public: true` (static and spa) serves public files
  anyone may link to: read-only CORS on every response, errors included, with
  preflights answered 204; directory listings; and port 80 serving the site
  exactly as 443 does, `nginx_site_extra_locations` included, instead of
  redirecting. For `static.krcg.org` and `lackey.krcg.org`, which kept all of
  this in hand-written snippets, and whose whole-site plain-HTTP path served
  port 80 bare (no headers, no rewrites, no listings).
- `nginx_site`: cache defaults per type. `static` sends
  `public, must-revalidate` with `max-age=3600` for images and fonts and
  `max-age=300` for everything else. `spa` caches `/assets/` (where Vite puts
  the hashed files) for a year as immutable and everything else `no-cache`: it
  used to cache every `.js` for a year, service worker and its registration
  script included, so `warroom.krcg.org` had to exempt them one by one.
- `nginx_site`: static and spa sites declare `charset utf-8` on text responses.
  Without it a browser guesses the encoding of a `.txt` file, and misreads the
  accented names in `static.krcg.org`'s tournament reports.
- molecule: a public static site answers on port 80 with CORS, listings, cache
  headers and its extra locations; an SPA caches only its assets.

## 1.0.12

- `nginx_site`: `nginx_site_plain_http_paths: ["/"]` serves the whole site over
  plain HTTP. The port 80 server still added its own `location /` (the HTTPS
  redirect, or the 503 before the certificate exists), and nginx refuses a
  duplicate location, so the config failed `nginx -t`. The catch-all is now left
  out when `/` is a plain-HTTP path, as the HTTPS server already does for
  `nginx_site_open_api_paths: ["/"]`. For `lackey.krcg.org`, whose LackeyCCG
  clients fetch the plugin files.
- molecule: a static site served over plain HTTP answers 200 on port 80.

## 1.0.11

- `nginx_site`: a dry run of a site's first deploy reaches the end. Check mode
  does not write the config, so enabling the site found no link target and
  aborted the play — on exactly the deploy most worth reviewing
  (`warroom.krcg.org`'s cutover from `myserver`). The link now uses `force`
  when the config is not on disk, which only a dry run can see: check mode then
  reports the link without creating it. The condition is a `stat`, not
  `ansible_check_mode`, which follows the CLI `--check` but not a play's
  `check_mode: true`.
- molecule: the nginx_site scenario dry-runs a site that was never deployed.

## 1.0.10

- `nginx_site`: read the certificate's names under `--check` too. The read is a
  `command`, which ansible skips in check mode, so it registered nothing, every
  name looked missing, and every dry run of every site reported a certbot
  issuance a real run would not perform — burying the one site that genuinely
  needed a certificate among all the ones that did not. `openssl x509` only
  reads, so it now opts out of check mode, as `nginx -v` did in 1.0.7.
- molecule: the dry run over the converged proxy site asserts certbot is not
  reported at all, not merely that it is not forced.

## 1.0.9

- `nginx_site`: repair a renewal configuration that points at another webroot.
  A site moved onto the role while its certificate was still valid kept the
  previous deploy's renewal conf, and with it that deploy's ACME webroot (e.g.
  `/usr/share/nginx/html`), while the role's vhost serves the challenge from
  `/var/www/certbot`. The certificate covered every name, so the role requested
  nothing and every unattended renewal 404'd until it expired — which is how
  `codex-beta.krcg.org` came within 18 days of lapsing. The role now reads the
  renewal conf and re-issues through its own webroot with `--force-renewal`,
  which rewrites the conf; it runs once per affected lineage. (`certbot
  reconfigure` would avoid the issuance but needs certbot 2.3; Debian 12 ships
  2.1.) A certificate with no renewal conf is left alone.
- molecule: the nginx_site scenario gives the proxy site a certbot renewal conf,
  checks the role leaves it alone, then points it at a legacy webroot and checks
  a dry run would force the re-issue.

## 1.0.8

- `nginx_site`: the certbot task reports what certbot did. It carried no
  `changed_when`, so it counted as a change whenever its guard let it run and
  reloaded nginx even when certbot had found the cert already covering the
  names and not due, and said so. That was also the tree's last `no-changed-when`
  violation: `ansible-lint` passes the production profile again.

## 1.0.7

- `nginx_site`: run the nginx version detection under `--check` too. It is a
  `command`, which ansible skips in check mode, so the register came back empty
  and the version parse aborted every consuming play's dry run — before the
  vhost was ever diffed, leaving a full deploy to apply the role unreviewed.
  `nginx -v` changes nothing, so it now opts out of check mode.
- molecule: the nginx_site scenario dry-runs the role over the converged site,
  so a task that cannot survive `--check` fails CI rather than a consumer.

## 1.0.6

- `nginx_site`: support nginx < 1.25.1 (Debian 12 ships 1.22): `http2 on;`
  does not exist there, so a rendered vhost failed `nginx -t` and wedged all
  reloads on the host. The role now detects the nginx version and falls back
  to the legacy `listen … http2` parameter.
- molecule: the nginx_site scenario converges on both `debian:12` and
  `debian:trixie`, so distro-specific nginx syntax breaks surface in CI
  instead of on the fleet.

## 1.0.5

- `nginx_site`: new `nginx_site_cert_extra_domains` — extra SANs requested on
  the site's certificate beyond its domain and aliases. Lets a domain that
  will later move to the site as an alias (e.g. an apex flipping between
  versioned sites) be covered from first issuance, so the move is a pure
  `server_name` change with no certificate operation.

## 1.0.4

- `nginx_site`: re-issue the Let's Encrypt certificate (`certbot --expand`)
  when the desired domain set is not covered by the existing cert's SANs —
  so an apex domain can move between sites as an alias. Previously a cert was
  only requested when none existed, and alias changes never re-issued it.

## 1.0.3

- `nginx_site`: support `nginx_site_open_api_paths: ["/"]` on proxy sites
  (whole-site permissive CORS for public APIs). The root location from the
  open-API loop previously collided with the proxy default `location /`,
  making `nginx -t` fail on a duplicate location.

## 1.0.2

- `postgres_db`: skip the per-database timeouts task under `--check`. It needs
  `autocommit`, which `community.postgresql` rejects in check mode, so a dry run
  of any consuming play would fail there. The timeouts still apply on real runs.

## 1.0.1

- `postgres_db`: scope `become`/`become_user: postgres` to the role's task
  blocks instead of `vars/main.yml`. Role vars set there leaked into the
  consumer's whole play and (as `ansible_become*`) overrode the play's own
  `become`, so unrelated tasks — including `delegate_to: localhost` tasks —
  wrongly escalated to the postgres user.

## 1.0.0

- Initial collection release: `nginx_site` and `postgres_db` roles, installable
  from git as `lionel_panhaleux.server_setup`.
