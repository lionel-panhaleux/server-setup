# Changelog

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
