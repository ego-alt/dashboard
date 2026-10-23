#!/usr/bin/env bash
# Pull-based deploy for the home stack. Run every few minutes by the
# home-stack-deploy systemd timer (install with scripts/install-deploy-timer.sh).
#
# For each repo (dashboard, library, calendar, tapes, and every app enabled in
# the dashboard's Deploy tab), sitting side by side in one folder:
#   1. fetch its deploy branch; stop if nothing new
#   2. only continue if the new commit's CI workflow passed on GitHub
#   3. fast-forward, then restart that one service on the image CI built and
#      published for that commit (ghcr.io/<owner>/<repo>:<sha>); only a repo
#      with no such image is built here, as before
#   4. wait for its health check; if it fails, roll back to the previous
#      commit and rebuild that, and don't retry the bad commit
#
# It never touches a repo with local changes or a diverged branch. Its only
# inputs are public CI results and, from the Deploy tab (admins only), which
# apps are enabled ($STATE_DIR/apps/*.json) and "deploy now" requests
# ($STATE_DIR/requests/<name>; a systemd path unit starts a run when one
# appears). Enabled apps are cloned, given a compose service and an nginx
# route (scripts/stack_render.py), and deployed like the rest.
#
# Logs go to stdout (journald under systemd) and, per repo, to
# $STATE_DIR/logs/<name>.log; the latest outcome per repo is written to
# $STATE_DIR/status.json.
#
# Env:
#   DEPLOY_STATE_DIR    state + status file   (default /var/lib/home-stack-deploy)
#   DEPLOY_HEALTH_WAIT  seconds to wait for a healthy container (default 180)
#   DEPLOY_REQUIRE_CI   set to 0 to skip the CI check (testing only)
#   DEPLOY_GITHUB_TOKEN optional read-only token; raises GitHub's API limit from
#                       60 to 5,000 requests/hour (not needed for public repos
#                       at this polling rate). Without it, the token git already
#                       uses for github.com (if any) checks private repos' CI.

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

mkdir -p "$STATE_DIR"/{apps,requests,logs,generated/nginx}
LOG_DIR="$STATE_DIR/logs"
RENDER=(python3 "$COMPOSE_DIR/scripts/stack_render.py")
export DEPLOY_STATE_DIR="$STATE_DIR"
[[ -f $STATE_DIR/generated/compose.apps.yml ]] || "${RENDER[@]}" render >/dev/null

# One run at a time (a slow build can outlast the timer interval).
if command -v flock >/dev/null 2>&1; then
  exec 9>"$STATE_DIR/lock"
  if ! flock -n 9; then
    echo "another deploy is running; skipping this tick"
    exit 0
  fi
fi

log() { echo "$(date '+%F %T') [$1] ${*:2}"; }

compose() { (cd "$COMPOSE_DIR" && docker compose "$@"); }

# owner/name from the origin URL (https or ssh form).
github_slug() {
  git -C "$1" remote get-url origin | sed -E 's#(\.git)?$##; s#^.*github\.com[:/]##'
}

# The token git has saved for github.com, which already clones and fetches
# private repos; empty when there's none.
git_token() {
  printf 'protocol=https\nhost=github.com\n\n' \
    | GIT_TERMINAL_PROMPT=0 git -c credential.interactive=never credential fill 2>/dev/null \
    | sed -n 's/^password=//p'
}

# Prints the CI workflow's result for a commit: success | failure | pending | none
ci_result() {
  local slug=$1 sha=$2 json code header="" token=${DEPLOY_GITHUB_TOKEN:-}
  [[ -z $token ]] && token=$(git_token || true)
  [[ -n $token ]] && header="Authorization: Bearer $token"
  # The header comes in on stdin, so the token never shows up in ps.
  json=$(curl -sS --max-time 20 -w '\n%{http_code}' -H @- <<<"$header" \
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
else:
    # A push can start two runs and the concurrency rule cancels one; only
    # the runs that finished count.
    finished = [r for r in runs if r["conclusion"] not in ("cancelled", "skipped")]
    print("success" if finished and all(r["conclusion"] == "success" for r in finished) else "failure")
' <<<"$json"
}

# Wait for the container's healthcheck. Containers without one count as
# healthy once running; apps from the Deploy tab must also answer their
# manifest's health path over HTTP (probed from the nginx container, so it
# works whatever the app is written in).
wait_healthy() {
  local container=$1 waited=0 health probe=""
  if is_app "$container"; then
    probe=$("${RENDER[@]}" health "$container" 2>/dev/null) || probe=""
  fi
  while (( waited < HEALTH_WAIT )); do
    health=$(docker inspect -f '{{if .State.Health}}{{.State.Health.Status}}{{else}}{{.State.Status}}{{end}}' \
      "$container" 2>/dev/null || echo missing)
    case $health in
      healthy|running)
        [[ -z $probe ]] && return 0
        docker exec home-nginx wget -q -O /dev/null -T 5 "http://$container:${probe% *}${probe#* }" 2>/dev/null \
          && return 0 ;;
      unhealthy|exited|dead) return 1 ;;
    esac
    sleep 5
    waited=$((waited + 5))
  done
  return 1
}

