# Changelog

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
