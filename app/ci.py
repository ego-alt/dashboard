"""The one rule for whether a commit passed CI, used by the Deploy tab
(app/github.py) and by the Pi's deploy script, which runs this file on the
GitHub API's answer: ``python3 -I app/ci.py < runs.json``.

Standard library only: the deploy script runs it with the Pi's own python3.
"""
import json
import sys


def result(runs: list[dict]) -> str:
    """passed | failed | running | none, from a commit's ci.yml workflow runs.

    A push can start two runs and the concurrency rule cancels one, so only the
    runs that finished count.
    """
    if not runs:
        return "none"
    if any(r.get("status") != "completed" for r in runs):
        return "running"
    finished = [r for r in runs if r.get("conclusion") not in ("cancelled", "skipped")]
    return "passed" if finished and all(r.get("conclusion") == "success" for r in finished) else "failed"


if __name__ == "__main__":
    print(result(json.load(sys.stdin).get("workflow_runs", [])))
