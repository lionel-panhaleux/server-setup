default:
    @just --list

# Sync DEPLOY_HOST and DEPLOY_HOST_KEY to each repo's configured environment
sync:
    #!/usr/bin/env bash
    set -euo pipefail
    yq 'to_entries | .[] | .key + " " + (.value.host // .value) + " " + (.value.env // "production")' deploy-targets.yml | while read -r repo host env; do
        info=$(ansible-inventory --host "$host")
        ip=$(echo "$info" | python3 -c "import sys,json; print(json.load(sys.stdin)['ansible_host'])")
        host_key=$(echo "$info" | python3 -c "import sys,json; print(json.load(sys.stdin)['host_key'])")
        echo "→ $repo ($host → $env): DEPLOY_HOST=$ip"
        gh api -X PUT "repos/$repo/environments/$env" --silent
        gh variable set DEPLOY_HOST --repo "$repo" --env "$env" --body "$ip"
        gh variable set DEPLOY_HOST_KEY --repo "$repo" --env "$env" --body "$host_key"
    done

# Sync DEPLOY_SSH_KEY to each repo's configured environment
sync-key key_file:
    #!/usr/bin/env bash
    set -euo pipefail
    yq 'to_entries | .[] | .key + " " + (.value.env // "production")' deploy-targets.yml | while read -r repo env; do
        echo "→ $repo ($env): DEPLOY_SSH_KEY"
        gh api -X PUT "repos/$repo/environments/$env" --silent
        gh secret set DEPLOY_SSH_KEY --repo "$repo" --env "$env" < "{{ key_file }}"
    done

# Run molecule tests locally (requires docker daemon + `uv sync --group dev`)
test role="":
    #!/usr/bin/env bash
    set -euo pipefail
    export PATH="{{ justfile_directory() }}/.venv/bin:$PATH"
    # molecule-plugins docker create.yml needs `invocation` in task results,
    # which ansible-core >= 2.21 omits by default (no-op on older cores).
    export ANSIBLE_INJECT_INVOCATION=true
    ansible-galaxy collection install community.docker >/dev/null
    roles="{{ role }}"
    [ -z "$roles" ] && roles="nginx_site postgres_db"
    for r in $roles; do
        echo "==> molecule test: $r"
        (cd "{{ justfile_directory() }}/roles/$r" && molecule test)
    done
