# -*- coding: utf-8 -*-
"""Discord does not render pipe tables; reports are converted before sending."""

from types import SimpleNamespace
from unittest.mock import patch

from src.formatters import format_discord_markdown
from src.notification_sender.discord_sender import DiscordSender


def test_single_row_table_becomes_one_line_per_column():
    out = format_discord_markdown(
        "### 🎯 操作点位\n| 理想买入点 | 止损位 | 目标位 |\n|---|---|---|\n| 770 | 764.4 | 778 |"
    )
    assert out == "### 🎯 操作点位\n- **理想买入点**：770\n- **止损位**：764.4\n- **目标位**：778"


def test_two_column_table_becomes_key_value_lines():
    out = format_discord_markdown("| 价格指标 | 当前价 |\n|---|---|\n| MA5 | 774.82 |\n| **支撑位** | 764.44 |")
    assert out == "- **MA5**：774.82\n- **支撑位**：764.44"


def test_multi_row_table_keeps_one_line_per_row_and_drops_na():
    out = format_discord_markdown(
        "| 指数 | 最新 | 涨跌幅 | 成交额 |\n|---|---|---|---|\n"
        "| 标普500 | 7724.63 | +0.07% | N/A |\n| 纳指 | 26585.50 | -0.40% | N/A |"
    )
    assert out == "- **标普500**：最新 7724.63 · 涨跌幅 +0.07%\n- **纳指**：最新 26585.50 · 涨跌幅 -0.40%"


def test_horizontal_rule_and_code_blocks():
    out = format_discord_markdown("a\n---\n```\n| keep | me |\n```")
    assert out == "a\n────────\n```\n| keep | me |\n```"


def test_discord_sender_sends_converted_tables():
    config = SimpleNamespace(
        discord_bot_token=None,
        discord_main_channel_id=None,
        discord_webhook_url="https://discord.example/webhook",
    )
    sender = DiscordSender(config)
    sent = []
    with patch.object(sender, "_send_discord_webhook", side_effect=lambda chunk, **_: sent.append(chunk) or True):
        assert sender.send_to_discord("| 止损位 | 目标位 |\n|---|---|\n| 764 | 778 |")
    assert sent == ["- **止损位**：764\n- **目标位**：778"]
