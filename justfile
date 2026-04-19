default:
    @just --list

# Sync DEPLOY_HOST and DEPLOY_HOST_KEY to all GitHub repos from inventory
sync:
    #!/usr/bin/env bash
    set -euo pipefail
    while IFS='=' read -r repo host; do
        [[ "$repo" =~ ^#.*$ || -z "$repo" ]] && continue
        info=$(ansible-inventory --host "$host")
        ip=$(echo "$info" | python3 -c "import sys,json; print(json.load(sys.stdin)['ansible_host'])")
        host_key=$(echo "$info" | python3 -c "import sys,json; print(json.load(sys.stdin)['host_key'])")
        echo "→ $repo ($host): DEPLOY_HOST=$ip"
        gh variable set DEPLOY_HOST --repo "$repo" --body "$ip"
        gh variable set DEPLOY_HOST_KEY --repo "$repo" --body "$host_key"
    done < deploy-targets.conf

# Sync DEPLOY_SSH_KEY to all GitHub repos' production environments
sync-key key_file:
    #!/usr/bin/env bash
    set -euo pipefail
    while IFS='=' read -r repo host; do
        [[ "$repo" =~ ^#.*$ || -z "$repo" ]] && continue
        echo "→ $repo: DEPLOY_SSH_KEY"
        gh secret set DEPLOY_SSH_KEY --repo "$repo" --env production < "{{ key_file }}"
    done < deploy-targets.conf
