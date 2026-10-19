"""
Inline Keyboard Builders & Callback Data Security Protocol.

Constructs secure InlineKeyboardMarkup layouts for Main Menu, Submenus, QR Tools,
and Task Controls. Embeds owner_id in callback data strings to enforce strict authorization
and prevent unauthorized cross-user interactions.
"""

from typing import Tuple, List, Optional
from telegram import InlineKeyboardButton, InlineKeyboardMarkup

from productivity_hub.utils.i18n import get_text


def parse_callback_data(data: str) -> Tuple[str, str, int]:
    """
    Parse a structured callback data string into action, payload, and owner_id.

    Format: 'action:payload:owner_id'

    Args:
        data: Callback string.

    Returns:
        Tuple[str, str, int]: (action, payload, owner_id).
    """
    parts = data.split(":")
    if len(parts) >= 3:
        action = parts[0]
        payload = ":".join(parts[1:-1])
        try:
            owner_id = int(parts[-1])
        except ValueError:
            owner_id = 0
        return action, payload, owner_id
    elif len(parts) == 2:
        try:
            return parts[0], "", int(parts[1])
        except ValueError:
            return parts[0], parts[1], 0
    return data, "", 0


def get_main_menu_keyboard(owner_id: int, lang: str = "en") -> InlineKeyboardMarkup:
    """
    Build the main menu inline keyboard with the 6 primary options:
    - 🎬 Media Downloader
    - 🔄 File Converter
    - 🪄 Background Remover
    - 📦 File Compressor
    - 🔳 QR Code Tools
    - ❓ Help
    """
    keyboard = [
        [
            InlineKeyboardButton(get_text("menu_downloader", lang), callback_data=f"menu:downloader:{owner_id}"),
            InlineKeyboardButton(get_text("menu_converter", lang), callback_data=f"menu:converter:{owner_id}")
        ],
        [
            InlineKeyboardButton(get_text("menu_bg_remover", lang), callback_data=f"menu:bg_remover:{owner_id}"),
            InlineKeyboardButton(get_text("menu_compressor", lang), callback_data=f"menu:compressor:{owner_id}")
        ],
        [
            InlineKeyboardButton(get_text("menu_qr", lang), callback_data=f"menu:qr:{owner_id}"),
            InlineKeyboardButton(get_text("menu_help", lang), callback_data=f"menu:help:{owner_id}")
        ]
    ]
    return InlineKeyboardMarkup(keyboard)


def get_qr_menu_keyboard(owner_id: int, lang: str = "en") -> InlineKeyboardMarkup:
    """
    Build the QR Tools submenu with exactly two primary options:
    - QR Generator
    - QR Scanner
    Plus Back button.
    """
    keyboard = [
        [
            InlineKeyboardButton(get_text("menu_qr_generator", lang), callback_data=f"qr:generator:{owner_id}"),
            InlineKeyboardButton(get_text("menu_qr_scanner", lang), callback_data=f"qr:scanner:{owner_id}")
        ],
        [
            InlineKeyboardButton(get_text("menu_back", lang), callback_data=f"menu:main:{owner_id}")
        ]
    ]
    return InlineKeyboardMarkup(keyboard)


def get_language_keyboard(owner_id: int, current_lang: str = "en") -> InlineKeyboardMarkup:
    """Build language selection keyboard (English & Hindi)."""
    en_check = " ✅" if current_lang == "en" else ""
    hi_check = " ✅" if current_lang == "hi" else ""
    keyboard = [
        [
            InlineKeyboardButton(f"🇬🇧 English{en_check}", callback_data=f"lang:set_en:{owner_id}"),
            InlineKeyboardButton(f"🇮🇳 हिंदी{hi_check}", callback_data=f"lang:set_hi:{owner_id}")
        ],
        [
            InlineKeyboardButton(get_text("menu_back", current_lang), callback_data=f"menu:main:{owner_id}")
        ]
    ]
    return InlineKeyboardMarkup(keyboard)


def get_back_keyboard(owner_id: int, lang: str = "en") -> InlineKeyboardMarkup:
    """Build a simple 'Back to Main Menu' keyboard."""
    keyboard = [
        [InlineKeyboardButton(get_text("menu_back", lang), callback_data=f"menu:main:{owner_id}")]
    ]
    return InlineKeyboardMarkup(keyboard)


def get_cancel_keyboard(task_id: str, owner_id: int, lang: str = "en") -> InlineKeyboardMarkup:
    """Build task cancellation keyboard."""
    keyboard = [
        [InlineKeyboardButton(get_text("btn_cancel", lang), callback_data=f"cancel:{task_id}:{owner_id}")]
    ]
    return InlineKeyboardMarkup(keyboard)


def get_retry_keyboard(action: str, owner_id: int, lang: str = "en") -> InlineKeyboardMarkup:
    """Build retry and back keyboard."""
    keyboard = [
        [InlineKeyboardButton(get_text("btn_retry", lang), callback_data=f"retry:{action}:{owner_id}")],
        [InlineKeyboardButton(get_text("menu_back", lang), callback_data=f"menu:main:{owner_id}")]
    ]
    return InlineKeyboardMarkup(keyboard)


def build_paginated_keyboard(
    items: List[Tuple[str, str]],
    page: int,
    page_size: int,
    callback_prefix: str,
    owner_id: int,
    lang: str = "en",
    row_width: int = 2
) -> InlineKeyboardMarkup:
    """
    Build a dynamic paginated keyboard for formats or options.

    Args:
        items: List of (label, callback_payload) tuples.
        page: Current page index (0-based).
        page_size: Number of items per page.
        callback_prefix: Prefix for callback data (e.g., 'convfmt').
        owner_id: Numeric owner ID.
        lang: User language code.
        row_width: Number of items per row.

    Returns:
        InlineKeyboardMarkup: Paginated inline keyboard.
    """
    total_pages = max(1, (len(items) + page_size - 1) // page_size)
    page = max(0, min(page, total_pages - 1))

    start_idx = page * page_size
    end_idx = start_idx + page_size
    page_items = items[start_idx:end_idx]

    keyboard: List[List[InlineKeyboardButton]] = []
    current_row: List[InlineKeyboardButton] = []

    for label, payload in page_items:
        current_row.append(
            InlineKeyboardButton(label, callback_data=f"{callback_prefix}:{payload}:{owner_id}")
        )
        if len(current_row) == row_width:
            keyboard.append(current_row)
            current_row = []

    if current_row:
        keyboard.append(current_row)

    # Navigation pagination row if multiple pages
    if total_pages > 1:
        nav_row: List[InlineKeyboardButton] = []
        if page > 0:
            nav_row.append(
                InlineKeyboardButton("◀️ Prev", callback_data=f"page:{callback_prefix}:{page - 1}:{owner_id}")
            )
        nav_row.append(
            InlineKeyboardButton(f"{page + 1} / {total_pages}", callback_data=f"page:noop:0:{owner_id}")
        )
        if page < total_pages - 1:
            nav_row.append(
                InlineKeyboardButton("Next ▶️", callback_data=f"page:{callback_prefix}:{page + 1}:{owner_id}")
            )
        keyboard.append(nav_row)

    # Back button row
    keyboard.append([
        InlineKeyboardButton(get_text("menu_back", lang), callback_data=f"menu:main:{owner_id}")
    ])

    return InlineKeyboardMarkup(keyboard)
