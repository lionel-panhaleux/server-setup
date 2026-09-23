from pathlib import Path

CONNECTION = {
    "ssh_user": "deploy",
    "ssh_key": "~/.ssh/deploy",
    "ssh_known_hosts_file": str(Path(__file__).parent / "known_hosts"),
    "ssh_strict_host_key_checking": "yes",
    "_sudo": True,
}

servers = [
    ("gravelines", {**CONNECTION, "ssh_hostname": "152.228.170.51"}),
    ("strasbourg", {**CONNECTION, "ssh_hostname": "51.178.45.139"}),
    # Beta is scrapped and reseeded at will: its backups would archive data nobody
    # intends to recover. Size is not the criterion.
    ("frankfurt", {**CONNECTION, "ssh_hostname": "57.129.110.107", "backup_exclude": ("new_archon",)}),
]
