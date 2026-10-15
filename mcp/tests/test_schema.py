"""The tool list itself: what every client sees first. Flat schemas and clear
annotations are what keep weaker tool-callers working."""

import json

import pytest

from homehub_mcp.server import build_server


@pytest.fixture
def tools(config, backend):
    import anyio

    return anyio.run(build_server(config, backend).list_tools)


def test_tool_names_are_prefixed_and_short(tools):
    assert len(tools) == 31
    for t in tools:
        assert t.name.split("_")[0] in {"calendar", "tapes", "library", "homehub"}, t.name
        assert len(t.name) <= 64 and t.name.replace("_", "").isalnum() and t.name.islower()


def test_schemas_are_flat(tools):
    for t in tools:
        schema = json.dumps(t.input_schema)
        for word in ("anyOf", "oneOf", "allOf", "$ref", '"null"'):
            assert word not in schema, (t.name, word)


def test_every_tool_is_described_and_annotated(tools):
    for t in tools:
        assert t.description and len(t.description) > 20, t.name
        a = t.annotations
        assert a is not None and a.read_only_hint is not None, t.name
        if a.read_only_hint:
            assert not a.destructive_hint, t.name


def test_assistants_cannot_delete(tools):
    """Deleting is left to the user, in the apps (prompt-injected text in a feed
    title must not be able to remove anything)."""
    assert not [t.name for t in tools if t.annotations.destructive_hint]
    assert not [t.name for t in tools if "delete" in t.name]


def test_the_day_marker_is_never_exposed(tools):
    assert "marker" not in json.dumps([t.model_dump() for t in tools]).lower()
