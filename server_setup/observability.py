from io import StringIO
from pathlib import Path

from pyinfra import host
from pyinfra.api import deploy
from pyinfra.facts.server import Command
from pyinfra.operations import apt, files, postgres, server, systemd
from pyinfra.operations.util import any_changed

from server_setup.secrets import put_secret

HERE = Path(__file__).parent
AS_POSTGRES = {"_sudo": True, "_sudo_user": "postgres"}


# Grafana Alloy ships node + postgres metrics and the journal to Grafana Cloud.
# It pushes outbound, so no firewall port opens for it.
@deploy("Observability")
def observability(
    prom_user: str,
    prom_password: str,
    loki_user: str,
    loki_password: str,
    prom_url: str = "https://prometheus-prod-65-prod-eu-west-2.grafana.net/api/prom/push",
    loki_url: str = "https://logs-prod-012.grafana.net/loki/api/v1/push",
):
    # apt reads an armored key from signed-by= only when the file is named *.asc
    key = files.download(
        name="Grafana apt key", src="https://apt.grafana.com/gpg.key", dest="/etc/apt/keyrings/grafana.asc", mode="644"
    )
    repo = files.put(
        name="Grafana apt repo",
        src=StringIO("deb [signed-by=/etc/apt/keyrings/grafana.asc] https://apt.grafana.com stable main\n"),
        dest="/etc/apt/sources.list.d/grafana.list",
        mode="644",
    )
    old_key = files.file(name="Old dearmored Grafana key", path="/etc/apt/keyrings/grafana.gpg", present=False)
    apt.update(name="Refresh apt for Grafana", _if=any_changed(key, repo, old_key))
    apt.packages(name="Alloy", packages=["alloy"])

    changes = [
        server.user(name="Alloy reads the journal", user="alloy", groups=["adm", "systemd-journal"], append=True),
        files.put(
            name="Alloy environment drop-in",
            src=str(HERE / "files/alloy-override.conf"),
            dest="/etc/systemd/system/alloy.service.d/override.conf",
            mode="644",
        ),
        put_secret(
            "Alloy credentials",
            "# Managed by server-setup. Loaded into alloy.service via a systemd drop-in.\n"
            "# Keep mode 0600, owner alloy:alloy.\n"
            f"GC_PROM_USER={prom_user}\n"
            f"GC_PROM_PASSWORD={prom_password}\n"
            f"GC_LOKI_USER={loki_user}\n"
            f"GC_LOKI_PASSWORD={loki_password}\n",
            "/etc/alloy/secrets.env",
            user="alloy",
            group="alloy",
        ),
        files.template(
            name="Alloy config",
            src=str(HERE / "templates/alloy.alloy.j2"),
            dest="/etc/alloy/config.alloy",
            user="root",
            group="alloy",
            mode="640",
            host_name=host.name,
            prom_url=prom_url,
            loki_url=loki_url,
        ),
    ]

    # Peer auth: the `alloy` OS user maps to the DB role of the same name
    postgres.role(name="Alloy DB role", role="alloy", login=True, inherit=True, **AS_POSTGRES)
    member = host.get_fact(
        Command,
        'psql -tAc "SELECT 1 FROM pg_auth_members m JOIN pg_roles r ON r.oid = m.member '
        "JOIN pg_roles g ON g.oid = m.roleid WHERE r.rolname = 'alloy' AND g.rolname = 'pg_monitor'\""
        " 2>/dev/null || true",
        **AS_POSTGRES,
    )
    if member != "1":
        postgres.sql(name="Grant pg_monitor to alloy", sql="GRANT pg_monitor TO alloy", **AS_POSTGRES)

    systemd.daemon_reload(_if=changes[1].did_change)
    systemd.service(name="alloy", service="alloy", running=True, enabled=True)
    systemd.service(name="Restart alloy", service="alloy", restarted=True, _if=any_changed(*changes))
