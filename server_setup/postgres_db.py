from pyinfra import host
from pyinfra.api import deploy
from pyinfra.facts.server import Command
from pyinfra.operations import postgres

AS_POSTGRES = {"_sudo": True, "_sudo_user": "postgres"}


def _settings(database: str) -> dict[str, str]:
    out = host.get_fact(
        Command,
        'psql -tAc "SELECT unnest(setconfig) FROM pg_db_role_setting s JOIN pg_database d '
        f"ON d.oid = s.setdatabase WHERE d.datname = '{database}' AND s.setrole = 0\" 2>/dev/null || true",
        **AS_POSTGRES,
    )
    return dict(line.split("=", 1) for line in out.splitlines() if "=" in line)


# An app on the same host logs in over the unix socket by peer auth: no password.
@deploy("Postgres database")
def postgres_db(
    database: str,
    owner: str,
    password: str | None = None,
    statement_timeout: str = "15s",
    idle_in_transaction_session_timeout: str = "60s",
    lock_timeout: str = "5s",
):
    # postgres.role defaults to NOINHERIT, where CREATE ROLE defaults to INHERIT
    postgres.role(name="Database role", role=owner, password=password, login=True, inherit=True, **AS_POSTGRES)
    postgres.database(name="Database", database=database, owner=owner, **AS_POSTGRES)

    current = _settings(database)
    for key, value in {
        "statement_timeout": statement_timeout,
        "idle_in_transaction_session_timeout": idle_in_transaction_session_timeout,
        "lock_timeout": lock_timeout,
    }.items():
        if current.get(key) != value:
            postgres.sql(
                name=f"Database {key}", sql=f"ALTER DATABASE \"{database}\" SET {key} = '{value}'", **AS_POSTGRES
            )
