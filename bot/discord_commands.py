# -*- coding: utf-8 -*-
"""Discord slash-command definitions and startup sync.

Single source for the command list used by ``scripts/register_discord_commands.py``
and by the server, which (with ``DISCORD_COMMAND_SYNC_ENABLED=true``) re-registers
the global commands on startup with its own ``DISCORD_BOT_TOKEN`` and removes
guild-scoped copies so each command shows up once.
"""

from __future__ import annotations

import logging
from typing import Dict

import requests

logger = logging.getLogger(__name__)

DISCORD_API_BASE = "https://discord.com/api/v10"


def _option(name: str, description: str, *, required: bool = False, kind: int = 3):
    return {
        "type": kind,
        "name": name,
        "description": description,
        "required": required,
    }


COMMAND_PAYLOADS = [
    {
        "name": "help",
        "description": "显示帮助信息",
        "options": [_option("command", "要查看的命令名")],
    },
    {"name": "status", "description": "显示系统状态"},
    {
        "name": "analyze",
        "description": "分析指定股票",
        "options": [
            _option("stock_code", "股票代码", required=True),
            _option("full", "生成完整分析", kind=5),
        ],
    },
    {"name": "market", "description": "执行大盘复盘分析"},
    {
        "name": "batch",
        "description": "批量分析自选股",
        "options": [_option("count", "最多分析的股票数量", kind=4)],
    },
    {
        "name": "ask",
        "description": "使用 Agent 技能分析股票",
        "options": [
            _option("stock_codes", "股票代码，多个代码用逗号分隔", required=True),
            _option("strategy", "可选的技能或策略名称"),
        ],
    },
    {
        "name": "chat",
        "description": "与 AI 助手自由对话",
        "options": [_option("question", "要询问的问题", required=True)],
    },
    {
        "name": "research",
        "description": "深度研究股票或市场主题",
        "options": [
            _option("topic", "股票代码或研究主题", required=True),
            _option("question", "可选的具体问题"),
        ],
    },
    {
        "name": "strategies",
        "description": "查看可用交易策略",
        "options": [_option("active", "仅显示已激活策略", kind=5)],
    },
    {
        "name": "history",
        "description": "查看 Agent 对话历史",
        "options": [_option("session", "会话 ID，或输入 clear 清空")],
    },
    {"name": "订阅更新公告", "description": "在当前频道订阅机器人更新公告"},
    {"name": "取消订阅更新公告", "description": "取消当前频道的机器人更新公告订阅"},
]


def sync_discord_commands(bot_token: str, *, timeout: float = 20) -> Dict[str, int]:
    """Overwrite global commands with COMMAND_PAYLOADS and clear guild-scoped copies."""
    headers = {
        "Authorization": f"Bot {bot_token}",
        "Content-Type": "application/json",
        "User-Agent": "daily-stock-analysis-discord-command-sync/1.0",
    }
    summary = {"global": 0, "guilds_cleared": 0, "guilds_failed": 0}

    app = requests.get(f"{DISCORD_API_BASE}/oauth2/applications/@me", headers=headers, timeout=timeout)
    app.raise_for_status()
    application_id = str(app.json()["id"])

    registered = requests.put(
        f"{DISCORD_API_BASE}/applications/{application_id}/commands",
        json=COMMAND_PAYLOADS,
        headers=headers,
        timeout=timeout,
    )
    registered.raise_for_status()
    summary["global"] = len(registered.json())

    guilds = requests.get(f"{DISCORD_API_BASE}/users/@me/guilds", headers=headers, timeout=timeout)
    guilds.raise_for_status()
    for guild in guilds.json():
        guild_id = str(guild.get("id") or "")
        if not guild_id:
            continue
        cleared = requests.put(
            f"{DISCORD_API_BASE}/applications/{application_id}/guilds/{guild_id}/commands",
            json=[],
            headers=headers,
            timeout=timeout,
        )
        if cleared.status_code < 300:
            summary["guilds_cleared"] += 1
        else:
            summary["guilds_failed"] += 1
            logger.warning("[Discord] 清理服务器 %s 的命令副本失败: HTTP %s", guild_id, cleared.status_code)
    return summary
