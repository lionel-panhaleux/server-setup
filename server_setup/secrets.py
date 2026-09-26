import json
import subprocess
from functools import cache
from io import StringIO

from pyinfra import state
from pyinfra.api import operation
from pyinfra.operations import files


@cache
def load(path: str) -> dict:
    out = subprocess.run(
        ["sops", "decrypt", "--output-type", "json", path], check=True, stdout=subprocess.PIPE, text=True
    ).stdout
    return json.loads(out)


# --diff prints the old and new content of every changed file, secrets included. pyinfra runs an
# operation's body twice, once to detect changes and again to execute: the diff must be off for both.
@operation()
def _put_quietly(src: str, dest: str, user: str, group: str, mode: str):
    diff, state.config.DIFF = state.config.DIFF, False
    try:
        commands = list(files.put._inner(src=StringIO(src), dest=dest, user=user, group=group, mode=mode))
    finally:
        state.config.DIFF = diff
    yield from commands


def put_secret(name: str, content: str, dest: str, user: str = "root", group: str = "root", mode: str = "600"):
    return _put_quietly(name=name, src=content, dest=dest, user=user, group=group, mode=mode)
