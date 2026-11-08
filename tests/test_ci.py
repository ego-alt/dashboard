"""The CI rule the Deploy tab and the Pi's deploy script share (app/ci.py)."""

import json
import subprocess
import sys
from pathlib import Path

from app.ci import result


def _run(conclusion, status="completed"):
    return {"status": status, "conclusion": conclusion}


def test_result():
    assert result([]) == "none"
    assert result([_run(None, status="in_progress"), _run("success")]) == "running"
    assert result([_run("success")]) == "passed"
    assert result([_run("failure"), _run("success")]) == "failed"
    # A push can start two runs and the concurrency rule cancels one.
    assert result([_run("cancelled"), _run("success")]) == "passed"
    assert result([_run("cancelled")]) == "failed"


def test_the_deploy_script_runs_it_on_githubs_answer():
    """deploy.sh pipes the API's JSON into ``python3 -I app/ci.py``."""
    script = Path(__file__).resolve().parent.parent / "app" / "ci.py"
    answer = json.dumps({"workflow_runs": [_run("cancelled"), _run("success")]})
    out = subprocess.run([sys.executable, "-I", str(script)], input=answer, capture_output=True, text=True, check=True)
    assert out.stdout.strip() == "passed"
