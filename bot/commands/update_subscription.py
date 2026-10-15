# -*- coding: utf-8 -*-
"""
===================================
更新公告订阅命令
===================================

在 Discord 频道中订阅 / 取消订阅机器人更新公告。每次部署带有新公告时，
服务启动后会向已订阅频道各推送一次。
"""

from typing import List, Optional

from bot.commands.base import BotCommand
from bot.models import BotMessage, BotResponse

# Discord permission bits: ADMINISTRATOR, MANAGE_CHANNELS, MANAGE_GUILD
_MANAGE_PERMISSION_BITS = (1 << 3) | (1 << 4) | (1 << 5)


def _discord_channel_or_error(message: BotMessage) -> tuple:
    """Return (channel_id, guild_id, error_text)."""
    if message.platform != "discord":
        return None, None, "更新公告订阅目前只支持 Discord 频道。"
    guild_id = str(message.raw_data.get("guild_id") or "")
    channel_id = str(message.raw_data.get("channel_id") or "")
    if not guild_id or not channel_id:
        return None, None, "请在服务器频道内使用该命令，私信不支持订阅。"
    return channel_id, guild_id, None


def _can_manage(message: BotMessage) -> bool:
    """Channel managers, server managers and BOT_ADMIN_USERS may change subscriptions."""
    from src.config import get_config

    if message.user_id in set(getattr(get_config(), "bot_admin_users", []) or []):
        return True
    member = message.raw_data.get("member") or {}
    try:
        permissions = int(member.get("permissions") or 0)
    except (TypeError, ValueError):
        return False
    return bool(permissions & _MANAGE_PERMISSION_BITS)


class SubscribeUpdatesCommand(BotCommand):
    """订阅更新公告到当前频道。"""

    @property
    def name(self) -> str:
        return "subscribe_updates"

    @property
    def aliases(self) -> List[str]:
        return ["订阅更新公告"]

    @property
    def description(self) -> str:
        return "在当前频道订阅机器人更新公告"

    @property
    def usage(self) -> str:
        return "/订阅更新公告"

    def execute(self, message: BotMessage, args: List[str]) -> BotResponse:
        channel_id, guild_id, error = _discord_channel_or_error(message)
        if error:
            return BotResponse.error_response(error)
        if not _can_manage(message):
            return BotResponse.error_response("需要「管理频道」或「管理服务器」权限才能订阅更新公告。")

        from src.repositories.bot_update_repo import BotUpdateRepository
        from src.services.bot_update_announcement_service import (
            DISCORD_PLATFORM,
            mark_latest_seen,
        )

        repo = BotUpdateRepository()
        created = repo.add_subscription(
            DISCORD_PLATFORM, channel_id, guild_id=guild_id, subscribed_by=message.user_id
        )
        if not created:
            return BotResponse.text_response("本频道已订阅更新公告。")
        current: Optional[int] = mark_latest_seen(channel_id, repo=repo)
        suffix = f"（当前版本为公告 #{current}，从下一次更新开始推送）" if current else ""
        return BotResponse.text_response(f"✅ 已订阅更新公告，之后每次部署更新会在本频道公告一次{suffix}。")


class UnsubscribeUpdatesCommand(BotCommand):
    """取消当前频道的更新公告订阅。"""

    @property
    def name(self) -> str:
        return "unsubscribe_updates"

    @property
    def aliases(self) -> List[str]:
        return ["取消订阅更新公告"]

    @property
    def description(self) -> str:
        return "取消当前频道的机器人更新公告订阅"

    @property
    def usage(self) -> str:
        return "/取消订阅更新公告"

    def execute(self, message: BotMessage, args: List[str]) -> BotResponse:
        channel_id, _guild_id, error = _discord_channel_or_error(message)
        if error:
            return BotResponse.error_response(error)
        if not _can_manage(message):
            return BotResponse.error_response("需要「管理频道」或「管理服务器」权限才能取消订阅。")

        from src.repositories.bot_update_repo import BotUpdateRepository
        from src.services.bot_update_announcement_service import DISCORD_PLATFORM

        if BotUpdateRepository().remove_subscription(DISCORD_PLATFORM, channel_id):
            return BotResponse.text_response("已取消本频道的更新公告订阅。")
        return BotResponse.text_response("本频道没有订阅更新公告。")
