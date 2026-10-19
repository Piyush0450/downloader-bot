"""
Internationalization & Multi-Language Translation System.

Provides localized UI string resolution for English ('en') and Hindi ('hi').
Defaults gracefully to English if a localized translation string or language key is missing.
"""

from typing import Dict, Any

SUPPORTED_LANGUAGES: Dict[str, str] = {
    "en": "🇬🇧 English",
    "hi": "🇮🇳 हिंदी (Hindi)",
}

# Master Translation Dictionary
TRANSLATIONS: Dict[str, Dict[str, str]] = {
    "en": {
        "welcome_title": "🚀 *Welcome to Productivity Hub!*",
        "welcome_body": (
            "Your all-in-one assistant for media downloading, universal file conversion, "
            "background removal, file compression, and QR operations.\n\n"
            "Please select an option from the menu below to get started:"
        ),
        "menu_downloader": "🎬 Media Downloader",
        "menu_converter": "🔄 File Converter",
        "menu_bg_remover": "🪄 Background Remover",
        "menu_compressor": "📦 File Compressor",
        "menu_qr": "🔳 QR Code Tools",
        "menu_help": "❓ Help",
        "menu_back": "⬅️ Back",
        "btn_cancel": "❌ Cancel",
        "btn_retry": "🔄 Retry",

        # QR Submenu
        "title_qr_menu": "🔳 *QR Code Tools*",
        "desc_qr_menu": "Please choose whether you want to generate a new QR code or scan an existing one:",
        "menu_qr_generator": "🔳 QR Generator",
        "menu_qr_scanner": "📷 QR Scanner",

        # Submenu Titles & Descriptions
        "title_downloader": "🎬 *Universal Media Downloader*",
        "desc_downloader": (
            "Paste any media link from YouTube, Instagram, TikTok, Twitter/X, "
            "Reddit, Pinterest, Facebook, Vimeo, or SoundCloud.\n\n"
            "The bot will extract metadata, provide quality options (360p, 720p, 1080p, MP3), "
            "and download your file."
        ),

        "title_converter": "🔄 *Universal File Converter*",
        "desc_converter": (
            "Upload any document, image, audio, video, spreadsheet, or archive.\n\n"
            "The bot will automatically detect the file signature and show only verified, "
            "available target formats."
        ),

        "title_bg_remover": "🪄 *Image Background Remover*",
        "desc_bg_remover": (
            "Upload any photo or image (JPG, PNG, WEBP).\n\n"
            "The bot will remove the background and return a high-quality transparent PNG."
        ),

        "title_compressor": "📦 *Universal File Compressor*",
        "desc_compressor": (
            "Send an image, PDF document, video, audio, or archive to reduce its file size.\n\n"
            "The bot adapts to the input format, optimizes the file, and reports exact savings."
        ),

        "title_qr_generator": "🔳 *QR Code Generator*",
        "desc_qr_generator": (
            "Choose a payload category to generate a scannable QR code:\n"
            "• *Text / URL*\n"
            "• *Contact / vCard*\n"
            "• *Wi-Fi Network*\n"
            "• *Calendar Event*\n"
            "• *Email / SMS*\n"
            "• *Payment URI*"
        ),

        "title_qr_scanner": "📷 *QR Code Scanner*",
        "desc_qr_scanner": (
            "Upload any image containing one or more QR codes.\n\n"
            "The bot will detect and decode all QR payloads, identify their content types, "
            "and display them safely."
        ),

        "title_lang": "🌐 *Language Selection*",
        "desc_lang": "Choose your preferred language:",
        "lang_changed": "✅ *Language updated to English!*",

        # Security & Limits
        "err_unauthorized_button": "⚠️ This menu belongs to another user. Please send /start to open your own menu.",
        "err_banned": "🚫 Your account has been restricted from using this bot. Reason: {reason}",
        "err_maintenance": "🛠️ The bot is currently undergoing maintenance. Please try again shortly.",
        "err_rate_limit": "⏳ Please wait {wait_time}s before sending another request.",
        "err_queue_full": "⚠️ System queue is currently full. Please try again in a few moments.",
        "err_user_limit": "⚠️ You already have an active task running. Please wait for it to complete.",
        "err_file_too_large": "⚠️ File exceeds the maximum allowed size of {max_mb} MB.",

        # Help Guide
        "help_title": "📖 *Productivity Hub Help & Guide*",
        "help_body": (
            "*Supported Modules:*\n\n"
            "• 🎬 *Media Downloader*: Paste any media URL to view formats and download.\n"
            "• 🔄 *File Converter*: Upload any file to see verified conversion formats.\n"
            "• 🪄 *Background Remover*: Upload any photo to remove its background.\n"
            "• 📦 *File Compressor*: Upload a document, image, or media to reduce file size.\n"
            "• 🔳 *QR Code Tools*: Generate custom QR payloads or scan QR images.\n\n"
            "*Navigation Commands:*\n"
            "• /start - Open the primary menu\n"
            "• /help - View this help guide\n"
            "• /cancel - Cancel active or pending operation"
        ),
    },

    "hi": {
        "welcome_title": "🚀 *प्रोडक्टिविटी हब में आपका स्वागत है!*",
        "welcome_body": (
            "मीडिया डाउनलोड, फ़ाइल रूपांतरण, बैकग्राउंड रिमूवल, "
            "फ़ाइल कम्प्रेशन और क्यूआर कोड टूल्स के लिए आपका ऑल-इन-वन सहायक।\n\n"
            "शुरू करने के लिए नीचे दिए गए मेनू से एक विकल्प चुनें:"
        ),
        "menu_downloader": "🎬 मीडिया डाउनलोडर",
        "menu_converter": "🔄 फ़ाइल कनवर्टर",
        "menu_bg_remover": "🪄 बैकग्राउंड रिमूवर",
        "menu_compressor": "📦 फ़ाइल कंप्रेसर",
        "menu_qr": "🔳 क्यूआर टूल्स",
        "menu_help": "❓ सहायता",
        "menu_back": "⬅️ पीछे जाएं",
        "btn_cancel": "❌ रद्द करें",
        "btn_retry": "🔄 पुनः प्रयास करें",

        "title_qr_menu": "🔳 *क्यूआर कोड टूल्स*",
        "desc_qr_menu": "कृपया चुनें कि आप एक नया क्यूआर कोड बनाना चाहते हैं या स्कैन करना चाहते हैं:",
        "menu_qr_generator": "🔳 क्यूआर जनरेटर",
        "menu_qr_scanner": "📷 क्यूआर स्कैनर",

        "title_downloader": "🎬 *यूनिवर्सल मीडिया डाउनलोडर*",
        "desc_downloader": "यूट्यूब, इंस्टाग्राम, टिकटॉक, ट्विटर, रेडिट आदि का लिंक भेजें।",

        "title_converter": "🔄 *यूनिवर्सल फ़ाइल कनवर्टर*",
        "desc_converter": "कोई भी दस्तावेज़, छवि, ऑडियो या वीडियो फ़ाइल भेजें।",

        "title_bg_remover": "🪄 *इमेज बैकग्राउंड रिमूवर*",
        "desc_bg_remover": "बैकग्राउंड हटाने के लिए कोई भी फोटो भेजें।",

        "title_compressor": "📦 *यूनिवर्सल फ़ाइल कंप्रेसर*",
        "desc_compressor": "फ़ाइल का साइज़ कम करने के लिए दस्तावेज़ या मीडिया भेजें।",

        "title_qr_generator": "🔳 *क्यूआर कोड जनरेटर*",
        "desc_qr_generator": "टेक्स्ट, यूआरएल, वाई-फाई या संपर्क का क्यूआर कोड बनाएं।",

        "title_qr_scanner": "📷 *क्यूआर कोड स्कैनर*",
        "desc_qr_scanner": "क्यूआर कोड वाली फोटो अपलोड करें।",

        "title_lang": "🌐 *भाषा चयन*",
        "desc_lang": "अपनी पसंदीदा भाषा चुनें:",
        "lang_changed": "✅ *भाषा हिंदी में बदल दी गई है!*",

        "err_unauthorized_button": "⚠️ यह मेनू किसी अन्य उपयोगकर्ता का है। कृपया नया मेनू खोलने के लिए /start भेजें।",
        "err_banned": "🚫 आपके खाते को प्रतिबंधित कर दिया गया है। कारण: {reason}",
        "err_maintenance": "🛠️ बॉट में वर्तमान में रखरखाव चल रहा है। कृपया कुछ समय बाद पुनः प्रयास करें।",
        "err_rate_limit": "⏳ कृपया अगला अनुरोध भेजने से पहले {wait_time}s प्रतीक्षा करें।",
        "err_queue_full": "⚠️ सिस्टम कतार अभी भरी हुई है। कृपया कुछ क्षणों में पुनः प्रयास करें।",
        "err_user_limit": "⚠️ आपका एक कार्य पहले से चल रहा है। कृपया उसके पूरा होने की प्रतीक्षा करें।",
        "err_file_too_large": "⚠️ फ़ाइल {max_mb} MB की अधिकतम सीमा से अधिक है।",

        "help_title": "📖 *प्रोडक्टिविटी हब सहायता*",
        "help_body": (
            "*समर्थित मॉड्यूल:*\n\n"
            "• 🎬 *मीडिया डाउनलोडर*: वीडियो या ऑडियो डाउनलोड करने के लिए लिंक भेजें।\n"
            "• 🔄 *फ़ाइल कनवर्टर*: विभिन्न प्रारूपों में फ़ाइल बदलने के लिए अपलोड करें।\n"
            "• 🪄 *बैकग्राउंड रिमूवर*: फ़ोटो का बैकग्राउंड हटाने के लिए इमेज भेजें।\n"
            "• 📦 *फ़ाइल कंप्रेसर*: फ़ाइल साइज़ कम करने के लिए भेजें।\n"
            "• 🔳 *क्यूआर टूल्स*: क्यूआर बनाएं या स्कैन करें।\n\n"
            "*कमांड्स:*\n"
            "• /start - मुख्य मेनू खोलें\n"
            "• /help - सहायता मार्गदर्शिका देखें\n"
            "• /cancel - सक्रिय कार्य रद्द करें"
        ),
    }
}


def get_text(key: str, lang: str = "en", **kwargs: Any) -> str:
    """
    Retrieve localized string by key and language code.
    Falls back gracefully to English if the key is missing in target language.

    Args:
        key: Translation key.
        lang: Target language code ('en', 'hi').
        **kwargs: Optional string formatting arguments.

    Returns:
        str: Resolved, formatted translation string.
    """
    lang_dict = TRANSLATIONS.get(lang, TRANSLATIONS["en"])
    text_template = lang_dict.get(key) or TRANSLATIONS["en"].get(key, f"[{key}]")

    if kwargs:
        try:
            return text_template.format(**kwargs)
        except Exception:
            return text_template

    return text_template
