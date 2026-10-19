"""
Configuration subpackage for Productivity Hub.
Exports settings instance and Settings class.
"""

from .settings import Settings, get_settings

__all__ = ["Settings", "get_settings"]
