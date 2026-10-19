"""
Database subpackage for Productivity Hub.
Exports async database connection manager, models, and migrations.
"""

from .database import DatabaseManager, init_db, get_db, close_db
from .models import User, Task, TaskStatus, SystemSetting
from .migrations import run_migrations

__all__ = [
    "DatabaseManager",
    "init_db",
    "get_db",
    "close_db",
    "User",
    "Task",
    "TaskStatus",
    "SystemSetting",
    "run_migrations",
]