# Reload nginx's config, once it's up. Recreating the services it depends on
# can restart it; a reload sent mid-restart fails, and a fresh start has
# already read the new config. If it's down, start it.
reload_nginx() {
  local waited=0
  until [[ $(docker inspect -f '{{.State.Running}}' home-nginx 2>/dev/null) == true ]]; do
    if (( waited >= 30 )); then
      log nginx "not running; starting it"
      compose up -d nginx >/dev/null 2>&1 || return 1
      sleep 3
      break
    fi
    sleep 2
    waited=$((waited + 2))
  done
  docker exec home-nginx nginx -t >/dev/null 2>&1 || { log nginx "config doesn't pass nginx -t"; return 1; }
  docker exec home-nginx nginx -s reload >/dev/null 2>&1 || sleep 3   # just started: nothing to reload
  [[ $(docker inspect -f '{{.State.Running}}' home-nginx 2>/dev/null) == true ]]
}

# Regenerate the apps' compose services and nginx routes from their checked-out
# homestack.toml, and reload nginx if the routes changed.
render_apps() {
  [[ $("${RENDER[@]}" render) == changed ]] || return 0
  if reload_nginx; then
    log nginx "routes updated for the Deploy tab's apps"
  else
    log nginx "the generated routes don't pass nginx -t; keeping the old ones"
  fi
}

# The image CI built and published for the commit checked out in a repo,
# pulled and tagged as the service's local image (<service>:dev, as the
# compose files name them), so compose runs it without building. Returns 1
# when there's none (a repo without CI's image step, or one not published).
# The tag is the commit, and only commits whose CI passed get this far.
pull_image() {  # repo-folder service [suffix: "-mcp" for the dashboard's mcp]
  local dir=$1 service=$2 suffix=${3:-} sha slug ref
  sha=$(git -C "$dir" rev-parse HEAD)
  slug=$(github_slug "$dir" | tr '[:upper:]' '[:lower:]')
  ref="ghcr.io/$slug$suffix:$sha"
  docker pull -q "$ref" >/dev/null 2>&1 || return 1
  docker tag "$ref" "$service:dev"
  # Keep this and the one before (for a rollback); older pulls go.
  docker images --format '{{.Repository}}:{{.Tag}}' "ghcr.io/$slug$suffix" | tail -n +3 \
    | xargs -r docker rmi >/dev/null 2>&1 || true
}

# The service's image for what's checked out: CI's if it published one,
# else built here (the old way, which the Pi can barely afford).
get_image() {  # name repo-folder service [suffix]
  local name=$1 dir=$2 service=$3 suffix=${4:-}
  if pull_image "$dir" "$service" "$suffix"; then
    log "$name" "running the image CI built for $(git -C "$dir" rev-parse --short HEAD)"
  else
    log "$name" "no image from CI for this commit; building it here"
    compose build "$service"
  fi
}

restart_service() {
  local name=$1 service=$2
  # An app's manifest (port, env, tile) may have changed in the commit just checked out.
  if is_app "$name"; then render_apps; fi
  get_image "$name" "$STACK_DIR/$name" "$service" && compose up -d --no-build "$service" || return 1
  if [[ $name == dashboard ]]; then
    # The dashboard repo also carries docker-compose.yml and the nginx config:
    # apply compose changes to the other services and reload nginx. mcp is
    # left out here and handled by restart_mcp.
    # Apps from the Deploy tab deploy on their own, after their own CI.
    local others
    others=$(compose config --services | grep -vxF -f <(printf '%s\n' mcp ${APP_NAMES[@]+"${APP_NAMES[@]}"}) | tr '\n' ' ')
    # shellcheck disable=SC2086
    compose up -d $others && reload_nginx || return 1
    restart_mcp
  fi
}

