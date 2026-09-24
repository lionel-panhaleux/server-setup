import os

from server_setup import upgrade

upgrade(confirm=os.environ.get("CONFIRM") == "1")
