import json
import subprocess
from functools import cache
from io import StringIO

from pyinfra import state
from pyinfra.operations import files


@cache
def load(path: str) -> dict:
    out = subprocess.run(
        ["sops", "decrypt", "--output-type", "json", path], check=True, stdout=subprocess.PIPE, text=True
    ).stdout
    return json.loads(out)


# --diff prints the old and new content of every changed file, secrets included.
def put_secret(name: str, content: str, dest: str, user: str = "root", group: str = "root", mode: str = "600"):
    diff, state.config.DIFF = state.config.DIFF, False
    try:
        return files.put(name=name, src=StringIO(content), dest=dest, user=user, group=group, mode=mode)
    finally:
        state.config.DIFF = diff
