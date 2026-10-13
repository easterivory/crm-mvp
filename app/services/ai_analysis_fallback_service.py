"""Conservative offline routing when an AI provider cannot analyse an answer."""
from __future__ import annotations

import difflib
import json
import re
import unicodedata
from functools import lru_cache
from pathlib import Path
from typing import Any

from app.schemas.ai import AIAnalysisPayload


def normalized_answer(value: str) -> str:
    text = unicodedata.normalize("NFKD", value.casefold().replace("ё", "е"))
    text = "".join(char for char in text if not unicodedata.combining(char))
    text = re.sub(r"['’‘ʻʼ`]+", "", text)
    return " ".join(re.sub(r"[^\w\s]", " ", text).split())


@lru_cache(maxsize=1)
def country_aliases() -> tuple[set[str], dict[str, str]]:
    data = json.loads((Path(__file__).parent.parent / "data" / "country_aliases.json").read_text(encoding="utf-8"))
    by_alias: dict[str, set[str]] = {}
    extra = {
        "RU": ["рф", "российское", "российский", "российская федерация", "россия", "россии"],
        "UZ": ["узб", "узбекистанское", "узбекское", "узбекский", "узбекистан", "узбекистана", "ozbekiston"],
        "KZ": ["рк", "казахстанское", "казакстан", "казахстана"],
        "BY": ["рб", "белоруссия", "белорусское", "беларусское"],
        "UA": ["украинское", "украины"], "KG": ["киргизия", "кыргызстан", "киргизское", "кыргызстана"],
        "TJ": ["таджикское"], "AM": ["армянское"], "AZ": ["азербайджанское"],
        "MX": ["mexicana", "mexicano"], "CO": ["colombiana", "colombiano"],
        "AR": ["argentino", "argentina"], "PE": ["peruano", "peruana"],
        "CL": ["chileno", "chilena"], "BR": ["brasileiro", "brasileira"],
    }
    for code, aliases in data["countries"].items():
        for alias in [*aliases, *extra.get(code, [])]:
            key = normalized_answer(alias)
            if key:
                by_alias.setdefault(key, set()).add(code)
                if re.fullmatch(r"[а-я ]+", key):
                    genitive = key[:-2] + "ии" if key.endswith("ия") else key[:-1] + ("и" if key.endswith("ка") else "ы") if key.endswith("а") else None
                    if genitive:
                        by_alias.setdefault(genitive, set()).add(code)
    return set(data["countries"]), {key: next(iter(codes)) for key, codes in by_alias.items() if len(codes) == 1}


@lru_cache(maxsize=1)
def _country_pattern():
    _, aliases = country_aliases()
    # Two-letter ISO codes are useful as standalone answers, but ambiguous in prose.
    phrases = sorted((key for key in aliases if len(key) >= 2 and not re.fullmatch(r"[a-z]{2,3}", key)), key=len, reverse=True)
    return re.compile(r"(?<!\w)(?:" + "|".join(re.escape(key) for key in phrases) + r")(?!\w)")


def citizenship_codes(answer: str) -> list[str]:
    known, aliases = country_aliases()
    codes: set[str] = set()
    for clause in re.split(r"[,;\n]+|\b(?:но|but|pero|а)\b", answer[:12000], flags=re.I):
        text = normalized_answer(clause)
        if (not text and not re.search(r"[\U0001F1E6-\U0001F1FF]{2}", clause)) or text in {"no", "not", "нет", "не", "да", "yes", "si"}:
            continue
        if any(symbol in clause for symbol in ("❌", "🚫", "⛔", "👎", "🙅", "?")):
            continue
        if text not in aliases and len(text.split()) == 1 and text.startswith(("не", "not", "no")):
            continue
        explicit = re.search(r"граждан|паспорт|citizen|passport|ciudadan|nacionalidad|fuqar|pasport", text)
        residence = re.search(r"живу|прожива|родил|национальности|\bиз\b|\blive\b|\bvivo\b|\bsoy de\b|\byashay", text)
        negative = re.search(r"\b(?:не|нет|нету|неимею|неявляюсь|негражданин|негражданка|отсутствует|not|no|sin|без|emas|yoq|эмас|емас|иуқ|иук)\b", text)
        if negative or (residence and not explicit):
            continue
        matched = {aliases[match.group()] for match in _country_pattern().finditer(text)}
        if text in aliases:
            matched.add(aliases[text])
        if explicit:
            matched.update(aliases[code.casefold()] for code in re.findall(r"(?<!\w)[A-Z]{2,3}(?!\w)", clause)
                           if code.casefold() in aliases)
        for flag in re.findall(r"[\U0001F1E6-\U0001F1FF]{2}", clause):
            code = "".join(chr(ord(char) - 0x1F1E6 + ord("A")) for char in flag)
            if code in known:
                matched.add(code)
        if not matched and len(text.split()) == 1 and 5 <= len(text) <= 64:
            candidates = difflib.get_close_matches(text, [key for key in aliases if len(key) >= 5], n=5, cutoff=.8)
            if candidates:
                best = difflib.SequenceMatcher(None, text, candidates[0]).ratio()
                matching = {aliases[key] for key in candidates if best - difflib.SequenceMatcher(None, text, key).ratio() < .06}
                if len(matching) == 1:
                    matched.update(matching)
        codes.update(matched)
    return sorted(codes)


def analyse_offline(answer: str, config: dict[str, Any]) -> AIAnalysisPayload:
    routes = [item for item in config.get("outcomes", []) if isinstance(item, dict) and item.get("id") != "fallback"]
    kind = config.get("fallback_type", "answers")
    matches: list[str] = []
    normalized = answer.strip()[:4000]
    if kind in {"answers", "citizenship"}:
        key = normalized_answer(answer)
        if key:
            matches = [str(item["id"]) for item in routes if key in {normalized_answer(str(alias)) for alias in item.get("aliases", [])}]
    if kind == "citizenship":
        codes = citizenship_codes(answer)
        listed = {str(code).upper() for item in routes if item.get("country_match") != "other" for code in item.get("country_codes", [])}
        if codes:
            normalized = ",".join(codes)
            for item in routes:
                allowed = {str(code).upper() for code in item.get("country_codes", [])}
                if (item.get("country_match") == "other" and all(code not in listed for code in codes)) or (
                    item.get("country_match", "listed") == "listed" and all(code in allowed for code in codes)
                ):
                    matches.append(str(item["id"]))
    matches = list(dict.fromkeys(matches))
    if len(matches) == 1 and next(item for item in routes if item["id"] == matches[0]).get("save_answer") is False:
        normalized = None
    return AIAnalysisPayload(next_route_key=matches[0] if len(matches) == 1 else "fallback",
                             normalized_answer=normalized if len(matches) == 1 else None)
