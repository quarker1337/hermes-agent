"""Bundled Slack platform plugin.

This is the reference first-party extra plugin: it wraps the existing Slack
adapter and helper CLI so the Slack integration is discoverable through the
plugin manager while preserving the current runtime implementation.
"""
from __future__ import annotations

import os
from typing import Any, Optional


def _validate_slack_config(config: Any) -> bool:
    """Return True when Slack has the tokens required for Socket Mode."""
    bot_token = getattr(config, "token", None) or os.getenv("SLACK_BOT_TOKEN")
    extra = getattr(config, "extra", {}) or {}
    app_token = extra.get("app_token") or os.getenv("SLACK_APP_TOKEN")
    return bool(bot_token and app_token)


def _is_slack_connected(config: Any) -> bool:
    """Status helper used by gateway setup/status surfaces."""
    try:
        from gateway.platforms.slack import check_slack_requirements
    except Exception:
        return False
    return bool(check_slack_requirements() and _validate_slack_config(config))


async def _standalone_send(
    config: Any,
    chat_id: str,
    message: str,
    *,
    thread_id: Optional[str] = None,
    media_files=None,
    force_document: bool = False,
) -> dict:
    """Send Slack messages when cron/tools run outside the gateway process."""
    if media_files:
        return {
            "error": "Slack standalone send currently supports text-only messages; MEDIA attachments were not sent."
        }
    try:
        from tools.send_message_tool import _send_slack
    except Exception as exc:
        return {"error": f"Slack standalone sender unavailable: {exc}"}

    token = getattr(config, "token", None) or os.getenv("SLACK_BOT_TOKEN")
    if not token:
        return {"error": "SLACK_BOT_TOKEN is not configured"}
    if thread_id:
        message = f"{message}\n\n(thread: {thread_id})"
    return await _send_slack(token, chat_id, message)


def _setup_slack() -> None:
    """Run the existing Slack interactive setup lazily."""
    from hermes_cli.setup import _setup_slack as setup_slack

    setup_slack()


def register(ctx) -> None:
    """Plugin entry point called by the Hermes plugin manager."""
    from gateway.platforms.slack import SlackAdapter, check_slack_requirements
    from hermes_cli.slack_cli import setup_slack_cli_parser, slack_command

    ctx.register_platform(
        name="slack",
        label="Slack",
        adapter_factory=lambda cfg: SlackAdapter(cfg),
        check_fn=check_slack_requirements,
        validate_config=_validate_slack_config,
        is_connected=_is_slack_connected,
        required_env=["SLACK_BOT_TOKEN", "SLACK_APP_TOKEN"],
        install_hint="pip install 'hermes-agent[slack]'",
        setup_fn=_setup_slack,
        cron_deliver_env_var="SLACK_HOME_CHANNEL",
        standalone_sender_fn=_standalone_send,
        allowed_users_env="SLACK_ALLOWED_USERS",
        allow_all_env="SLACK_ALLOW_ALL_USERS",
        max_message_length=SlackAdapter.MAX_MESSAGE_LENGTH,
        emoji="💼",
        pii_safe=False,
        allow_update_command=True,
        platform_hint=(
            "You are chatting via Slack. Use concise Slack-friendly Markdown; "
            "prefer short threaded replies when responding in channels."
        ),
    )
    ctx.register_cli_command(
        name="slack",
        help="Slack integration helpers",
        description="Slack integration helpers for Hermes.",
        setup_fn=setup_slack_cli_parser,
        handler_fn=slack_command,
    )
