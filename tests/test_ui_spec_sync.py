"""Guard against drift of the shared home-ui-spec primitives block.

Canonical copy: docs/primitives.css (see docs/ui-spec.md, Distribution).
"""
from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parents[1]
EMBEDDED = REPO_ROOT / "frontend" / "src" / "index.css"
CANONICAL = REPO_ROOT / "docs" / "primitives.css"

START = "/* >>> home-ui-spec primitives"
END = "/* <<< home-ui-spec primitives */"


def extract_block(path: Path) -> str:
    text = path.read_text()
    start = text.find(START)
    end = text.find(END)
    assert start != -1 and end != -1, f"{path}: missing home-ui-spec primitives markers"
    return text[start : end + len(END)].strip()


def test_primitives_match_canonical():
    assert extract_block(EMBEDDED) == extract_block(CANONICAL), (
        "Shared primitives block in frontend/src/index.css has drifted from "
        "docs/primitives.css; paste the canonical block verbatim (ui-spec.md, Distribution)."
    )
