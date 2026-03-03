# server-setup

Ansible playbooks for Debian/Ubuntu server provisioning. Installs base packages, hardens SSH, configures UFW firewall, and sets up nginx + certbot.

## Prerequisites

- A Debian/Ubuntu server with root SSH access (for initial user setup)
- [uv](https://docs.astral.sh/uv/) installed locally, then run `uv sync` to install Ansible and dev tools

## Usage

### 1. Add admin users (as root)

Run once per user to create a sudo user with SSH key access:

```bash
ansible-playbook add-admin.yml -i "HOST," --user root \
    -e "username=lpanhaleux" -e "ssh_key='ssh-ed25519 AAAA...'"

ansible-playbook add-admin.yml -i "HOST," --user root \
    -e "username=deploy" -e "ssh_key='ssh-ed25519 AAAA...'"
```

### 2. System setup

Hardens SSH (disables root login), installs packages, configures UFW, nginx, and certbot:

```bash
ansible-playbook setup.yml -i "HOST," --user deploy
```

After this step, root SSH access is disabled. Use `add-admin.yml` with `--user deploy` (or any existing admin) to add more users.

### GitHub Actions

The `setup.yml` workflow runs via `workflow_dispatch`. Configure the following repository secrets:

- `DEPLOY_SSH_KEY` — private SSH key for the deploy user
- `DEPLOY_HOST` — target server hostname or IP
