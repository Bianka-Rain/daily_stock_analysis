# -*- coding: utf-8 -*-
"""Tests for /订阅更新公告 subscriptions and once-per-deploy update announcements."""

from types import SimpleNamespace
from unittest.mock import patch

import pytest

from bot.commands.update_subscription import SubscribeUpdatesCommand, UnsubscribeUpdatesCommand
from bot.models import BotMessage, ChatType
from src.repositories.bot_update_repo import BotUpdateRepository
from src.services.bot_update_announcement_service import (
    AnnouncementError,
    announce_latest,
    load_announcements,
    mark_latest_seen,
    parse_announcement_text,
    render_announcement,
)
from src.storage import DatabaseManager

SHA_A = "a" * 40
SHA_B = "b" * 40
SHA_C = "c" * 40


def _text(id_=1, base=SHA_A, head=SHA_B, date="2026-10-16", body=None):
    body = body or "## 新增\n- **更新公告**：频道里用 `/订阅更新公告` 订阅\n"
    return f"---\nid: {id_}\ndate: {date}\nbase: {base}\nhead: {head}\n---\n{body}"


@pytest.fixture()
def repo(tmp_path):
    DatabaseManager.reset_instance()
    db = DatabaseManager(db_url=f"sqlite:///{tmp_path / 'bot.db'}")
    yield BotUpdateRepository(db)
    DatabaseManager.reset_instance()


class FakeSender:
    def __init__(self, ok=True):
        self.ok = ok
        self.sent = []

    def send_to_channel(self, channel_id, content="", *, embed=None, timeout_seconds=None):
        self.sent.append((channel_id, embed))
        return self.ok


CONFIG = SimpleNamespace(discord_bot_token="token")


# --- template ---------------------------------------------------------------

def test_parse_valid_announcement():
    a = parse_announcement_text(
        _text(body="## 新增\n- **甲**：说明一\n## 修复\n- **乙**：说明二\n")
    )
    assert a.id == 1
    assert a.sections == [("新增", ["**甲**：说明一"]), ("修复", ["**乙**：说明二"])]


@pytest.mark.parametrize(
    "body, message",
    [
        ("## 新功能\n- **甲**：说明\n", "未知章节"),
        ("## 修复\n- **甲**：说明\n## 新增\n- **乙**：说明\n", "章节顺序"),
        ("## 新增\n", "没有条目"),
        ("## 新增\n- 没有主题的说明\n", "主题"),
        ("## 新增\n- **甲**:半角冒号\n", "主题"),
        ("## 新增\n- **甲**：TODO 待补充\n", "占位符"),
        ("## 新增\n- **甲**：说明\n- **甲**：说明\n", "重复"),
        ("随便一段话\n", "正文只允许"),
    ],
)
def test_parse_rejects_off_template(body, message):
    with pytest.raises(AnnouncementError, match=message):
        parse_announcement_text(_text(body=body))


def test_parse_rejects_short_sha():
    with pytest.raises(AnnouncementError, match="sha"):
        parse_announcement_text(_text(head="abc1234"))


def test_chain_requires_contiguous_ids_and_matching_base(tmp_path):
    (tmp_path / "0001.md").write_text(_text(1, SHA_A, SHA_B), encoding="utf-8")
    (tmp_path / "0002.md").write_text(_text(2, SHA_B, SHA_C), encoding="utf-8")
    assert [a.id for a in load_announcements(tmp_path)] == [1, 2]

    (tmp_path / "0002.md").write_text(_text(2, SHA_A, SHA_C), encoding="utf-8")
    with pytest.raises(AnnouncementError, match="base 必须等于上一份"):
        load_announcements(tmp_path)

    (tmp_path / "0002.md").unlink()
    (tmp_path / "0003.md").write_text(_text(3, SHA_B, SHA_C), encoding="utf-8")
    with pytest.raises(AnnouncementError, match="连续递增"):
        load_announcements(tmp_path)


def test_render_embed_follows_template():
    embed = render_announcement(
        parse_announcement_text(_text(2, body="## 新增\n- **甲**：一\n## 改进\n- **乙**：二\n- **丙**：三\n"))
    )
    assert embed["title"] == "📈 Fairy 更新日志 · 2026-10-16"
    assert embed["description"].startswith("公告 #2（接续 #1）。更新内容如下——")
    assert "✨ **新增**\n- **甲**：一" in embed["description"]
    assert embed["footer"]["text"] == "共 3 项改动 · 不想收了：/取消订阅更新公告 · aaaaaaa..bbbbbbb"


def test_repo_announcements_are_valid():
    load_announcements()


# --- delivery ---------------------------------------------------------------

def test_announce_once_per_channel_across_restarts(repo, tmp_path):
    (tmp_path / "0001.md").write_text(_text(), encoding="utf-8")
    repo.add_subscription("discord", "c1")
    repo.add_subscription("discord", "c2")
    sender = FakeSender()

    first = announce_latest(CONFIG, repo=repo, sender=sender, directory=tmp_path)
    second = announce_latest(CONFIG, repo=repo, sender=sender, directory=tmp_path)

    assert first == {"sent": 2, "failed": 0, "skipped": 0}
    assert second == {"sent": 0, "failed": 0, "skipped": 2}
    assert [channel for channel, _ in sender.sent] == ["c1", "c2"]
    assert repo.get_delivery_status("0001", "discord", "c1") == "sent"


