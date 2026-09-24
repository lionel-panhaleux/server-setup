from pathlib import Path

ssh_user = "deploy"
ssh_key = "~/.ssh/deploy"
ssh_known_hosts_file = str(Path(__file__).parent.parent / "known_hosts")
ssh_strict_host_key_checking = "yes"
_sudo = True
