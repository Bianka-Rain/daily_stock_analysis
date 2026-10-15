# -*- coding: utf-8 -*-
"""Bot update announcements.

Announcements live in ``bot/announcements/NNNN.md`` (one file per deploy that
ships user-visible changes). Each file has a small front matter block and a
body that follows the fixed section template::

    ---
    id: 2
    date: 2026-10-16
    base: <full sha of the previous announcement's head>
    head: <full sha of the last commit this announcement covers>
    ---
    ## 新增
    - **主题**：一句话说明，命令写成 `/analyze`
    ## 修复
    - **主题**：...

On server startup the newest announcement is posted once to every subscribed
Discord channel. Each (announcement, channel) pair is claimed in the
``bot_update_deliveries`` table before sending, so restarts never re-post.
"""

from __future__ import annotations

import logging
import re
from dataclasses import dataclass, field
from pathlib import Path
from typing import Dict, List, Optional, Tuple

logger = logging.getLogger(__name__)

ANNOUNCEMENTS_DIR = Path(__file__).resolve().parents[2] / "bot" / "announcements"
DISCORD_PLATFORM = "discord"
EMBED_DESCRIPTION_LIMIT = 4096
EMBED_COLOR = 0x9B8CFF
UNSUBSCRIBE_HINT = "不想收了：/取消订阅更新公告"

# Canonical section order and the heading rendered in Discord.
SECTION_TITLES: Dict[str, str] = {
    "新增": "✨ **新增**",
    "改进": "🔧 **改进**",
    "修复": "🐛 **修复**",
    "配置变更": "⚙️ **配置变更**",
    "注意事项": "⚠️ **注意事项**",
}
_FILENAME_RE = re.compile(r"^(\d{4})\.md$")
_SHA_RE = re.compile(r"^[0-9a-f]{40}$")
_DATE_RE = re.compile(r"^\d{4}-\d{2}-\d{2}$")
_ITEM_RE = re.compile(r"^\*\*[^*\n]{1,16}\*\*：\S.*$")
_PLACEHOLDER_RE = re.compile(r"TODO|TBD|待补充|待定|XXX|\.\.\.$|…$", re.IGNORECASE)


class AnnouncementError(ValueError):
    """Raised when an announcement file does not follow the template."""


@dataclass
class Announcement:
    id: int
    date: str
    base: str
    head: str
    sections: List[Tuple[str, List[str]]] = field(default_factory=list)
    path: Optional[Path] = None

    @property
    def key(self) -> str:
        return f"{self.id:04d}"


def parse_announcement_text(text: str, *, path: Optional[Path] = None) -> Announcement:
    """Parse one announcement file and enforce the section template."""
    where = path.name if path else "<text>"
    lines = text.splitlines()
    if not lines or lines[0].strip() != "---":
        raise AnnouncementError(f"{where}: 缺少 front matter 起始行 ---")
    try:
        end = next(i for i in range(1, len(lines)) if lines[i].strip() == "---")
    except StopIteration as exc:
        raise AnnouncementError(f"{where}: front matter 未以 --- 结束") from exc

    meta: Dict[str, str] = {}
    for raw in lines[1:end]:
        if not raw.strip():
            continue
        key, sep, value = raw.partition(":")
        if not sep:
            raise AnnouncementError(f"{where}: front matter 行格式错误: {raw!r}")
        meta[key.strip()] = value.strip()
    missing = {"id", "date", "base", "head"} - meta.keys()
    if missing:
        raise AnnouncementError(f"{where}: front matter 缺少字段 {sorted(missing)}")
    if not meta["id"].isdigit() or int(meta["id"]) < 1:
        raise AnnouncementError(f"{where}: id 必须是正整数")
    if not _DATE_RE.match(meta["date"]):
        raise AnnouncementError(f"{where}: date 必须是 YYYY-MM-DD")
    for key in ("base", "head"):
        if not _SHA_RE.match(meta[key]):
            raise AnnouncementError(f"{where}: {key} 必须是 40 位完整 commit sha")

    sections: List[Tuple[str, List[str]]] = []
    for raw in lines[end + 1:]:
        line = raw.rstrip()
        if not line.strip():
            continue
        if line.startswith("## "):
            title = line[3:].strip()
            if title not in SECTION_TITLES:
                raise AnnouncementError(
                    f"{where}: 未知章节「{title}」，只允许 {list(SECTION_TITLES)}"
                )
            if any(title == existing for existing, _ in sections):
                raise AnnouncementError(f"{where}: 章节「{title}」重复")
            sections.append((title, []))
            continue
        if line.startswith("- "):
            if not sections:
                raise AnnouncementError(f"{where}: 条目必须写在章节标题之下")
            item = line[2:].strip()
            if not item or _PLACEHOLDER_RE.search(item):
                raise AnnouncementError(f"{where}: 条目为空或含占位符: {line!r}")
            if not _ITEM_RE.match(item):
                raise AnnouncementError(
                    f"{where}: 条目必须写成「- **主题**：说明」（全角冒号）: {line!r}"
                )
            if item in sections[-1][1]:
                raise AnnouncementError(f"{where}: 条目重复: {line!r}")
            sections[-1][1].append(item)
            continue
        raise AnnouncementError(f"{where}: 正文只允许 `## 章节` 和 `- 条目`，发现: {line!r}")

    if not sections:
        raise AnnouncementError(f"{where}: 至少需要一个章节")
    for title, items in sections:
        if not items:
            raise AnnouncementError(f"{where}: 章节「{title}」没有条目，空章节请直接删除")
    order = list(SECTION_TITLES)
    titles = [title for title, _ in sections]
    if titles != sorted(titles, key=order.index):
        raise AnnouncementError(f"{where}: 章节顺序必须是 {order}")

    announcement = Announcement(
        id=int(meta["id"]),
        date=meta["date"],
        base=meta["base"],
        head=meta["head"],
        sections=sections,
        path=path,
    )
    if len(render_announcement(announcement)["description"]) > EMBED_DESCRIPTION_LIMIT:
        raise AnnouncementError(f"{where}: 正文超过 Discord embed 上限 {EMBED_DESCRIPTION_LIMIT} 字符，请精简")
    return announcement


