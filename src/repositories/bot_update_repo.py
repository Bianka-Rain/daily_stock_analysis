# -*- coding: utf-8 -*-
"""Bot update-announcement repository.

Subscriptions (which channels receive update announcements) and the
per-(announcement, channel) delivery ledger that keeps each announcement
from being posted twice.
"""

from __future__ import annotations

from datetime import datetime
from typing import List, Optional

from sqlalchemy import delete, select
from sqlalchemy.exc import IntegrityError

from src.storage import (
    BotUpdateDeliveryRecord,
    BotUpdateSubscriptionRecord,
    DatabaseManager,
)


class BotUpdateRepository:
    """DB access layer for update-announcement subscriptions and deliveries."""

    def __init__(self, db_manager: Optional[DatabaseManager] = None):
        self.db = db_manager or DatabaseManager.get_instance()

    def add_subscription(
        self,
        platform: str,
        channel_id: str,
        *,
        guild_id: Optional[str] = None,
        subscribed_by: Optional[str] = None,
    ) -> bool:
        """Subscribe a channel. Returns False if it was already subscribed."""
        with self.db.get_session() as session:
            session.add(
                BotUpdateSubscriptionRecord(
                    platform=platform,
                    channel_id=channel_id,
                    guild_id=guild_id or None,
                    subscribed_by=subscribed_by or None,
                )
            )
            try:
                session.commit()
            except IntegrityError:
                session.rollback()
                return False
            return True

    def remove_subscription(self, platform: str, channel_id: str) -> bool:
        """Unsubscribe a channel. Returns False if it was not subscribed."""
        with self.db.get_session() as session:
            result = session.execute(
                delete(BotUpdateSubscriptionRecord).where(
                    BotUpdateSubscriptionRecord.platform == platform,
                    BotUpdateSubscriptionRecord.channel_id == channel_id,
                )
            )
            session.commit()
            return bool(result.rowcount)

    def list_subscribed_channels(self, platform: str) -> List[str]:
        with self.db.get_session() as session:
            rows = session.execute(
                select(BotUpdateSubscriptionRecord.channel_id)
                .where(BotUpdateSubscriptionRecord.platform == platform)
                .order_by(BotUpdateSubscriptionRecord.id)
            ).scalars()
            return list(rows)

    def claim_delivery(
        self,
        announcement_id: str,
        platform: str,
        channel_id: str,
        *,
        status: str = "sending",
    ) -> bool:
        """Atomically record a delivery attempt.

        Returns False when a row for this (announcement, channel) already
        exists, i.e. it was sent, skipped or attempted before.
        """
        with self.db.get_session() as session:
            session.add(
                BotUpdateDeliveryRecord(
                    announcement_id=announcement_id,
                    platform=platform,
                    channel_id=channel_id,
                    status=status,
                )
            )
            try:
                session.commit()
            except IntegrityError:
                session.rollback()
                return False
            return True

    def set_delivery_status(
        self,
        announcement_id: str,
        platform: str,
        channel_id: str,
        status: str,
        detail: Optional[str] = None,
    ) -> None:
        with self.db.get_session() as session:
            row = session.execute(
                select(BotUpdateDeliveryRecord).where(
                    BotUpdateDeliveryRecord.announcement_id == announcement_id,
                    BotUpdateDeliveryRecord.platform == platform,
                    BotUpdateDeliveryRecord.channel_id == channel_id,
                ).limit(1)
            ).scalar_one_or_none()
            if row is None:
                return
            row.status = status
            row.detail = detail
            row.updated_at = datetime.now()
            session.commit()

    def get_delivery_status(
        self, announcement_id: str, platform: str, channel_id: str
    ) -> Optional[str]:
        with self.db.get_session() as session:
            return session.execute(
                select(BotUpdateDeliveryRecord.status).where(
                    BotUpdateDeliveryRecord.announcement_id == announcement_id,
                    BotUpdateDeliveryRecord.platform == platform,
                    BotUpdateDeliveryRecord.channel_id == channel_id,
                ).limit(1)
            ).scalar_one_or_none()
