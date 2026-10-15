# -*- coding: utf-8 -*-
"""Startup sync of Discord slash commands (DISCORD_COMMAND_SYNC_ENABLED)."""

from unittest.mock import Mock, patch

import pytest

from bot.discord_commands import COMMAND_PAYLOADS, sync_discord_commands


def _response(payload, status=200):
    response = Mock(status_code=status)
    response.json.return_value = payload
    response.raise_for_status = Mock()
    return response


def test_sync_registers_global_commands_and_clears_guild_copies():
    calls = []

    def fake_get(url, headers, timeout):
        calls.append(("GET", url, None))
        if url.endswith("/oauth2/applications/@me"):
            return _response({"id": "app-1"})
        return _response([{"id": "g1"}, {"id": "g2"}])

    def fake_put(url, json, headers, timeout):
        calls.append(("PUT", url, json))
        assert headers["Authorization"] == "Bot token-x"
        if url.endswith("/guilds/g2/commands"):
            return _response([], status=403)
        return _response(json)

    with patch("bot.discord_commands.requests.get", side_effect=fake_get), \
         patch("bot.discord_commands.requests.put", side_effect=fake_put):
        summary = sync_discord_commands("token-x")

    assert summary == {"global": len(COMMAND_PAYLOADS), "guilds_cleared": 1, "guilds_failed": 1}
    puts = [(url, body) for method, url, body in calls if method == "PUT"]
    assert puts[0] == ("https://discord.com/api/v10/applications/app-1/commands", COMMAND_PAYLOADS)
    assert [url.rsplit("/guilds/", 1)[1] for url, _ in puts[1:]] == ["g1/commands", "g2/commands"]
    assert all(body == [] for _, body in puts[1:])


def test_sync_stops_before_writing_when_application_lookup_fails():
    failing = _response({}, status=401)
    failing.raise_for_status.side_effect = RuntimeError("401")
    with patch("bot.discord_commands.requests.get", return_value=failing), \
         patch("bot.discord_commands.requests.put") as put:
        with pytest.raises(RuntimeError):
            sync_discord_commands("bad-token")
    put.assert_not_called()


def test_command_payloads_include_update_subscription_commands():
    names = {command["name"] for command in COMMAND_PAYLOADS}
    assert {"analyze", "订阅更新公告", "取消订阅更新公告"} <= names
    assert len(names) == len(COMMAND_PAYLOADS)