def test_new_announcement_is_sent_after_previous_one(repo, tmp_path):
    (tmp_path / "0001.md").write_text(_text(1, SHA_A, SHA_B), encoding="utf-8")
    repo.add_subscription("discord", "c1")
    sender = FakeSender()
    announce_latest(CONFIG, repo=repo, sender=sender, directory=tmp_path)
    (tmp_path / "0002.md").write_text(_text(2, SHA_B, SHA_C), encoding="utf-8")
    announce_latest(CONFIG, repo=repo, sender=sender, directory=tmp_path)
    assert [embed["description"][:5] for _, embed in sender.sent] == ["公告 #1", "公告 #2"]


def test_new_subscriber_does_not_get_already_released_announcement(repo, tmp_path):
    (tmp_path / "0001.md").write_text(_text(), encoding="utf-8")
    repo.add_subscription("discord", "c1")
    assert mark_latest_seen("c1", repo=repo, directory=tmp_path) == 1
    sender = FakeSender()
    assert announce_latest(CONFIG, repo=repo, sender=sender, directory=tmp_path)["skipped"] == 1
    assert sender.sent == []


def test_failed_send_is_not_retried(repo, tmp_path):
    (tmp_path / "0001.md").write_text(_text(), encoding="utf-8")
    repo.add_subscription("discord", "c1")
    assert announce_latest(CONFIG, repo=repo, sender=FakeSender(ok=False), directory=tmp_path)["failed"] == 1
    assert repo.get_delivery_status("0001", "discord", "c1") == "failed"
    retry = FakeSender()
    announce_latest(CONFIG, repo=repo, sender=retry, directory=tmp_path)
    assert retry.sent == []


def test_invalid_announcement_sends_nothing(repo, tmp_path):
    (tmp_path / "0001.md").write_text(_text(body="## 新增\n- 不合模板\n"), encoding="utf-8")
    repo.add_subscription("discord", "c1")
    sender = FakeSender()
    assert announce_latest(CONFIG, repo=repo, sender=sender, directory=tmp_path) == {
        "sent": 0, "failed": 0, "skipped": 0,
    }
    assert sender.sent == []


def test_no_bot_token_sends_nothing(repo, tmp_path):
    (tmp_path / "0001.md").write_text(_text(), encoding="utf-8")
    repo.add_subscription("discord", "c1")
    sender = FakeSender()
    announce_latest(SimpleNamespace(discord_bot_token=None), repo=repo, sender=sender, directory=tmp_path)
    assert sender.sent == []


# --- commands ---------------------------------------------------------------

def _message(permissions="0", guild_id="g1", platform="discord"):
    raw = {"type": 2, "channel_id": "c1", "member": {"permissions": permissions}}
    if guild_id:
        raw["guild_id"] = guild_id
    return BotMessage(
        platform=platform, message_id="m", user_id="u1", user_name="u", chat_id="c1",
        chat_type=ChatType.GROUP, content="/订阅更新公告", raw_data=raw,
    )


@pytest.fixture()
def command_env(repo):
    with patch("src.config.get_config", return_value=SimpleNamespace(bot_admin_users=[])), \
         patch("src.repositories.bot_update_repo.BotUpdateRepository", return_value=repo), \
         patch("src.services.bot_update_announcement_service.latest_announcement", return_value=None):
        yield repo


def test_subscribe_requires_manage_permission(command_env):
    response = SubscribeUpdatesCommand().execute(_message(permissions="0"), [])
    assert "权限" in response.text
    assert command_env.list_subscribed_channels("discord") == []


def test_subscribe_and_unsubscribe_with_manage_channels(command_env):
    manage_channels = str(1 << 4)
    assert "已订阅" in SubscribeUpdatesCommand().execute(_message(manage_channels), []).text
    assert "已订阅" in SubscribeUpdatesCommand().execute(_message(manage_channels), []).text
    assert command_env.list_subscribed_channels("discord") == ["c1"]
    assert "已取消" in UnsubscribeUpdatesCommand().execute(_message(manage_channels), []).text
    assert command_env.list_subscribed_channels("discord") == []


def test_subscribe_rejects_dm_and_other_platforms(command_env):
    assert "私信" in SubscribeUpdatesCommand().execute(_message(str(1 << 3), guild_id=None), []).text
    assert "只支持 Discord" in SubscribeUpdatesCommand().execute(_message(str(1 << 3), platform="feishu"), []).text


def test_chinese_slash_name_routes_to_command():
    from bot.dispatcher import CommandDispatcher

    dispatcher = CommandDispatcher()
    dispatcher.register_class(SubscribeUpdatesCommand)
    dispatcher.register_class(UnsubscribeUpdatesCommand)
    assert isinstance(dispatcher.get_command("订阅更新公告"), SubscribeUpdatesCommand)
    assert isinstance(dispatcher.get_command("取消订阅更新公告"), UnsubscribeUpdatesCommand)
