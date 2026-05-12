"""Community plugin registry schema, tap loading, and validation helpers.

This module is intentionally dependency-light (stdlib only).  The public
registry/tap format is also published as ``website/static/plugin-registry/schema.json``
so external taps can validate their JSON without importing Hermes.
"""

from __future__ import annotations

import copy
import json
import logging
import re
import urllib.parse
import urllib.request
from collections.abc import Iterable, Mapping
from pathlib import Path
from typing import Any

PLUGIN_REGISTRY_SCHEMA_ID = "https://hermes-agent.nousresearch.com/plugin-registry/schema.json"
PLUGIN_REGISTRY_INDEX_URL = "https://hermes-agent.nousresearch.com/plugin-registry/index.json"
PLUGIN_REGISTRY_VERSION = 1
INSTALL_SOURCE_FIELDS = ("bundled_key", "extra_name", "pip_name", "git_url", "tarball_url")
PLUGIN_TIERS = ("core", "extra", "community")
_TIER_SORT_ORDER = {tier: index for index, tier in enumerate(PLUGIN_TIERS)}

_IDENTIFIER_RE = re.compile(r"^[a-z0-9][a-z0-9._-]{0,127}$")
_PLUGIN_KEY_RE = re.compile(r"^[a-z0-9][a-z0-9._/-]{0,127}$")
_PIP_NAME_RE = re.compile(r"^[A-Za-z0-9][A-Za-z0-9._-]{0,127}$")
_EXTRA_NAME_RE = re.compile(r"^[A-Za-z0-9][A-Za-z0-9._-]{0,127}$")
_GIT_URL_RE = re.compile(r"^(https://|ssh://|git@).+")
_HTTPS_URL_RE = re.compile(r"^https://.+")

logger = logging.getLogger(__name__)

