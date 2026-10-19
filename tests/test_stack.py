"""scripts/stack.py: the app registry and the files generated from it."""
import importlib.util
import pathlib
import sys

import pytest

ROOT = pathlib.Path(__file__).resolve().parent.parent
spec = importlib.util.spec_from_file_location("stack", ROOT / "scripts" / "stack.py")
stack = importlib.util.module_from_spec(spec)
spec.loader.exec_module(stack)


@pytest.fixture
def sandbox(tmp_path, monkeypatch):
    monkeypatch.setattr(stack, "REGISTRY", tmp_path / "apps.toml")
    monkeypatch.setattr(stack, "COMPOSE_OUT", tmp_path / "compose.apps.yml")
    monkeypatch.setattr(stack, "NGINX_OUT", tmp_path / "apps")
    return tmp_path


APP = {"name": "situation", "repo": "ego-alt/situation", "branch": "main", "title": "Situation",
       "description": 'World news, "on a map"', "icon": "globe", "env": {"NTFY_TOPIC": "${NTFY_TOPIC}"}}


def test_registry_round_trip(sandbox):
    stack.add_to_registry(APP)
    stack.add_to_registry({**APP, "title": "Situation room"})       # re-adding replaces
    apps = stack.load_apps()
    assert len(apps) == 1 and apps[0]["title"] == "Situation room"
    assert apps[0]["description"] == 'World news, "on a map"' and apps[0]["env"] == APP["env"]


def test_render_writes_compose_and_nginx(sandbox):
    stack.add_to_registry(APP)
    stack.render()
    compose = (sandbox / "compose.apps.yml").read_text()
    assert "build: ../situation" in compose and 'APPLICATION_ROOT: "/situation"' in compose
    assert 'NTFY_TOPIC: "${NTFY_TOPIC}"' in compose and "healthz" in compose
    nginx = (sandbox / "apps" / "situation.locations").read_text()
    assert "auth_request       /auth/verify;" in nginx
    assert "set                $app_situation http://situation:8000;" in nginx
    assert "X-Forwarded-Prefix /situation;" in nginx


def test_check_spots_stale_and_removed_apps(sandbox):
    stack.add_to_registry(APP)
    assert stack.render(check=True) is False                       # nothing generated yet
    stack.render()
    assert stack.render(check=True) is True
    (sandbox / "apps.toml").write_text("")                         # app removed from the registry
    assert stack.render(check=True) is False
    stack.render()
    assert not list((sandbox / "apps").glob("*.locations"))


def test_repos_line_for_deploy_sh(sandbox, capsys):
    stack.add_to_registry(APP)
    sys.argv = ["stack.py", "repos"]
    stack.main()
    assert capsys.readouterr().out.strip() == "situation:main:situation:situation:ego-alt/situation"


def test_names(sandbox):
    assert stack.NAME_RE.match("situation") and stack.NAME_RE.match("news-room")
    assert not stack.NAME_RE.match("News") and not stack.NAME_RE.match("1app")
    assert "library" in stack.RESERVED and "login" in stack.RESERVED


def test_the_repo_matches_its_registry():
    assert stack.render(check=True)
