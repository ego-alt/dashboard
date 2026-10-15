#!/usr/bin/env bash
# Pull-based deploy for the home stack. Run every few minutes by the
# home-stack-deploy systemd timer (install with scripts/install-deploy-timer.sh).
#
# For each repo (dashboard, library, calendar, tapes), sitting side by side in
# one folder:
#   1. fetch its deploy branch; stop if nothing new
#   2. only continue if the new commit's CI workflow passed on GitHub
#   3. fast-forward, rebuild and restart that one service
#   4. wait for its health check; if it fails, roll back to the previous
#      commit and rebuild that, and don't retry the bad commit
#
# It never touches a repo with local changes or a diverged branch, and it
# never takes instructions from outside: it only reads public CI results.
#
# Logs go to stdout (journald under systemd); the latest outcome per repo is
# written to $DEPLOY_STATE_DIR/status.json.
#
# Env:
#   DEPLOY_STATE_DIR    state + status file   (default /var/lib/home-stack-deploy)
#   DEPLOY_HEALTH_WAIT  seconds to wait for a healthy container (default 180)
#   DEPLOY_REQUIRE_CI   set to 0 to skip the CI check (testing only)
#   DEPLOY_GITHUB_TOKEN optional read-only token; raises GitHub's API limit from
#                       60 to 5,000 requests/hour (not needed for public repos
#                       at this polling rate)

set -euo pipefail

STACK_DIR=$(cd "$(dirname "$0")/../.." && pwd)   # folder holding all the repos
COMPOSE_DIR="$STACK_DIR/dashboard"
STATE_DIR=${DEPLOY_STATE_DIR:-/var/lib/home-stack-deploy}
HEALTH_WAIT=${DEPLOY_HEALTH_WAIT:-180}
REQUIRE_CI=${DEPLOY_REQUIRE_CI:-1}

# repo folder : deploy branch : compose service : container name
REPOS=(
  "dashboard:master:dashboard:dashboard"
  "library:master:library:library"
  "calendar:master:calendar:calendar"
  "tapes:main:music:music"
)

mkdir -p "$STATE_DIR"

# One run at a time (a slow build can outlast the timer interval).
if command -v flock >/dev/null 2>&1; then
  exec 9>"$STATE_DIR/lock"
  if ! flock -n 9; then
    echo "another deploy is running; skipping this tick"
    exit 0
  fi
fi

log() { echo "[$1] ${*:2}"; }

compose() { (cd "$COMPOSE_DIR" && docker compose "$@"); }

# owner/name from the origin URL (https or ssh form).
github_slug() {
  git -C "$1" remote get-url origin | sed -E 's#(\.git)?$##; s#^.*github\.com[:/]##'
}

# Prints the CI workflow's result for a commit: success | failure | pending | none
ci_result() {
  local slug=$1 sha=$2 json code auth=()
  [[ -n ${DEPLOY_GITHUB_TOKEN:-} ]] && auth=(-H "Authorization: Bearer $DEPLOY_GITHUB_TOKEN")
  json=$(curl -sS --max-time 20 -w '\n%{http_code}' ${auth[@]+"${auth[@]}"} \
    "https://api.github.com/repos/$slug/actions/workflows/ci.yml/runs?head_sha=$sha&per_page=5" \
    2>/dev/null) || { echo pending; return; }   # API unreachable: try next tick
  code=${json##*$'\n'}
  json=${json%$'\n'*}
  case $code in
    200) ;;
    404) echo none; return ;;      # no ci.yml workflow in this repo
    *)   echo pending; return ;;   # rate limited (403/429) or a GitHub hiccup
  esac
  python3 -c '
import json, sys
runs = json.load(sys.stdin).get("workflow_runs", [])
if not runs:
    print("none")
elif any(r["status"] != "completed" for r in runs):
    print("pending")
elif all(r["conclusion"] == "success" for r in runs):
    print("success")
else:
    print("failure")
' <<<"$json"
}

# Wait for the container's healthcheck. Containers without one count as
# healthy once running.
wait_healthy() {
  local container=$1 waited=0 health
  while (( waited < HEALTH_WAIT )); do
    health=$(docker inspect -f '{{if .State.Health}}{{.State.Health.Status}}{{else}}{{.State.Status}}{{end}}' \
      "$container" 2>/dev/null || echo missing)
    case $health in
      healthy|running) return 0 ;;
      unhealthy|exited|dead) return 1 ;;
    esac
    sleep 5
    waited=$((waited + 5))
  done
  return 1
}

