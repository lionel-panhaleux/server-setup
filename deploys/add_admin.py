import os
import re
from io import StringIO
from pathlib import Path

from pyinfra.operations import files, server

username = os.environ["ADMIN"]
if not re.fullmatch(r"[a-z_][a-z0-9_-]*", username):
    raise ValueError(f"not a valid user name: {username!r}")

server.user(
    name=f"Admin user {username}",
    user=username,
    shell="/bin/bash",
    groups=["sudo"],
    append=True,
    create_home=True,
    public_keys=[Path(os.environ["ADMIN_KEY"]).expanduser().read_text().strip()],
)
files.put(
    name="Passwordless sudo",
    src=StringIO(f"{username} ALL=(ALL) NOPASSWD:ALL\n"),
    dest=f"/etc/sudoers.d/{username}",
    mode="440",
)
