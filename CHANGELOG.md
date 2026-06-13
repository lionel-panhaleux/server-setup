# Changelog

## 1.0.1

- `postgres_db`: scope `become`/`become_user: postgres` to the role's task
  blocks instead of `vars/main.yml`. Role vars set there leaked into the
  consumer's whole play and (as `ansible_become*`) overrode the play's own
  `become`, so unrelated tasks — including `delegate_to: localhost` tasks —
  wrongly escalated to the postgres user.

## 1.0.0

- Initial collection release: `nginx_site` and `postgres_db` roles, installable
  from git as `lionel_panhaleux.server_setup`.
