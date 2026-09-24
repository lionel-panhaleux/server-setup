from io import StringIO
from pathlib import Path

from pyinfra import host
from pyinfra.api import deploy
from pyinfra.facts.server import Command
from pyinfra.operations import files, systemd
from pyinfra.operations.util import any_changed

from server_setup.secrets import put_secret

FILES = Path(__file__).parent / "files"
UNITS = (
    "postgres-backup.service",
    "postgres-backup.timer",
    "postgres-backup-check.service",
    "postgres-backup-check.timer",
)


@deploy("Postgres logging")
def postgres_logging():
    # Read before this run installs postgresql: a fresh box gets these on its second run
    confd = host.get_fact(Command, "find /etc/postgresql -type d -name conf.d 2>/dev/null || true", _sudo=True)
    changes = []
    for directory in (confd or "").splitlines():
        for dest, src in (
            ("50-log-prefix.conf", "postgres-log-prefix.conf"),
            ("51-log-queries.conf", "postgres-log-queries.conf"),
        ):
            path = f"{directory}/{dest}"
            changes.append(files.put(name=f"Install {path}", src=str(FILES / src), dest=path, mode="644"))
    systemd.service(name="Restart postgresql", service="postgresql", restarted=True, _if=any_changed(*changes))


@deploy("Postgres backups")
def postgres_backups(
    access_key: str,
    secret_key: str,
    restic_password: str,
    healthcheck_url: str = "",
    check_healthcheck_url: str = "",
    exclude: tuple[str, ...] = (),
    endpoint: str = "https://s3.fr-par.scw.cloud",
    bucket: str = "krcg-db-backups",
    keep_daily: int = 7,
    keep_weekly: int = 4,
    keep_monthly: int = 12,
):
    files.directory(name="Backup config dir", path="/etc/postgres-backup", user="root", group="postgres", mode="750")
    files.directory(name="Backup dir", path="/var/backups/postgres", user="postgres", group="postgres", mode="750")
    files.put(
        name="Backup settings",
        src=StringIO(f'EXCLUDE_DBS="{" ".join(exclude)}"\n'),
        dest="/etc/postgres-backup/backup.env",
        user="root",
        group="postgres",
        mode="640",
    )
    put_secret(
        "Remote backup credentials",
        f"AWS_ACCESS_KEY_ID={access_key}\n"
        f"AWS_SECRET_ACCESS_KEY={secret_key}\n"
        f"RESTIC_PASSWORD={restic_password}\n"
        f"RESTIC_REPOSITORY_BASE=s3:{endpoint}/{bucket}\n"
        f"REMOTE_KEEP_DAILY={keep_daily}\n"
        f"REMOTE_KEEP_WEEKLY={keep_weekly}\n"
        f"REMOTE_KEEP_MONTHLY={keep_monthly}\n",
        "/etc/postgres-backup/remote.env",
        group="postgres",
        mode="640",
    )
    # healthchecks.io-style dead-man's switch: an alert on the absence of the
    # success ping catches the timer that silently stopped firing
    if healthcheck_url or check_healthcheck_url:
        put_secret(
            "Healthcheck ping URLs",
            f"BACKUP_HEALTHCHECK_URL={healthcheck_url}\nCHECK_HEALTHCHECK_URL={check_healthcheck_url}\n",
            "/etc/postgres-backup/healthcheck.env",
            group="postgres",
            mode="640",
        )

    for script in ("pg-backup", "pg-backup-check", "pg-restore"):
        files.put(
            name=f"Install {script}",
            src=str(FILES / f"{script}.sh"),
            dest=f"/usr/local/bin/{script}",
            user="root",
            group="postgres",
            mode="750",
        )

    units = [
        files.put(name=f"Install {unit}", src=str(FILES / unit), dest=f"/etc/systemd/system/{unit}", mode="644")
        for unit in UNITS
    ]
    systemd.daemon_reload(_if=any_changed(*units))
    for timer in ("postgres-backup.timer", "postgres-backup-check.timer"):
        systemd.service(name=timer, service=timer, running=True, enabled=True)
