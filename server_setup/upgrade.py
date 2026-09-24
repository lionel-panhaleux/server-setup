import re
import urllib.request

from pyinfra import host, logger
from pyinfra.api import deploy
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
