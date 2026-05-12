"""Community plugin registry schema and validation helpers.

This module is intentionally dependency-free.  The public registry/tap format is
also published as ``website/plugin-registry/schema.json`` so external taps can
validate their JSON without importing Hermes.
"""

from __future__ import annotations

import copy
import re
from collections.abc import Mapping
from typing import Any

PLUGIN_REGISTRY_SCHEMA_ID = "https://hermes-agent.nousresearch.com/plugin-registry/schema.json"
PLUGIN_REGISTRY_VERSION = 1
INSTALL_SOURCE_FIELDS = ("pip_name", "git_url", "tarball_url")

_IDENTIFIER_RE = re.compile(r"^[a-z0-9][a-z0-9._-]{0,127}$")
_PIP_NAME_RE = re.compile(r"^[A-Za-z0-9][A-Za-z0-9._-]{0,127}$")
_GIT_URL_RE = re.compile(r"^(https://|ssh://|git@).+")
_HTTPS_URL_RE = re.compile(r"^https://.+")

PLUGIN_REGISTRY_SCHEMA: dict[str, Any] = {
    "$schema": "https://json-schema.org/draft/2020-12/schema",
    "$id": PLUGIN_REGISTRY_SCHEMA_ID,
    "title": "Hermes Agent Plugin Registry",
    "description": "Static registry/tap format for community Hermes Agent plugins.",
    "type": "object",
    "additionalProperties": False,
    "required": ["version", "plugins"],
    "properties": {
        "$schema": {"type": "string"},
        "version": {"const": PLUGIN_REGISTRY_VERSION},
        "updated_at": {
            "type": "string",
            "description": "Optional ISO-8601 timestamp for the registry document.",
        },
        "plugins": {
            "type": "array",
            "items": {"$ref": "#/$defs/plugin"},
            "uniqueItems": True,
        },
    },
    "$defs": {
        "identifier": {
            "type": "string",
            "pattern": "^[a-z0-9][a-z0-9._-]{0,127}$",
        },
        "plugin": {
            "type": "object",
            "additionalProperties": False,
            "required": ["name", "description", "maintainer", "tags"],
            "oneOf": [
                {"required": ["pip_name"]},
                {"required": ["git_url"]},
                {"required": ["tarball_url"]},
            ],
            "properties": {
                "name": {"$ref": "#/$defs/identifier"},
                "description": {
                    "type": "string",
                    "minLength": 1,
                    "maxLength": 500,
                },
                "maintainer": {
                    "type": "string",
                    "minLength": 1,
                    "maxLength": 200,
                },
                "tags": {
                    "type": "array",
                    "items": {"$ref": "#/$defs/identifier"},
                    "uniqueItems": True,
                },
                "pip_name": {
                    "type": "string",
                    "pattern": "^[A-Za-z0-9][A-Za-z0-9._-]{0,127}$",
                },
                "git_url": {
                    "type": "string",
                    "pattern": "^(https://|ssh://|git@).+",
                },
                "tarball_url": {
                    "type": "string",
                    "pattern": "^https://.+",
                },
                "homepage": {"type": "string", "pattern": "^https://.+"},
                "source_url": {"type": "string", "pattern": "^https://.+"},
                "license": {"type": "string", "maxLength": 100},
            },
        },
    },
}


class PluginRegistryValidationError(ValueError):
    """Raised when a plugin registry/tap JSON document is malformed."""


def _fail(path: str, message: str) -> None:
    raise PluginRegistryValidationError(f"{path}: {message}")


def _require_mapping(value: Any, path: str) -> Mapping[str, Any]:
    if not isinstance(value, Mapping):
        _fail(path, "must be an object")
    return value


def _require_string(value: Any, path: str, *, pattern: re.Pattern[str] | None = None) -> str:
    if not isinstance(value, str) or not value.strip():
        _fail(path, "must be a non-empty string")
    text = value.strip()
    if pattern is not None and not pattern.fullmatch(text):
        _fail(path, f"invalid value: {text!r}")
    return text