def load_announcements(directory: Path = ANNOUNCEMENTS_DIR) -> List[Announcement]:
    """Load and validate the full announcement chain, oldest first."""
    if not directory.is_dir():
        return []
    announcements: List[Announcement] = []
    for path in sorted(directory.iterdir()):
        if path.suffix != ".md":
            continue
        match = _FILENAME_RE.match(path.name)
        if not match:
            raise AnnouncementError(f"{path.name}: 文件名必须是四位编号，如 0001.md")
        announcement = parse_announcement_text(path.read_text(encoding="utf-8"), path=path)
        if announcement.id != int(match.group(1)):
            raise AnnouncementError(f"{path.name}: front matter id 与文件名编号不一致")
        announcements.append(announcement)

    for index, announcement in enumerate(announcements):
        if announcement.id != index + 1:
            raise AnnouncementError(
                f"{announcement.key}.md: 编号必须从 1 开始连续递增，期望 {index + 1}"
            )
        if index:
            previous = announcements[index - 1]
            if announcement.base != previous.head:
                raise AnnouncementError(
                    f"{announcement.key}.md: base 必须等于上一份公告 #{previous.id} 的 head，"
                    "保证覆盖范围首尾相接"
                )
            if announcement.date < previous.date:
                raise AnnouncementError(f"{announcement.key}.md: 日期早于上一份公告")
    return announcements


def render_announcement(announcement: Announcement) -> Dict[str, object]:
    """Render the Discord embed for one announcement."""
    lead = f"公告 #{announcement.id}"
    if announcement.id > 1:
        lead += f"（接续 #{announcement.id - 1}）"
    lines = [f"{lead}。更新内容如下——"]
    item_count = 0
    for title, items in announcement.sections:
        lines.append("")
        lines.append(SECTION_TITLES[title])
        lines.extend(f"- {item}" for item in items)
        item_count += len(items)
    return {
        "title": f"📈 Fairy 更新日志 · {announcement.date}",
        "description": "\n".join(lines),
        "color": EMBED_COLOR,
        "footer": {
            "text": (
                f"共 {item_count} 项改动 · {UNSUBSCRIBE_HINT} · "
                f"{announcement.base[:7]}..{announcement.head[:7]}"
            )
        },
    }


def latest_announcement(directory: Path = ANNOUNCEMENTS_DIR) -> Optional[Announcement]:
    announcements = load_announcements(directory)
    return announcements[-1] if announcements else None


def _get_repo(repo=None):
    if repo is not None:
        return repo
    from src.repositories.bot_update_repo import BotUpdateRepository

    return BotUpdateRepository()


def mark_latest_seen(channel_id: str, *, repo=None, directory: Path = ANNOUNCEMENTS_DIR) -> Optional[int]:
    """Record that a newly subscribed channel starts after the current announcement.

    Without this, the next restart would post an already-released announcement
    to the new channel, which is not a deploy.
    """
    try:
        announcement = latest_announcement(directory)
    except AnnouncementError as exc:
        logger.warning("[更新公告] 公告文件无效，跳过订阅基线记录: %s", exc)
        return None
    if announcement is None:
        return None
    _get_repo(repo).claim_delivery(
        announcement.key, DISCORD_PLATFORM, channel_id, status="skipped_on_subscribe"
    )
    return announcement.id


def announce_latest(config, *, repo=None, sender=None, directory: Path = ANNOUNCEMENTS_DIR) -> Dict[str, int]:
    """Post the newest announcement once to every subscribed channel.

    Delivery is at-most-once per (announcement, channel): the row is claimed
    before sending and never re-claimed, so a crash or failed send is logged
    rather than retried on the next restart.
    """
    summary = {"sent": 0, "failed": 0, "skipped": 0}
    if not getattr(config, "discord_bot_token", None):
        logger.info("[更新公告] 未配置 DISCORD_BOT_TOKEN，跳过")
        return summary
    try:
        announcement = latest_announcement(directory)
    except AnnouncementError as exc:
        logger.error("[更新公告] 公告文件无效，本次不发送: %s", exc)
        return summary
    if announcement is None:
        logger.info("[更新公告] 没有公告文件，跳过")
        return summary

    embed = render_announcement(announcement)
    repo = _get_repo(repo)
    if sender is None:
        from src.notification_sender.discord_sender import DiscordSender

        sender = DiscordSender(config)

    for channel_id in repo.list_subscribed_channels(DISCORD_PLATFORM):
        if not repo.claim_delivery(announcement.key, DISCORD_PLATFORM, channel_id):
            summary["skipped"] += 1
            continue
        try:
            ok = sender.send_to_channel(channel_id, embed=embed)
        except Exception as exc:  # noqa: BLE001 - one channel must not block the rest.
            logger.error("[更新公告] 发送到频道 %s 异常: %s", channel_id, exc)
            ok = False
        repo.set_delivery_status(
            announcement.key, DISCORD_PLATFORM, channel_id, "sent" if ok else "failed"
        )
        summary["sent" if ok else "failed"] += 1

    logger.info("[更新公告] #%s 发送完成: %s", announcement.id, summary)
    return summary