PLUGIN_REGISTRY_SCHEMA: dict[str, Any] = {
    "$schema": "https://json-schema.org/draft/2020-12/schema",
    "$id": PLUGIN_REGISTRY_SCHEMA_ID,
    "title": "Hermes Agent Plugin Registry",
    "description": "Static registry/tap format for Hermes Agent core, extra, and community plugins.",
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
        "plugin_key": {
            "type": "string",
            "pattern": "^[a-z0-9][a-z0-9._/-]{0,127}$",
        },
        "plugin": {
            "type": "object",
            "additionalProperties": False,
            "required": ["name", "description", "maintainer", "tags"],
            "oneOf": [
                {"required": ["bundled_key"]},
                {"required": ["extra_name"]},
                {"required": ["pip_name"]},
                {"required": ["git_url"]},
                {"required": ["tarball_url"]},
            ],
            "properties": {
                "name": {"$ref": "#/$defs/identifier"},
                "tier": {"type": "string", "enum": list(PLUGIN_TIERS)},
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
                "bundled_key": {"$ref": "#/$defs/plugin_key"},
                "plugin_key": {"$ref": "#/$defs/plugin_key"},
                "extra_name": {
                    "type": "string",
                    "pattern": "^[A-Za-z0-9][A-Za-z0-9._-]{0,127}$",
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


class PluginRegistryLoadError(RuntimeError):
    """Raised when a registry/tap URL cannot be loaded or parsed."""


def _fail(path: str, message: str) -> None:
    raise PluginRegistryValidationError(f"{path}: {message}")


def _require_mapping(value: Any, path: str) -> Mapping[str, Any]:
    if not isinstance(value, Mapping):
        _fail(path, "must be an object")
    return value


def _require_string(
    value: Any,
    path: str,
    *,
    pattern: re.Pattern[str] | None = None,
    max_length: int | None = None,
) -> str:
    if not isinstance(value, str) or not value.strip():
        _fail(path, "must be a non-empty string")
    text = value.strip()
    if max_length is not None and len(text) > max_length:
        _fail(path, f"must be at most {max_length} characters")
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


def _validate_tier(value: Any, path: str, install_field: str) -> str:
    if value is None:
        if install_field == "bundled_key":
            return "core"
        if install_field == "extra_name":
            return "extra"
        return "community"
    tier = _require_string(value, path)
    if tier not in PLUGIN_TIERS:
        _fail(path, f"must be one of: {', '.join(PLUGIN_TIERS)}")
    return tier


def _validate_install_source(plugin: Mapping[str, Any], path: str) -> dict[str, str]:
    # Count presence, not truthiness, to mirror the public JSON Schema oneOf:
    # a second source with an empty value is still an ambiguous second source,
    # not an absent field.
    present = [field for field in INSTALL_SOURCE_FIELDS if field in plugin]
    if len(present) != 1:
        _fail(
            path,
            "must declare exactly one install source: bundled_key, extra_name, "
            "pip_name, git_url, or tarball_url",
        )

    field = present[0]
    pattern = {
        "bundled_key": _PLUGIN_KEY_RE,
        "extra_name": _EXTRA_NAME_RE,
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

    install_source = _validate_install_source(plugin, path)
    install_field = next(iter(install_source))
    normalized: dict[str, Any] = {
        "name": _require_string(plugin.get("name"), f"{path}.name", pattern=_IDENTIFIER_RE),
        "tier": _validate_tier(plugin.get("tier"), f"{path}.tier", install_field),
        "description": _require_string(plugin.get("description"), f"{path}.description", max_length=500),
        "maintainer": _require_string(plugin.get("maintainer"), f"{path}.maintainer", max_length=200),
        "tags": _validate_tags(plugin.get("tags"), f"{path}.tags"),
    }
    normalized.update(install_source)

    if plugin.get("plugin_key"):
        normalized["plugin_key"] = _require_string(
            plugin["plugin_key"], f"{path}.plugin_key", pattern=_PLUGIN_KEY_RE
        )

    for optional_url in ("homepage", "source_url"):
        if plugin.get(optional_url):
            normalized[optional_url] = _require_string(
                plugin[optional_url], f"{path}.{optional_url}", pattern=_HTTPS_URL_RE
            )
    if plugin.get("license"):
        normalized["license"] = _require_string(plugin["license"], f"{path}.license", max_length=100)
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


def packaged_registry_index_path() -> Path | None:
    """Return the checked-out/static registry index path when available."""
    path = Path(__file__).resolve().parent.parent / "website" / "static" / "plugin-registry" / "index.json"
    return path if path.exists() else None


def default_registry_url() -> str:
    """Return the default registry source.

    In a source checkout we prefer the local static index to avoid network calls
    during tests and development. Installed packages fall back to the public URL.
    """
    local = packaged_registry_index_path()
    return str(local) if local is not None else PLUGIN_REGISTRY_INDEX_URL


def get_configured_registry_urls(*, include_default: bool = True) -> list[str]:
    """Return registry/tap URLs from config, optionally prefixed by the default."""
    urls: list[str] = []
    if include_default:
        urls.append(default_registry_url())
    try:
        from hermes_cli.config import load_config

        config = load_config()
        plugins_cfg = config.get("plugins") if isinstance(config, dict) else {}
        configured = []
        if isinstance(plugins_cfg, dict):
            configured = plugins_cfg.get("registry_urls") or plugins_cfg.get("registries") or []
        if isinstance(configured, str):
            configured = [configured]
        if isinstance(configured, list):
            urls.extend(str(url).strip() for url in configured if str(url).strip())
    except Exception as exc:  # pragma: no cover - defensive config fallback
        logger.debug("Could not read plugin registry urls from config: %s", exc)
    return _dedupe_preserve_order(urls)


def save_configured_registry_urls(urls: Iterable[str]) -> None:
    """Persist user-added plugin registry/tap URLs in ``config.yaml``."""
    from hermes_cli.config import load_config, save_config

    clean = [str(url).strip() for url in urls if str(url).strip()]
    config = load_config()
    if "plugins" not in config or not isinstance(config.get("plugins"), dict):
        config["plugins"] = {}
    config["plugins"]["registry_urls"] = _dedupe_preserve_order(clean)
    # Drop the pre-schema alias if present so config has one canonical key.
    config["plugins"].pop("registries", None)
    save_config(config)


def add_configured_registry_url(url: str) -> list[str]:
    """Add a user registry/tap URL and return the new configured list."""
    existing = get_configured_registry_urls(include_default=False)
    clean_url = _normalize_registry_source(url)
    if clean_url not in existing:
        existing.append(clean_url)
        save_configured_registry_urls(existing)
    return existing


def remove_configured_registry_url(url: str) -> list[str]:
    """Remove a user registry/tap URL and return the new configured list."""
    clean_url = _normalize_registry_source(url)
    existing = [u for u in get_configured_registry_urls(include_default=False) if u != clean_url]
    save_configured_registry_urls(existing)
    return existing


def load_registry_document(source: str, *, timeout: float = 10.0) -> dict[str, Any]:
    """Load and validate one registry/tap document from a URL or local path."""
    text = _read_registry_source(source, timeout=timeout)
    try:
        document = json.loads(text)
    except json.JSONDecodeError as exc:
        raise PluginRegistryLoadError(f"{source}: invalid JSON: {exc}") from exc
    try:
        return validate_registry_document(document)
    except PluginRegistryValidationError as exc:
        raise PluginRegistryLoadError(f"{source}: {exc}") from exc


def load_registry_plugins(
    sources: Iterable[str] | None = None,
    *,
    include_default: bool = True,
    timeout: float = 10.0,
) -> tuple[list[dict[str, Any]], list[str]]:
    """Load plugins from one or more registry sources.

    Returns ``(plugins, errors)``. Each plugin dict includes ``_registry_url``.
    Duplicate plugin names are resolved last-source-wins so user taps can
    intentionally override the default registry metadata.
    """
    registry_sources = list(sources) if sources is not None else get_configured_registry_urls(include_default=include_default)
    by_name: dict[str, dict[str, Any]] = {}
    errors: list[str] = []
    for source in _dedupe_preserve_order(registry_sources):
        try:
            document = load_registry_document(source, timeout=timeout)
        except PluginRegistryLoadError as exc:
            errors.append(str(exc))
            continue
        for plugin in document["plugins"]:
            enriched = copy.deepcopy(plugin)
            enriched["_registry_url"] = source
            by_name[plugin["name"].lower()] = enriched
    return list(by_name.values()), errors


def find_registry_plugin(
    name: str,
    sources: Iterable[str] | None = None,
    *,
    include_default: bool = True,
) -> tuple[dict[str, Any] | None, list[str]]:
    """Find a plugin registry entry by name (case-insensitive)."""
    needle = name.strip().lower()
    plugins, errors = load_registry_plugins(sources, include_default=include_default)
    for plugin in plugins:
        if plugin["name"].lower() == needle:
            return plugin, errors
    return None, errors


def _sort_registry_plugin(plugin: Mapping[str, Any]) -> tuple[int, str]:
    tier = str(plugin.get("tier", "community"))
    return (_TIER_SORT_ORDER.get(tier, len(PLUGIN_TIERS)), plugin["name"])


def search_registry_plugins(
    query: str = "",
    sources: Iterable[str] | None = None,
    *,
    include_default: bool = True,
) -> tuple[list[dict[str, Any]], list[str]]:
    """Return registry plugins matching *query* in name, tags, or description."""
    plugins, errors = load_registry_plugins(sources, include_default=include_default)
    query = query.strip().lower()
    if not query:
        return sorted(plugins, key=_sort_registry_plugin), errors
    words = [part for part in query.split() if part]
    matches = []
    for plugin in plugins:
        haystack = " ".join(
            [
                plugin.get("name", ""),
                plugin.get("description", ""),
                plugin.get("maintainer", ""),
                " ".join(plugin.get("tags") or []),
                plugin.get("tier", ""),
            ]
        ).lower()
        if all(word in haystack for word in words):
            matches.append(plugin)
    return sorted(matches, key=_sort_registry_plugin), errors


def _read_registry_source(source: str, *, timeout: float) -> str:
    source = _normalize_registry_source(source)
    parsed = urllib.parse.urlparse(source)
    if parsed.scheme in {"https", "http"}:
        with urllib.request.urlopen(source, timeout=timeout) as response:  # noqa: S310 - user-configured tap URL
            return response.read().decode("utf-8")
    if parsed.scheme == "file":
        path = Path(urllib.request.url2pathname(parsed.path)).expanduser()
        return path.read_text(encoding="utf-8")
    if parsed.scheme:
        raise PluginRegistryLoadError(f"{source}: unsupported URL scheme '{parsed.scheme}'")
    return Path(source).expanduser().read_text(encoding="utf-8")


def _normalize_registry_source(source: str) -> str:
    text = str(source).strip()
    if not text:
        raise PluginRegistryLoadError("empty registry URL/path")
    return text


def _dedupe_preserve_order(values: Iterable[str]) -> list[str]:
    seen: set[str] = set()
    out: list[str] = []
    for value in values:
        if value not in seen:
            seen.add(value)
            out.append(value)
    return out
