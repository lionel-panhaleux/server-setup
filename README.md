# server-setup

Ansible playbooks for Debian/Ubuntu server provisioning. Installs base packages, hardens SSH, configures UFW firewall, and sets up nginx + certbot.

## Prerequisites

- A Debian/Ubuntu server with root SSH access (for initial user setup)
- [uv](https://docs.astral.sh/uv/) installed locally, then run `uv sync` to install Ansible and dev tools
- [just](https://just.systems/) for running sync recipes
- [gh](https://cli.github.com/) CLI, authenticated, for pushing variables/secrets to GitHub

## Inventory

`inventory/hosts` is the single source of truth for server IPs:

```ini
[servers]
api     ansible_host=1.2.3.4
```

Each host has a `host_key` variable in `inventory/host_vars/<name>.yml`:

```yaml
host_key: "1.2.3.4 ssh-ed25519 AAAA..."
```

The setup playbook prints the ready-to-paste `host_key` value at the end of each run.

`inventory/group_vars/servers.yml` pins the default Ansible user and private key for the `[servers]` group, so day-to-day playbook runs don't need `--user` or `--private-key`:

```yaml
ansible_user: deploy
ansible_ssh_private_key_file: ~/.ssh/deploy
```

CLI flags still override these (used by `add-admin.yml` for the initial root login).

## Usage

### 1. Generate SSH keys

Generate one ed25519 keypair per identity (admin user, deploy user). `ssh-keygen` will prompt for a passphrase — leave empty for the deploy key (CI cannot type a passphrase), set one for admin keys.

```bash
ssh-keygen -t ed25519 -f ~/.ssh/lpanhaleux -C "lpanhaleux@$(hostname)"
ssh-keygen -t ed25519 -f ~/.ssh/deploy     -C "deploy@server-setup" -N ""
```

This produces `~/.ssh/<name>` (private) and `~/.ssh/<name>.pub` (public). The `.pub` file is what `add-admin.yml` reads; the private key stays on your machine (or, for the deploy key, is uploaded as a GitHub secret — see [Sync deploy key](#sync-deploy-key-to-github)).

### 2. Add admin users (as root)

Run once per user to create a sudo user with SSH key access. The `--user`/`--private-key` flags override the defaults in `inventory/group_vars/servers.yml` for the initial root-only login:

```bash
ansible-playbook add-admin.yml --limit HOST --user root --private-key ~/.ssh/initial_root_key \
    -e "username=lpanhaleux" -e "ssh_key_file=~/.ssh/lpanhaleux.pub"

ansible-playbook add-admin.yml --limit HOST --user root --private-key ~/.ssh/initial_root_key \
    -e "username=deploy" -e "ssh_key_file=~/.ssh/deploy.pub"
```

### 3. System setup

Hardens SSH (disables root login), installs packages, configures UFW, nginx, and certbot:

```bash
ansible-playbook setup.yml --limit HOST
```

After this step, root SSH access is disabled. Subsequent `add-admin.yml` runs can drop the `--user`/`--private-key` overrides and use the inventory defaults (`deploy` user with `~/.ssh/deploy`).

The playbook also writes the server's SSH host key directly to `inventory/host_vars/<name>.yml`. Commit the change so `just sync` can push it to the deploy-target repos.

### 4. Reboot when required

If the setup playbook ends with `REBOOT REQUIRED`, trigger a graceful reboot and wait for the host to come back:

```bash
ansible HOST -m reboot -b
```

## Deploy targets

`deploy-targets.conf` maps GitHub repos to inventory hostnames:

```
lionel-panhaleux/krcg-api=api
```

### Sync variables to GitHub

Push `DEPLOY_HOST` and `DEPLOY_HOST_KEY` to all repos listed in `deploy-targets.conf`:

```bash
just sync
```

### Sync deploy key to GitHub

Push `DEPLOY_SSH_KEY` as an environment secret to all repos:

```bash
just sync-key ~/.ssh/deploy_key
```

## GitHub Actions

The `setup.yml` and `upgrade.yml` workflows run via `workflow_dispatch` and take the target host as a dropdown input. They read `DEPLOY_SSH_KEY` from secrets and resolve the host key from the committed `inventory/host_vars/<host>.yml`, so no `DEPLOY_HOST_KEY` variable is needed on this repo.
