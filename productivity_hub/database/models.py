"""
Database Data Models.

Defines strongly-typed dataclasses and enums representing all entities in the Productivity Hub
database schema (Users, Tasks, Downloads, Conversions, QR History, Admins, Banned Users,
Suspicious Activity, Application Logs, and System Settings).
"""

from dataclasses import dataclass, field
from enum import Enum
from typing import Optional


class TaskStatus(str, Enum):
    """Enumeration of background task execution states."""
    PENDING = "pending"
    PROCESSING = "processing"
    COMPLETED = "completed"
    FAILED = "failed"
    CANCELLED = "cancelled"


@dataclass
class User:
    """
    Represents a registered Telegram user.

    Attributes:
        user_id: Telegram numeric user ID (Primary Key).
        username: Telegram handle without '@'.
        first_name: User's first name.
        last_name: User's last name.
        is_banned: Boolean flag indicating ban status.
        is_admin: Boolean flag indicating admin status.
        role: User role ('user', 'admin', 'owner').
        language: Selected language code ('en', 'hi', etc.).
        created_at: ISO timestamp of account registration.
        updated_at: ISO timestamp of last update.
    """
    user_id: int
    username: Optional[str] = None
    first_name: Optional[str] = None
    last_name: Optional[str] = None
    is_banned: bool = False
    is_admin: bool = False
    role: str = "user"
    language: str = "en"
    created_at: Optional[str] = None
    updated_at: Optional[str] = None


@dataclass
class Task:
    """
    Represents an asynchronous background task.

    Attributes:
        task_id: Unique UUID string for the task (Primary Key).
        user_id: Telegram user ID of owner.
        task_type: Type identifier ('download', 'convert', 'qr', etc.).
        status: Task execution status (TaskStatus).
        payload: JSON parameters string.
        result_data: JSON output string or file metadata.
        error_message: Error string if task failed.
        created_at: ISO timestamp of submission.
        updated_at: ISO timestamp of last status change.
    """
    task_id: str
    user_id: int
    task_type: str
    status: TaskStatus = TaskStatus.PENDING
    payload: Optional[str] = None
    result_data: Optional[str] = None
    error_message: Optional[str] = None
    created_at: Optional[str] = None
    updated_at: Optional[str] = None


@dataclass
class Download:
    """
    Represents a media downloader history record.
    """
    task_id: str
    user_id: int
    url: str
    id: Optional[int] = None
    service: Optional[str] = None
    title: Optional[str] = None
    file_path: Optional[str] = None
    file_size: Optional[int] = None
    status: str = "pending"
    created_at: Optional[str] = None


@dataclass
class Conversion:
    """
    Represents a document/file conversion history record.
    """
    task_id: str
    user_id: int
    source_format: str
    target_format: str
    id: Optional[int] = None
    source_file: Optional[str] = None
    result_file: Optional[str] = None
    file_size: Optional[int] = None
    status: str = "pending"
    created_at: Optional[str] = None


@dataclass
class QRHistory:
    """
    Represents a QR code generation or decoding event log.
    """
    user_id: int
    action_type: str
    content: str
    id: Optional[int] = None
    created_at: Optional[str] = None


@dataclass
class Admin:
    """
    Represents an authorized administrator account.
    """
    user_id: int
    added_by: int
    role: str = "admin"
    added_at: Optional[str] = None


@dataclass
class BannedUser:
    """
    Represents a banned user record.
    """
    user_id: int
    reason: str
    banned_by: int
    banned_at: Optional[str] = None


@dataclass
class SuspiciousUser:
    """
    Tracks users flagged by automated rate limiters or security policies.
    """
    user_id: int
    event_count: int = 1
    last_reason: Optional[str] = None
    updated_at: Optional[str] = None


@dataclass
class LogEntry:
    """
    Represents a structured application log entry stored in the database.
    """
    level: str
    logger_name: str
    message: str
    id: Optional[int] = None
    user_id: Optional[int] = None
    created_at: Optional[str] = None


@dataclass
class SystemSetting:
    """
    Represents a dynamic system configuration setting stored in SQLite.
    """
    key: str
    value: str
    updated_at: Optional[str] = None
