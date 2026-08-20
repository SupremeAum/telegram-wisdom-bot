"""Транслитерация кириллицы в латиницу.

Нужна потому, что текст на карточках рендерится только латиницей:
кириллица в декоративных шрифтах часто ломается (отсутствующие глифы,
кривой кернинг), а латинский набор поддержан везде.
"""

from __future__ import annotations

# Практическая транслитерация (BGN/PCGN-подобная), оптимизированная
# под читаемость названий, а не под обратимость.
_MAP = {
    "а": "a", "б": "b", "в": "v", "г": "g", "д": "d", "е": "e", "ё": "e",
    "ж": "zh", "з": "z", "и": "i", "й": "y", "к": "k", "л": "l", "м": "m",
    "н": "n", "о": "o", "п": "p", "р": "r", "с": "s", "т": "t", "у": "u",
    "ф": "f", "х": "kh", "ц": "ts", "ч": "ch", "ш": "sh", "щ": "shch",
    "ъ": "", "ы": "y", "ь": "", "э": "e", "ю": "yu", "я": "ya",
    # казахские буквы
    "ә": "a", "ғ": "g", "қ": "q", "ң": "ng", "ө": "o", "ұ": "u",
    "ү": "u", "һ": "h", "і": "i",
}

# Устоявшиеся написания — их транслитерировать по буквам нельзя.
_OVERRIDES = {
    "усть-каменогорск": "Ust-Kamenogorsk",
    "óskemen": "Oskemen",
    "өскемен": "Oskemen",
    "казахстан": "Kazakhstan",
    "алматы": "Almaty",
    "астана": "Astana",
}


def translit(text: str) -> str:
    """Переводит кириллицу в латиницу, сохраняя регистр и пунктуацию."""
    if not text:
        return ""

    lowered = text.strip().lower()
    if lowered in _OVERRIDES:
        return _OVERRIDES[lowered]

    out: list[str] = []
    for char in text:
        lower = char.lower()
        replacement = _MAP.get(lower)
        if replacement is None:
            out.append(char)
            continue
        if char.isupper():
            replacement = replacement.capitalize()
        out.append(replacement)
    return "".join(out)


def is_cyrillic(text: str) -> bool:
    """True, если в строке есть хоть один кириллический символ."""
    return any("Ѐ" <= char <= "ӿ" for char in text)


def latin_only(text: str) -> str:
    """Гарантирует, что на карточку уйдёт только латиница."""
    result = translit(text)
    if is_cyrillic(result):  # подстраховка на случай пропущенного символа
        result = "".join(ch for ch in result if not is_cyrillic(ch))
    return result
