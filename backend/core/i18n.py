"""Fixed UI text (labels, buttons, questions) comes from reviewed translation files,
never from the language model."""
import json

from core.config import MIGRATIONS_DIR

I18N_DIR = MIGRATIONS_DIR.parent / "i18n"
_cache: dict = {}


def _load(lang: str) -> dict:
    if lang not in _cache:
        path = I18N_DIR / f"{lang}.json"
        _cache[lang] = json.loads(path.read_text(encoding="utf-8")) if path.exists() else {}
    return _cache[lang]


def t(key: str, lang: str = "en") -> str:
    """Translate a key; falls back to English, then to the key itself."""
    return _load(lang).get(key) or _load("en").get(key) or key


def is_reviewed(lang: str) -> bool:
    return bool(_load(lang).get("_meta", {}).get("reviewed"))
