# sops' own default is ~/Library/Application Support/sops/age/keys.txt on macOS
export SOPS_AGE_KEY_FILE := env("SOPS_AGE_KEY_FILE", home_directory() / ".config/sops/age/keys.txt")

default:
    @just --list

# System setup of a host, or `servers` for all: shows the changes, then asks (--dry, -y pass through)
setup target *flags:
    uv run pyinfra inventory.py deploys/setup.py --limit {{ target }} --diff {{ flags }}

# Distribution upgrade status of a host (CONFIRM=1 upgrades and reboots)
upgrade target:
    uv run pyinfra inventory.py deploys/upgrade.py --limit {{ target }} -y

# Record a new host's SSH key before anything first connects to it
add-host ip:
    ssh-keyscan -t ed25519 {{ ip }} | grep -v '^#' >> known_hosts

# Create a sudo user on a fresh host, as root (ADMIN=deploy ADMIN_KEY=~/.ssh/deploy.pub)
add-admin ip:
    uv run pyinfra {{ ip }} deploys/add_admin.py --ssh-user root --data ssh_known_hosts_file=known_hosts --data ssh_strict_host_key_checking=yes -y

# Push DEPLOY_HOST and DEPLOY_HOST_KEY to each deploy target's GitHub environment
sync:
    uv run deploy_targets.py

# Push DEPLOY_SSH_KEY to each deploy target's GitHub environment
sync-key key_file:
    uv run deploy_targets.py {{ key_file }}

# Edit the encrypted secrets in $EDITOR
secrets:
    sops edit secrets.sops.yaml

lint:
    uv run ruff check
    uv run ruff format --check

test:
    uv run pytest