# The MCP server lives in the dashboard repo but is its own container. Best
# effort: a broken mcp build is logged and recorded, never a reason to roll
# the dashboard back (nginx resolves mcp per request, so nothing else needs it).
restart_mcp() {
  local sha
  sha=$(git -C "$STACK_DIR/dashboard" rev-parse HEAD)
  if get_image mcp "$STACK_DIR/dashboard" mcp -mcp && compose up -d --no-build mcp && wait_healthy mcp; then
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

is_app() {
  local n
  for n in ${APP_NAMES[@]+"${APP_NAMES[@]}"}; do [[ $n == "$1" ]] && return 0; done
  return 1
}

deploy_repo() {
  local name=$1 branch=$2 service=$3 container=$4 force=${5:-0}
  local dir="$STACK_DIR/$name" current target result
  local bad_file="$STATE_DIR/$name.bad"

  local first=0
  [[ -d $dir/.git ]] || { log "$name" "no repo at $dir; skipping"; return; }
  git -C "$dir" fetch -q origin "$branch" || { log "$name" "fetch failed"; return; }
  current=$(git -C "$dir" rev-parse HEAD)
  target=$(git -C "$dir" rev-parse "origin/$branch")
  if [[ $current == "$target" ]]; then
    # Up to date, unless it was just cloned and has never run, or the Deploy
    # tab asked for a fresh build.
    if docker inspect "$container" >/dev/null 2>&1; then
      (( force )) || return 0
      rm -f "$bad_file"
    fi
    first=1
  fi

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

  if (( first )); then
    log "$name" "building and starting ${target:0:7}"
  else
    log "$name" "deploying ${current:0:7} -> ${target:0:7}"
    # Checked explicitly: set -e is off inside a function called with ||.
    git -C "$dir" merge -q --ff-only "$target" || { log "$name" "fast-forward failed"; return; }
  fi
  if restart_service "$name" "$service" && wait_healthy "$container"; then
    log "$name" "${target:0:7} is live"
    rm -f "$bad_file"
    record "$name" "$target" "deployed"
    return
  fi
  if (( first )); then
    log "$name" "${target:0:7} didn't start healthy; fix and push again"
    echo "$target" >"$bad_file"
    record "$name" "$target" "failed"
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

# "Deploy now" from the Deploy tab: one file per repo name.
declare -A FORCE=()
for req in "$STATE_DIR"/requests/*; do
  [[ -e $req ]] || continue
  FORCE[$(basename "$req")]=1
  rm -f "$req"
done

# Apps enabled in the Deploy tab: clone any that are new, then generate their
# compose services and nginx routes before anything is restarted.
APPS=()
APP_NAMES=()
while IFS= read -r line; do
  [[ -n $line ]] && APPS+=("$line")
done < <("${RENDER[@]}" apps 2>/dev/null)
for entry in ${APPS[@]+"${APPS[@]}"}; do
  IFS=: read -r name branch service container slug <<<"$entry"
  APP_NAMES+=("$name")
  if [[ ! -d $STACK_DIR/$name/.git ]]; then
    log "$name" "new app: cloning $slug" | tee -a "$LOG_DIR/$name.log"
    git clone -q --branch "$branch" "https://github.com/$slug.git" "$STACK_DIR/$name" 2>&1 | tee -a "$LOG_DIR/$name.log" \
      || log "$name" "clone failed; will try again next run" | tee -a "$LOG_DIR/$name.log"
  fi
done

# Apps switched off in the Deploy tab: stop and remove their containers (their
# folders and data stay on disk).
touch "$STATE_DIR/generated/running-apps"
while IFS= read -r gone; do
  [[ -n $gone ]] || continue
  log "$gone" "removed in the Deploy tab: stopping it" | tee -a "$LOG_DIR/$gone.log"
  docker rm -f "$gone" >/dev/null 2>&1 || true
done < <(grep -vxF -f <(printf '%s\n' "" ${APP_NAMES[@]+"${APP_NAMES[@]}"}) "$STATE_DIR/generated/running-apps" || true)
printf '%s\n' ${APP_NAMES[@]+"${APP_NAMES[@]}"} >"$STATE_DIR/generated/running-apps"

render_apps

for entry in "${REPOS[@]}" ${APPS[@]+"${APPS[@]}"}; do
  IFS=: read -r name branch service container _ <<<"$entry"
  {
    deploy_repo "$name" "$branch" "$service" "$container" "${FORCE[$name]:-0}" || log "$name" "deploy step errored"
  } 2>&1 | tee -a "$LOG_DIR/$name.log"
  # Keep each log to its last 3,000 lines.
  if [[ -f $LOG_DIR/$name.log ]] && (( $(wc -l <"$LOG_DIR/$name.log") > 3000 )); then
    tail -n 2000 "$LOG_DIR/$name.log" >"$LOG_DIR/$name.log.tmp" && mv "$LOG_DIR/$name.log.tmp" "$LOG_DIR/$name.log"
  fi
done

# Whatever happened above, nginx is the front door to everything: never
# leave it stopped.
if [[ $(docker inspect -f '{{.State.Running}}' home-nginx 2>/dev/null) != true ]]; then
  log nginx "found stopped at the end of the run; starting it"
  compose up -d nginx >/dev/null 2>&1 || log nginx "couldn't start it; needs a look"
fi

# What each repo has checked out right now, for the Deploy tab's "Running"
# column (true even for repos no deploy has touched yet).
heads=()
for entry in "${REPOS[@]}" ${APPS[@]+"${APPS[@]}"}; do
  IFS=: read -r name _ <<<"$entry"
  sha=$(git -C "$STACK_DIR/$name" rev-parse HEAD 2>/dev/null) && heads+=("$name=$sha")
done
python3 - "$STATE_DIR/status.json" ${heads[@]+"${heads[@]}"} <<'EOF'
import json, sys
path, pairs = sys.argv[1], sys.argv[2:]
try:
    data = json.load(open(path))
except (OSError, ValueError):
    data = {}
data["_heads"] = dict(p.split("=", 1) for p in pairs)
json.dump(data, open(path, "w"), indent=2)
EOF
