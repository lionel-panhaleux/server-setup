# server-setup

Ansible playbook for system-level server provisioning. Installs base packages, hardens SSH, configures UFW firewall, and sets up nginx + certbot.

## Prerequisites

- A Debian/Ubuntu server with root SSH access (for bootstrap)
- Ansible installed locally: `pip install ansible`

## Usage

### First-time bootstrap (as root)

```bash
ansible-playbook playbook.yml -i "HOST," --user root --tags bootstrap \
    -e "ssh_public_key='ssh-ed25519 AAAA...'"
```

### System setup (as deploy user)

```bash
ansible-playbook playbook.yml -i "HOST," --tags setup \
    --private-key ~/.ssh/krcg_deploy --user lpanhaleux
```

### GitHub Actions

The `setup.yml` workflow runs via `workflow_dispatch`. Configure the following repository secrets:

- `DEPLOY_SSH_KEY` — private SSH key for the deploy user
- `DEPLOY_HOST` — target server hostname or IP
