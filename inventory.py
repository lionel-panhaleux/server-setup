servers = [
    ("gravelines", {"ssh_hostname": "152.228.170.51"}),
    ("strasbourg", {"ssh_hostname": "51.178.45.139"}),
    # Beta is scrapped and reseeded at will: its backups would archive data nobody
    # intends to recover. Size is not the criterion.
    ("frankfurt", {"ssh_hostname": "57.129.110.107", "backup_exclude": ("new_archon",)}),
]
