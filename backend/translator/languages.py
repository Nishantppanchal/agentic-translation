LANGUAGES = [
    "English",
    "Spanish",
    "French",
    "German",
    "Italian",
    "Portuguese",
    "Dutch",
    "Polish",
    "Swedish",
    "Turkish",
    "Russian",
    "Ukrainian",
    "Greek",
    "Arabic",
    "Hebrew",
    "Hindi",
    "Bengali",
    "Indonesian",
    "Vietnamese",
    "Thai",
    "Japanese",
    "Korean",
    "Chinese (Simplified)",
    "Chinese (Traditional)",
]

# BCP-47 codes (document language tags; XLIFF/TMX/TBX later).
LANG_CODES = {
    "English": "en", "Spanish": "es", "French": "fr", "German": "de", "Italian": "it", "Portuguese": "pt",
    "Dutch": "nl", "Polish": "pl", "Swedish": "sv", "Turkish": "tr", "Russian": "ru", "Ukrainian": "uk",
    "Greek": "el", "Arabic": "ar", "Hebrew": "he", "Hindi": "hi", "Bengali": "bn", "Indonesian": "id",
    "Vietnamese": "vi", "Thai": "th", "Japanese": "ja", "Korean": "ko",
    "Chinese (Simplified)": "zh-Hans", "Chinese (Traditional)": "zh-Hant",
}
RTL = {"ar", "he"}
EAST_ASIAN_FONTS = {"zh-Hans": "SimSun", "zh-Hant": "PMingLiU", "ja": "Yu Mincho", "ko": "Malgun Gothic"}


def language_name(code: str | None) -> str | None:
    """"de-DE" → "German" (None if unknown)."""
    primary = (code or "").split("-")[0].split("_")[0].lower()
    if primary == "zh":
        return "Chinese (Traditional)" if "hant" in (code or "").lower() or (code or "").upper().endswith(("TW", "HK")) else "Chinese (Simplified)"
    return next((name for name, c in LANG_CODES.items() if c == primary), None)


def lang_code(name: str | None) -> str:
    """BCP-47 code for a language name (also accepts names like "Chinese", or a code)."""
    if not name:
        return "und"
    if name in LANG_CODES:
        return LANG_CODES[name]
    if name.startswith("Chinese"):
        return "zh-Hant" if "Trad" in name else "zh-Hans"
    for full, code in LANG_CODES.items():
        if name.lower() in (full.lower(), code.lower()):
            return code
    return "und"
