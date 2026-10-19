"""
User Profile Management Service.

Provides user account registration, profile updates, language settings, ban verification,
and usage statistics aggregation.
"""

import logging
from typing import Any, Dict, Optional, Tuple
from telegram import User as TelegramUser

from productivity_hub.config.settings import Settings, get_settings
from productivity_hub.database.database import get_db
from productivity_hub.database.models import User, BannedUser

logger = logging.getLogger("productivity_hub.services.user")


class UserService:
    """
    High-level service managing user profiles, permissions, and database operations.
    """

    def __init__(self, settings: Optional[Settings] = None):
        self.settings = settings or get_settings()

    async def get_or_create_user(self, tg_user: TelegramUser) -> User:
        """
        Fetch existing user profile or auto-register a new Telegram user in SQLite.

        Args:
            tg_user: python-telegram-bot User object.

        Returns:
            User: Database User model instance.
        """
        db = get_db()
        existing = await db.get_user(tg_user.id)

        is_owner = (tg_user.id == self.settings.OWNER_ID)
        role = "owner" if is_owner else ("admin" if existing and existing.is_admin else "user")

        if existing:
            # Update name or username if changed
            if (
                existing.username != tg_user.username
                or existing.first_name != tg_user.first_name
                or existing.last_name != tg_user.last_name
            ):
                existing.username = tg_user.username
                existing.first_name = tg_user.first_name
                existing.last_name = tg_user.last_name
                await db.upsert_user(existing)
            return existing

        # Create new user record
        new_user = User(
            user_id=tg_user.id,
            username=tg_user.username,
            first_name=tg_user.first_name,
            last_name=tg_user.last_name,
            is_banned=False,
            is_admin=is_owner,
            role=role,
            language="en"
        )
        await db.upsert_user(new_user)
        logger.info(f"Registered new user profile: {tg_user.id} (@{tg_user.username or 'none'})")
        return new_user

    async def update_language(self, user_id: int, language_code: str) -> None:
        """
        Update user language preference in database.

        Args:
            user_id: Telegram user ID.
            language_code: Target language ('en', 'hi', etc.).
        """
        db = get_db()
        await db.set_user_language(user_id, language_code)
        logger.info(f"Updated language preference for user {user_id} to '{language_code}'.")

    async def check_ban_status(self, user_id: int) -> Tuple[bool, Optional[str]]:
        """
        Check if user is banned and retrieve restriction reason.

        Args:
            user_id: Telegram user ID.

        Returns:
            Tuple[bool, Optional[str]]: (is_banned, reason).
        """
        db = get_db()
        user = await db.get_user(user_id)
        if not user or not user.is_banned:
            return False, None

        # Fetch ban reason from banned_users table
        async with db.get_connection() as conn:
            async with conn.execute("SELECT reason FROM banned_users WHERE user_id = ?", (user_id,)) as cursor:
                row = await cursor.fetchone()
                reason = row[0] if row else "Violation of terms of service."
                return True, reason


# Global UserService instance singleton
_user_service_instance = UserService()


def get_user_service() -> UserService:
    """Retrieve global UserService instance."""
    return _user_service_instance
