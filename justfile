default:
    @just --list

# System setup of a host, or `servers` for all: shows the changes, then asks (--dry, -y pass through)
setup target *flags:
    uv run pyinfra inventory.py deploys/setup.py --limit {{ target }} --diff {{ flags }}

# Distribution upgrade status of a host (CONFIRM=1 upgrades and reboots)
upgrade target:
    uv run pyinfra inventory.py deploys/upgrade.py --limit {{ target }} -y

# Reboot a host if a kernel or system update needs it (FORCE=1 reboots anyway), then check every unit came back
reboot target:
    uv run pyinfra inventory.py deploys/reboot.py --limit {{ target }} -y

# Postgres major upgrade, UNTESTED: reports, CONFIRM=1 migrates, CONFIRM=1 DROP_OLD=1 drops the old cluster
pg-upgrade target:
    uv run pyinfra inventory.py deploys/postgres_upgrade.py --limit {{ target }} -y

# Record a new host's SSH key before anything first connects to it
add-host ip:
    ssh-keyscan -t ed25519 {{ ip }} | grep -v '^#' >> known_hosts

# Create a sudo user on a fresh host, as root with your own key (ADMIN=deploy ADMIN_KEY=~/.ssh/deploy.pub)
add-admin ip root_key="~/.ssh/id_ed25519":
    uv run pyinfra {{ ip }} deploys/add_admin.py --ssh-user root --ssh-key {{ root_key }} -y

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