restart_service() {
  local name=$1 service=$2
  compose build "$service" && compose up -d "$service" || return 1
  if [[ $name == dashboard ]]; then
    # The dashboard repo also carries docker-compose.yml and the nginx config:
    # apply compose changes to the other services and reload nginx. mcp is
    # left out here and handled by restart_mcp.
    local others
    others=$(compose config --services | grep -vx mcp | tr '\n' ' ')
    # shellcheck disable=SC2086
    compose up -d $others && docker exec home-nginx nginx -s reload || return 1
    restart_mcp
  fi
}

# The MCP server lives in the dashboard repo but is its own container. Best
# effort: a broken mcp build is logged and recorded, never a reason to roll
# the dashboard back (nginx resolves mcp per request, so nothing else needs it).
restart_mcp() {
  local sha
  sha=$(git -C "$STACK_DIR/dashboard" rev-parse HEAD)
  if compose build mcp && compose up -d mcp && wait_healthy mcp; then
    record mcp "$sha" "deployed"
  else
    log mcp "${sha:0:7}: mcp didn't build or start healthy; the rest of the stack is unaffected"
    record mcp "$sha" "failed"
  fi
}

record() {  # name sha result
  python3 - "$STATE_DIR/status.json" "$1" "$2" "$3" <<'EOF'
import json, sys, time
path, name, sha, result = sys.argv[1:]
try:
    data = json.load(open(path))
except (OSError, ValueError):
    data = {}
data[name] = {"sha": sha, "result": result,
              "at": time.strftime("%Y-%m-%dT%H:%M:%S%z")}
json.dump(data, open(path, "w"), indent=2)
EOF
}

deploy_repo() {
  local name=$1 branch=$2 service=$3 container=$4
  local dir="$STACK_DIR/$name" current target result
  local bad_file="$STATE_DIR/$name.bad"

  [[ -d $dir/.git ]] || { log "$name" "no repo at $dir; skipping"; return; }
  git -C "$dir" fetch -q origin "$branch" || { log "$name" "fetch failed"; return; }
  current=$(git -C "$dir" rev-parse HEAD)
  target=$(git -C "$dir" rev-parse "origin/$branch")
  [[ $current == "$target" ]] && return

  if [[ -f $bad_file && $(cat "$bad_file") == "$target" ]]; then
    return   # already failed and rolled back; wait for a newer commit
  fi
  if [[ $(git -C "$dir" rev-parse --abbrev-ref HEAD) != "$branch" ]]; then
    log "$name" "not on $branch; skipping"; return
  fi
  if [[ -n $(git -C "$dir" status --porcelain --untracked-files=no) ]]; then
    log "$name" "has local changes; skipping"; return
  fi
  if ! git -C "$dir" merge-base --is-ancestor "$current" "$target"; then
    log "$name" "local branch has diverged from origin; skipping"; return
  fi

  if [[ $REQUIRE_CI == 1 ]]; then
    result=$(ci_result "$(github_slug "$dir")" "$target")
    case $result in
      success) ;;
      pending) log "$name" "${target:0:7}: CI still running; will check again"; return ;;
      none)    log "$name" "${target:0:7}: no CI run for this commit; not deploying"; return ;;
      *)       log "$name" "${target:0:7}: CI failed; not deploying"
               echo "$target" >"$bad_file"; record "$name" "$target" "ci-failed"; return ;;
    esac
  fi

  log "$name" "deploying ${current:0:7} -> ${target:0:7}"
  # Checked explicitly: set -e is off inside a function called with ||.
  git -C "$dir" merge -q --ff-only "$target" || { log "$name" "fast-forward failed"; return; }
  if restart_service "$name" "$service" && wait_healthy "$container"; then
    log "$name" "${target:0:7} is live"
    rm -f "$bad_file"
    record "$name" "$target" "deployed"
    return
  fi

  log "$name" "${target:0:7} failed to start healthy; rolling back to ${current:0:7}"
  echo "$target" >"$bad_file"
  git -C "$dir" reset -q --hard "$current"
  if restart_service "$name" "$service" && wait_healthy "$container"; then
    record "$name" "$target" "rolled-back"
  else
    log "$name" "rollback to ${current:0:7} is not healthy either; needs a look"
    record "$name" "$target" "rollback-failed"
  fi
}

for entry in "${REPOS[@]}"; do
  IFS=: read -r name branch service container <<<"$entry"
  deploy_repo "$name" "$branch" "$service" "$container" || log "$name" "deploy step errored"
done
