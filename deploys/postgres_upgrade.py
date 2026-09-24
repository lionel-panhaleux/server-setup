import os

from server_setup import postgres_upgrade

postgres_upgrade(confirm=os.environ.get("CONFIRM") == "1", drop_old=os.environ.get("DROP_OLD") == "1")
