"""Tests for community plugin registry/tap metadata."""

from __future__ import annotations

import json
from pathlib import Path

import pytest

from hermes_cli.plugin_registry import (
    PLUGIN_REGISTRY_SCHEMA,
    PluginRegistryValidationError,
    load_registry_plugins,
    search_registry_plugins,
    validate_registry_document,
)


REPO_ROOT = Path(__file__).resolve().parents[2]


def _valid_registry() -> dict:
    return {
        "$schema": "https://hermes-agent.nousresearch.com/plugin-registry/schema.json",
        "version": 1,
        "plugins": [
            {
                "name": "hermes-jira",
                "description": "Jira issue integration for Hermes Agent.",
                "maintainer": "Nous Research",
                "tags": ["issues", "jira"],
                "pip_name": "hermes-jira",
            }
        ],
    }


def test_validate_registry_document_accepts_curated_plugin_entry():
    """Registry entries describe one plugin and exactly one install target."""
    doc = validate_registry_document(_valid_registry())

    assert doc["version"] == 1
    assert doc["plugins"][0]["name"] == "hermes-jira"
    assert doc["plugins"][0]["tier"] == "community"
    assert doc["plugins"][0]["pip_name"] == "hermes-jira"
    assert doc["plugins"][0]["tags"] == ["issues", "jira"]


def test_validate_registry_document_accepts_core_and_extra_entries():
    """Official core/extra plugins share the registry with community plugins."""
    doc = validate_registry_document(
        {
            "version": 1,
            "plugins": [
                {
                    "name": "disk-cleanup",
                    "description": "Bundled cleanup plugin.",
                    "maintainer": "Hermes Agent",
                    "tags": ["core", "maintenance"],
                    "bundled_key": "disk-cleanup",
                },
                {
                    "name": "hermes-slack",
                    "tier": "extra",
                    "description": "Slack gateway adapter.",
                    "maintainer": "Hermes Agent",
                    "tags": ["slack", "messaging"],
                    "extra_name": "slack",
                    "plugin_key": "hermes-slack",
                },
            ],
        }
    )

    assert doc["plugins"][0]["tier"] == "core"
    assert doc["plugins"][0]["bundled_key"] == "disk-cleanup"
    assert doc["plugins"][1]["tier"] == "extra"
    assert doc["plugins"][1]["extra_name"] == "slack"
    assert doc["plugins"][1]["plugin_key"] == "hermes-slack"


@pytest.mark.parametrize(
    "source_patch",
    [
        {},
        {"pip_name": "hermes-jira", "git_url": "https://github.com/example/hermes-jira.git"},
        {"pip_name": "hermes-jira", "tarball_url": "https://example.com/hermes-jira.tar.gz"},
    ],
)
def test_validate_registry_document_requires_exactly_one_install_source(source_patch):
    """A registry entry must resolve unambiguously to pip, git, or tarball."""
    doc = _valid_registry()
    plugin = doc["plugins"][0]
    for key in ("pip_name", "git_url", "tarball_url"):
        plugin.pop(key, None)
    plugin.update(source_patch)

    with pytest.raises(PluginRegistryValidationError, match="exactly one install source"):
        validate_registry_document(doc)


def test_validate_registry_document_rejects_duplicate_plugin_names():
    """Taps should not contain two entries that resolve to the same plugin name."""
    doc = _valid_registry()
    doc["plugins"].append(
        {
            "name": "hermes-jira",
            "description": "Duplicate with a different install source.",
            "maintainer": "Nous Research",
            "tags": ["issues"],
            "git_url": "https://github.com/example/hermes-jira.git",
        }
    )

    with pytest.raises(PluginRegistryValidationError, match="Duplicate plugin name"):
        validate_registry_document(doc)


def test_validate_registry_document_rejects_bad_plugin_name_and_tags():
    """Names and tags are machine-facing identifiers, not arbitrary text blobs."""
    doc = _valid_registry()
    doc["plugins"][0]["name"] = "../../oops"
    doc["plugins"][0]["tags"] = ["jira", "bad tag with spaces"]

    with pytest.raises(PluginRegistryValidationError, match="name"):
        validate_registry_document(doc)


def test_static_registry_schema_matches_runtime_constant():
    """The published schema file should be the same schema Hermes uses."""
    schema_path = REPO_ROOT / "website" / "static" / "plugin-registry" / "schema.json"

    schema = json.loads(schema_path.read_text(encoding="utf-8"))

    assert schema == PLUGIN_REGISTRY_SCHEMA
    assert schema["$id"] == "https://hermes-agent.nousresearch.com/plugin-registry/schema.json"
    assert "bundled_key" in schema["$defs"]["plugin"]["properties"]
    assert "extra_name" in schema["$defs"]["plugin"]["properties"]
    assert "pip_name" in schema["$defs"]["plugin"]["properties"]
    assert "git_url" in schema["$defs"]["plugin"]["properties"]
    assert "tarball_url" in schema["$defs"]["plugin"]["properties"]


def test_static_registry_index_validates_with_curated_core_and_extra_entries():
    """The curated registry ships installable core/extra metadata."""
    index_path = REPO_ROOT / "website" / "static" / "plugin-registry" / "index.json"

    index = json.loads(index_path.read_text(encoding="utf-8"))
    normalized = validate_registry_document(index)

    assert normalized["version"] == 1
    by_name = {plugin["name"]: plugin for plugin in normalized["plugins"]}
    assert by_name["disk-cleanup"]["tier"] == "core"
    assert by_name["disk-cleanup"]["bundled_key"] == "disk-cleanup"
    assert by_name["hermes-slack"]["tier"] == "extra"
    assert by_name["hermes-slack"]["extra_name"] == "slack"


def test_load_registry_plugins_and_search_local_tap(tmp_path):
    """Search uses arbitrary tap URLs/paths, not only the built-in index."""
    tap_path = tmp_path / "tap.json"
    tap_path.write_text(
        json.dumps(
            {
                "version": 1,
                "plugins": [
                    {
                        "name": "hermes-linear",
                        "description": "Linear issue integration.",
                        "maintainer": "Acme",
                        "tags": ["issues", "linear"],
                        "git_url": "https://github.com/acme/hermes-linear.git",
                    }
                ],
            }
        ),
        encoding="utf-8",
    )

    plugins, errors = load_registry_plugins([str(tap_path)], include_default=False)
    assert errors == []
    assert plugins[0]["name"] == "hermes-linear"
    assert plugins[0]["_registry_url"] == str(tap_path)

    matches, errors = search_registry_plugins("linear issues", [str(tap_path)], include_default=False)
    assert errors == []
    assert [plugin["name"] for plugin in matches] == ["hermes-linear"]
