"""Push each repo's deploy target into its GitHub environment.

uv run deploy_targets.py            DEPLOY_HOST and DEPLOY_HOST_KEY
uv run deploy_targets.py KEY_FILE   DEPLOY_SSH_KEY
"""

import subprocess
import sys
from pathlib import Path

from inventory import servers

# repo -> (inventory host, GitHub environment)
TARGETS = {
    "lionel-panhaleux/krcg-api": ("strasbourg", "production"),
    "lionel-panhaleux/warroom-app": ("strasbourg", "production"),
    "lionel-panhaleux/krcg-static": ("strasbourg", "production"),
    "lionel-panhaleux/krcg-bot": ("gravelines", "production"),
    "lionel-panhaleux/codex-of-the-damned": ("strasbourg", "production"),
    "vtes-biased/archon-vibe": ("frankfurt", "beta"),  # archon.krcg.org
    "vtes-biased/rulings-website": ("gravelines", "production"),
    "vtes-biased/vtes-lackeyccg": ("strasbourg", "production"),
}


def gh(*args: str, stdin: str | None = None) -> None:
    subprocess.run(["gh", *args], input=stdin, text=True, check=True)


def main() -> None:
    ips = {name: data["ssh_hostname"] for name, data in servers}
    known = dict(line.split(" ", 1) for line in (Path(__file__).parent / "known_hosts").read_text().splitlines())
    key_file = sys.argv[1] if len(sys.argv) > 1 else None
    for repo, (host, env) in TARGETS.items():
        print(f"→ {repo} ({host} → {env})")
        gh("api", "-X", "PUT", f"repos/{repo}/environments/{env}", "--silent")
        if key_file:
            gh("secret", "set", "DEPLOY_SSH_KEY", "--repo", repo, "--env", env, stdin=Path(key_file).read_text())
        else:
            ip = ips[host]
            gh("variable", "set", "DEPLOY_HOST", "--repo", repo, "--env", env, "--body", ip)
            gh("variable", "set", "DEPLOY_HOST_KEY", "--repo", repo, "--env", env, "--body", f"{ip} {known[ip]}")


if __name__ == "__main__":
    main()
