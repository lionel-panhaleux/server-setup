import re
import urllib.request

from pyinfra import host, logger
from pyinfra.api import deploy
from pyinfra.facts.files import File
from pyinfra.facts.server import Command, LinuxDistribution
from pyinfra.operations import apt, server


@deploy("Distribution upgrade")
def upgrade(confirm: bool = False):
    distribution = host.get_fact(LinuxDistribution)
    name, current = distribution["name"], distribution["release_meta"]["VERSION_CODENAME"]

    if name == "Ubuntu":
        check = host.get_fact(Command, "do-release-upgrade -c 2>&1 || true")
        found = re.search(r"New release '([^']+)'", check or "")
        target = found.group(1) if found else current
    else:
        release = urllib.request.urlopen("https://deb.debian.org/debian/dists/stable/Release").read().decode()
        target = re.search(r"Codename:\s*(\S+)", release).group(1)

    if target == current:
        logger.info(f"{host.name}: {name} {current}, up to date")
        return
    if not confirm:
        logger.warning(f"{host.name}: {name} {current} → {target} available (CONFIRM=1 to upgrade)")
        return

    apt.update()
    apt.dist_upgrade(auto_remove=True)
    if name == "Ubuntu":
        apt.packages(packages=["update-manager-core"])
        server.shell(name="Release upgrade", commands=["do-release-upgrade -f DistUpgradeViewNonInteractive"])
    else:
        server.shell(
            name=f"Point apt sources at {target}",
            commands=[
                (
                    "find /etc/apt -maxdepth 2 -type f \\( -name '*.list' -o -name '*.sources' \\)"
                    f" -exec sed -i 's/\\b{current}\\b/{target}/g' {{}} +"
                )
            ],
        )
        apt.update()
        apt.dist_upgrade(auto_remove=True)
    server.reboot(reboot_timeout=1200)


@deploy("Reboot")
def reboot(force: bool = False):
    if not force and not host.get_fact(File, path="/var/run/reboot-required"):
        logger.info(f"{host.name}: no reboot required")
        return
    server.reboot(reboot_timeout=600)
    # exits non-zero on a degraded boot, and pyinfra prints the failed units
    server.shell(
        name="Every unit came back",
        commands=["systemctl is-system-running --wait || { systemctl --failed --no-legend; exit 1; }"],
    )


def _clusters() -> list[tuple[int, int, str]]:
    out = host.get_fact(Command, "pg_lsclusters --no-header 2>/dev/null || true", _sudo=True) or ""
    return sorted(
        (int(version), int(port), status)
        for version, name, port, status, *_ in (line.split() for line in out.splitlines())
        if name == "main"
    )


@deploy("Postgres major upgrade")
def postgres_upgrade(confirm: bool = False, drop_old: bool = False):
    """UNTESTED until the first real upgrade. Installing a new major (a distro upgrade,
    or a new postgres_version) leaves an empty NEW/main on 5433 beside OLD/main."""
    clusters = _clusters()
    if len(clusters) != 2:
        logger.info(f"{host.name}: clusters {clusters}, nothing to upgrade")
        return
    (old, old_port, _), (new, new_port, _) = clusters

    if new_port != 5432:
        databases = host.get_fact(
            Command,
            f"psql -p {new_port} -tAc \"SELECT count(*) FROM pg_database WHERE NOT datistemplate AND datname <> 'postgres'\"",
            _sudo=True,
            _sudo_user="postgres",
        )
        if databases != "0":
            raise ValueError(f"{host.name}: {new}/main holds databases, refusing to drop it")
        if not confirm:
            logger.warning(f"{host.name}: {old}/main → {new} ready (CONFIRM=1 to migrate)")
            return
        server.shell(name="Back up before migrating", commands=["systemctl start postgres-backup.service"])
        server.shell(name=f"Drop the empty {new}/main", commands=[f"pg_dropcluster --stop {new} main"])
        # dump mode: OLD/main stays intact on 5433, the rollback until drop_old
        server.shell(name=f"Migrate {old}/main to {new}", commands=[f"pg_upgradecluster {old} main"])
        server.shell(
            name="Refresh planner statistics",
            commands=["vacuumdb --all --analyze-in-stages"],
            _sudo_user="postgres",
        )
        logger.warning(f"{host.name}: run setup for {new}'s conf.d, check the apps, then DROP_OLD=1")
        return

    if not (confirm and drop_old):
        logger.warning(f"{host.name}: {new}/main serves, {old}/main kept on {old_port} (CONFIRM=1 DROP_OLD=1 to drop)")
        return
    server.shell(name=f"Drop {old}/main", commands=[f"pg_dropcluster --stop {old} main"])
    apt.packages(
        name=f"Remove postgres {old}", packages=[f"postgresql-{old}", f"postgresql-client-{old}"], present=False
    )
