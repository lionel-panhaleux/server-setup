import os

from server_setup import reboot

reboot(force=os.environ.get("FORCE") == "1")
