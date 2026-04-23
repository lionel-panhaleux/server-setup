default:
    @just --list

# Sync DEPLOY_HOST and DEPLOY_HOST_KEY to all GitHub repos from inventory
sync:
    #!/usr/bin/env bash
    set -euo pipefail
    yq 'to_entries | .[] | .key + " " + .value' deploy-targets.yml | while read -r repo host; do
        info=$(ansible-inventory --host "$host")
        ip=$(echo "$info" | python3 -c "import sys,json; print(json.load(sys.stdin)['ansible_host'])")
        host_key=$(echo "$info" | python3 -c "import sys,json; print(json.load(sys.stdin)['host_key'])")
        echo "→ $repo ($host): DEPLOY_HOST=$ip"
        gh variable set DEPLOY_HOST --repo "$repo" --body "$ip"
        gh variable set DEPLOY_HOST_KEY --repo "$repo" --body "$host_key"
    done

# Sync DEPLOY_SSH_KEY to all GitHub repos' production environments
sync-key key_file:
    #!/usr/bin/env bash
    set -euo pipefail
    yq 'to_entries | .[] | .key' deploy-targets.yml | while read -r repo; do
        echo "→ $repo: DEPLOY_SSH_KEY"
        gh secret set DEPLOY_SSH_KEY --repo "$repo" --env production < "{{ key_file }}"
    done