def _validate_tags(value: Any, path: str) -> list[str]:
    if not isinstance(value, list):
        _fail(path, "must be a list")
    seen: set[str] = set()
    tags: list[str] = []
    for index, raw_tag in enumerate(value):
        tag = _require_string(raw_tag, f"{path}[{index}]", pattern=_IDENTIFIER_RE)
        if tag in seen:
            _fail(f"{path}[{index}]", f"duplicate tag: {tag}")
        seen.add(tag)
        tags.append(tag)
    return tags


def _validate_install_source(plugin: Mapping[str, Any], path: str) -> dict[str, str]:
    present = [field for field in INSTALL_SOURCE_FIELDS if plugin.get(field)]
    if len(present) != 1:
        _fail(path, "must declare exactly one install source: pip_name, git_url, or tarball_url")

    field = present[0]
    pattern = {
        "pip_name": _PIP_NAME_RE,
        "git_url": _GIT_URL_RE,
        "tarball_url": _HTTPS_URL_RE,
    }[field]
    return {field: _require_string(plugin[field], f"{path}.{field}", pattern=pattern)}


def _validate_plugin_entry(raw_plugin: Any, path: str) -> dict[str, Any]:
    plugin = _require_mapping(raw_plugin, path)
    allowed = set(PLUGIN_REGISTRY_SCHEMA["$defs"]["plugin"]["properties"])
    unknown = sorted(set(plugin) - allowed)
    if unknown:
        _fail(path, f"unknown field(s): {', '.join(unknown)}")

    normalized: dict[str, Any] = {
        "name": _require_string(plugin.get("name"), f"{path}.name", pattern=_IDENTIFIER_RE),
        "description": _require_string(plugin.get("description"), f"{path}.description"),
        "maintainer": _require_string(plugin.get("maintainer"), f"{path}.maintainer"),
        "tags": _validate_tags(plugin.get("tags"), f"{path}.tags"),
    }
    normalized.update(_validate_install_source(plugin, path))

    for optional_url in ("homepage", "source_url"):
        if plugin.get(optional_url):
            normalized[optional_url] = _require_string(
                plugin[optional_url], f"{path}.{optional_url}", pattern=_HTTPS_URL_RE
            )
    if plugin.get("license"):
        normalized["license"] = _require_string(plugin["license"], f"{path}.license")
    return normalized


def validate_registry_document(document: Any) -> dict[str, Any]:
    """Validate and normalize a Hermes plugin registry/tap document.

    The validator mirrors the published JSON Schema but avoids a runtime
    dependency on ``jsonschema``. It returns a new normalized dict and never
    mutates the caller's object.
    """
    root = _require_mapping(document, "registry")
    allowed_root = {"$schema", "version", "updated_at", "plugins"}
    unknown_root = sorted(set(root) - allowed_root)
    if unknown_root:
        _fail("registry", f"unknown field(s): {', '.join(unknown_root)}")

    if root.get("version") != PLUGIN_REGISTRY_VERSION:
        _fail("registry.version", f"must be {PLUGIN_REGISTRY_VERSION}")
    plugins = root.get("plugins")
    if not isinstance(plugins, list):
        _fail("registry.plugins", "must be a list")

    normalized: dict[str, Any] = {"version": PLUGIN_REGISTRY_VERSION, "plugins": []}
    if root.get("$schema"):
        normalized["$schema"] = _require_string(root["$schema"], "registry.$schema")
    if root.get("updated_at"):
        normalized["updated_at"] = _require_string(root["updated_at"], "registry.updated_at")

    seen_names: set[str] = set()
    for index, raw_plugin in enumerate(plugins):
        plugin = _validate_plugin_entry(raw_plugin, f"registry.plugins[{index}]")
        name_key = plugin["name"].lower()
        if name_key in seen_names:
            _fail(f"registry.plugins[{index}].name", f"Duplicate plugin name: {plugin['name']}")
        seen_names.add(name_key)
        normalized["plugins"].append(plugin)

    return copy.deepcopy(normalized)
