import re
from io import StringIO
from pathlib import Path

from pyinfra import host
from pyinfra.api import deploy
from pyinfra.facts.files import File
from pyinfra.facts.server import Arch, Command, LinuxDistribution
from pyinfra.operations import apt, files, server, systemd
from pyinfra.operations.util import any_changed

FILES = Path(__file__).parent / "files"

PACKAGES = [
    "unattended-upgrades",
    "logrotate",
    "ufw",
    "fail2ban",
    "gnupg",
    "nginx",
    "certbot",
    "python3-certbot-nginx",
    "python3-venv",
    "python3-dev",
    "python3-pip",
    "libpq-dev",
    "python3-psycopg2",
    "gcc",
    "make",
    "curl",
    "rsync",
    "git",
    "acl",
    "restic",
    "rclone",  # pg-backup's orphan-repo scan: restic can't list bucket prefixes
]


def _put(name: str, dest: str, mode: str = "644"):
    return files.put(name=f"Install {dest}", src=str(FILES / name), dest=dest, mode=mode)


@deploy("Packages")
def packages(postgres_version: str | None = None):
    """postgres_version installs that major from the PGDG repo. With PGDG configured,
    the unversioned `postgresql` package pulls PGDG's newest major: a second cluster."""
    postgres = ["postgresql", "postgresql-client"]
    if postgres_version:
        codename = host.get_fact(LinuxDistribution)["release_meta"]["VERSION_CODENAME"]
        key = files.download(
            name="PGDG apt key",
            src="https://www.postgresql.org/media/keys/ACCC4CF8.asc",
            dest="/etc/apt/keyrings/postgresql.asc",
            mode="644",
        )
        repo = files.put(
            name="PGDG apt repo",
            src=StringIO(
                "Types: deb\n"
                "URIs: https://apt.postgresql.org/pub/repos/apt\n"
                f"Suites: {codename}-pgdg\n"
                "Components: main\n"
                "Signed-By: /etc/apt/keyrings/postgresql.asc\n"
            ),
            dest="/etc/apt/sources.list.d/pgdg.sources",
            mode="644",
        )
        apt.update(name="Refresh apt for PGDG", _if=any_changed(key, repo))
        postgres = [f"postgresql-{postgres_version}", f"postgresql-client-{postgres_version}"]
    apt.update(cache_time=3600)
    apt.dist_upgrade()
    apt.packages(name="Base packages", packages=[*PACKAGES, *postgres])
    _put("20auto-upgrades", "/etc/apt/apt.conf.d/20auto-upgrades")
    if not host.get_fact(File, path="/usr/local/bin/uv"):
        server.shell(
            name="Install uv",
            commands=[
                (
                    "curl -LsSf https://github.com/astral-sh/uv/releases/latest/download/"
                    f"uv-{host.get_fact(Arch)}-unknown-linux-gnu.tar.gz"
                    " | tar -xz --strip-components=1 -C /usr/local/bin"
                )
            ],
        )
    _put("applog.sh", "/usr/local/bin/applog", mode="755")


@deploy("Services")
def services(journal_max_use: str = "2G"):
    jail = _put("jail.local", "/etc/fail2ban/jail.local")
    systemd.service(name="fail2ban", service="fail2ban", running=True, enabled=True)
    systemd.service(name="Restart fail2ban", service="fail2ban", restarted=True, _if=jail.did_change)

    journald = [
        files.directory(name="journald drop-in dir", path="/etc/systemd/journald.conf.d"),
        files.put(
            name="Install /etc/systemd/journald.conf.d/00-server-setup.conf",
            src=StringIO(
                "# Managed by server-setup.\n"
                "[Journal]\n"
                "Storage=persistent\n"
                f"SystemMaxUse={journal_max_use}\n"
                "SystemKeepFree=500M\n"
            ),
            dest="/etc/systemd/journald.conf.d/00-server-setup.conf",
            mode="644",
        ),
    ]
    systemd.service(name="Restart journald", service="systemd-journald", restarted=True, _if=any_changed(*journald))

    for timer in ("certbot.timer", "logrotate.timer", "systemd-tmpfiles-clean.timer"):
        systemd.service(name=timer, service=timer, running=True, enabled=True)
    systemd.service(name="timesyncd", service="systemd-timesyncd", running=True, enabled=True)


@deploy("nginx")
def nginx():
    # Debian's nginx.conf already sets `gzip on`: repeating it here fails nginx -t
    nginx = [
        files.link(name="Remove default site", path="/etc/nginx/sites-enabled/default", present=False),
        _put("nginx-upgrade-map.conf", "/etc/nginx/conf.d/upgrade_map.conf"),
        _put("nginx-gzip.conf", "/etc/nginx/conf.d/gzip.conf"),
        _put("nginx-default-server.conf", "/etc/nginx/conf.d/default_server.conf"),
    ]
    systemd.service(name="nginx", service="nginx", running=True, enabled=True)
    # a reload with a broken config keeps serving the old one, and says so only in the journal
    server.shell(name="Validate nginx config", commands=["nginx -t"], _if=any_changed(*nginx))
    systemd.service(name="Reload nginx", service="nginx", reloaded=True, _if=any_changed(*nginx))
    # certbot renews the files, but nginx serves the old certificate until it reloads
    _put("reload-nginx.sh", "/etc/letsencrypt/renewal-hooks/deploy/reload-nginx.sh", mode="755")


@deploy("SSH")
def ssh():
    config = _put("sshd_config", "/etc/ssh/sshd_config")
    # a config sshd rejects, once restarted, locks every new session out
    server.shell(name="Validate sshd config", commands=["sshd -t"], _if=config.did_change)
    systemd.service(name="Restart ssh", service="ssh", restarted=True, _if=config.did_change)


@deploy("Firewall")
def firewall(ports: tuple[int, ...] = (22, 80, 443)):
    status = host.get_fact(Command, "ufw status verbose", _sudo=True)
    wanted = ["Status: active", "Default: deny (incoming"]
    missing = [p for p in ports if not re.search(rf"(?m)^{p}/tcp\s+ALLOW IN", status)]
    if missing or not all(w in status for w in wanted):
        server.shell(
            name="Configure ufw",
            commands=[
                *(f"ufw allow {p}/tcp" for p in ports),
                "ufw default deny incoming",
                "ufw --force enable",
            ],
        )


@deploy("Swap")
def swap(size_mb: int = 2048):
    if not host.get_fact(File, path="/swapfile"):
        server.shell(
            name="Create swapfile",
            commands=[
                f"dd if=/dev/zero of=/swapfile bs=1M count={size_mb}",
                "chmod 600 /swapfile",
                "mkswap /swapfile",
                "swapon /swapfile",
            ],
        )
    files.line(name="Swap in fstab", path="/etc/fstab", line="/swapfile none swap sw 0 0")
