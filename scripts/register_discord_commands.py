#!/usr/bin/env python3
"""Bulk-register the bot's Discord application commands."""

from __future__ import annotations

import argparse
import getpass
import json
import os
import sys
from pathlib import Path
from typing import Sequence
from urllib import error as urllib_error
from urllib import request as urllib_request

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from bot.discord_commands import COMMAND_PAYLOADS, DISCORD_API_BASE  # noqa: E402


def _parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(
        description="Register Daily Stock Analysis slash commands with Discord."
    )
    parser.add_argument("--application-id", required=True, help="Discord application ID")
    scope = parser.add_mutually_exclusive_group(required=True)
    scope.add_argument("--guild-id", help="Register commands in one Discord guild")
    scope.add_argument(
        "--global",
        dest="global_scope",
        action="store_true",
        help="Register commands globally",
    )
    scope.add_argument(
        "--clear-guild-commands",
        action="store_true",
        help=(
            "Remove guild-scoped copies of the commands in every guild the bot "
            "is in (keeps global commands); fixes duplicated slash commands"
        ),
    )
    parser.add_argument(
        "--dry-run",
        action="store_true",
        help="Print the JSON command payload without contacting Discord",
    )
    return parser


def _endpoint(application_id: str, guild_id: str | None) -> str:
    base = f"{DISCORD_API_BASE}/applications/{application_id}"
    if guild_id:
        return f"{base}/guilds/{guild_id}/commands"
    return f"{base}/commands"


def _load_bot_token() -> str:
    """Read the token without placing it in argv or echoing it."""
    token = os.environ.get("DISCORD_BOT_TOKEN", "").strip()
    if token:
        return token
    if sys.stdin.isatty():
        try:
            return getpass.getpass("Discord bot token: ").strip()
        except (EOFError, KeyboardInterrupt):
            return ""
    return ""


def _discord_request(method: str, url: str, bot_token: str, payload=None):
    data = None
    if payload is not None:
        data = json.dumps(payload, ensure_ascii=False).encode("utf-8")
    request = urllib_request.Request(
        url,
        data=data,
        headers={
            "Authorization": f"Bot {bot_token}",
            "Content-Type": "application/json",
            "User-Agent": "daily-stock-analysis-discord-command-register/1.0",
        },
        method=method,
    )
    response = urllib_request.urlopen(request, timeout=20)
    try:
        return json.loads(response.read().decode("utf-8") or "null")
    finally:
        response.close()


def _clear_guild_commands(application_id: str, bot_token: str) -> int:
    try:
        guilds = _discord_request("GET", f"{DISCORD_API_BASE}/users/@me/guilds", bot_token)
    except (urllib_error.HTTPError, urllib_error.URLError, TimeoutError, ValueError) as exc:
        status = getattr(exc, "code", None)
        detail = f" (HTTP {status})" if status is not None else ""
        print(f"Listing bot guilds failed{detail}", file=sys.stderr)
        return 1

    failed = 0
    for guild in guilds or []:
        guild_id = str(guild.get("id") or "")
        if not guild_id:
            continue
        try:
            _discord_request("PUT", _endpoint(application_id, guild_id), bot_token, [])
            print(f"Cleared guild commands in {guild_id}.")
        except (urllib_error.HTTPError, urllib_error.URLError, TimeoutError, ValueError) as exc:
            status = getattr(exc, "code", None)
            detail = f" (HTTP {status})" if status is not None else ""
            print(f"Clearing guild {guild_id} failed{detail}", file=sys.stderr)
            failed += 1
    return 1 if failed else 0


def main(argv: Sequence[str] | None = None) -> int:
    raw_argv = list(sys.argv[1:] if argv is None else argv)
    if any(
        argument == "--bot-token" or argument.startswith("--bot-token=")
        for argument in raw_argv
    ):
        print(
            "error: command-line token input is rejected; use the "
            "DISCORD_BOT_TOKEN environment variable or the secure prompt",
            file=sys.stderr,
        )
        return 2

    args = _parser().parse_args(raw_argv)

    if args.dry_run:
        print(json.dumps([] if args.clear_guild_commands else COMMAND_PAYLOADS, ensure_ascii=False, indent=2))
        return 0

    bot_token = _load_bot_token()
    if not bot_token:
        print(
            "error: set DISCORD_BOT_TOKEN or run interactively to enter it securely",
            file=sys.stderr,
        )
        return 2

    if args.clear_guild_commands:
        return _clear_guild_commands(args.application_id, bot_token)

    endpoint = _endpoint(args.application_id, args.guild_id)
    request = urllib_request.Request(
        endpoint,
        data=json.dumps(COMMAND_PAYLOADS, ensure_ascii=False).encode("utf-8"),
        headers={
            "Authorization": f"Bot {bot_token}",
            "Content-Type": "application/json",
            "User-Agent": "daily-stock-analysis-discord-command-register/1.0",
        },
        method="PUT",
    )
    try:
        response = urllib_request.urlopen(request, timeout=20)
        response_body = response.read()
        response.close()
    except (urllib_error.HTTPError, urllib_error.URLError, TimeoutError) as exc:
        status = getattr(exc, "code", None)
        detail = f" (HTTP {status})" if status is not None else ""
        print(f"Discord command registration failed{detail}", file=sys.stderr)
        return 1

    try:
        registered_count = len(json.loads(response_body.decode("utf-8")))
    except (AttributeError, TypeError, UnicodeDecodeError, ValueError):
        registered_count = len(COMMAND_PAYLOADS)
    scope_name = f"guild {args.guild_id}" if args.guild_id else "global"
    print(f"Registered {registered_count} Discord commands ({scope_name}).")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
