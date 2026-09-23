from pathlib import Path

from pyinfra import host, logger
from pyinfra.facts.files import File

import server_setup as s
from server_setup.secrets import load

secrets = load(str(Path(__file__).parent.parent / "secrets.sops.yaml"))

s.packages()
s.services()
s.nginx()
s.ssh()
s.firewall()
s.swap()
s.postgres_logging()
s.postgres_backups(
    access_key=secrets["remote_backup_access_key"],
    secret_key=secrets["remote_backup_secret_key"],
    restic_password=secrets["remote_backup_restic_password"],
    healthcheck_url=secrets.get("postgres_backup_healthcheck_url", ""),
    check_healthcheck_url=secrets.get("postgres_backup_check_healthcheck_url", ""),
    exclude=host.data.get("backup_exclude", ()),
)
s.observability(
    prom_user=secrets["grafana_cloud_prom_user"],
    prom_password=secrets["grafana_cloud_prom_password"],
    loki_user=secrets["grafana_cloud_loki_user"],
    loki_password=secrets["grafana_cloud_loki_password"],
)

if host.get_fact(File, path="/var/run/reboot-required"):
    logger.warning(f"{host.name}: REBOOT REQUIRED for a kernel or system update")
