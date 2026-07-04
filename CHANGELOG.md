# Changelog

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
