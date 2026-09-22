"""Opt-in Telegram HTML compiled to plain text and UTF-16 entities."""
from html.parser import HTMLParser
from urllib.parse import urlsplit


TAGS = {"b": "bold", "strong": "bold", "i": "italic", "em": "italic",
        "u": "underline", "s": "strikethrough", "del": "strikethrough",
        "tg-spoiler": "spoiler", "code": "code", "pre": "pre",
        "blockquote": "blockquote", "a": "text_link"}


class TelegramHTMLParser(HTMLParser):
    def __init__(self) -> None:
        super().__init__(convert_charrefs=True)
        self.parts: list[str] = []
        self.entities: list[dict] = []
        self.stack: list[tuple[str, dict]] = []
        self.utf16_offset = 0

    def handle_data(self, data: str) -> None:
        self.parts.append(data)
        self.utf16_offset += len(data.encode("utf-16-le")) // 2

    def handle_starttag(self, tag: str, attrs: list[tuple[str, str | None]]) -> None:
        if tag not in TAGS:
            raise ValueError(f"Неподдерживаемый тег оформления: {tag}")
        attributes = dict(attrs)
        if len(attrs) != len(attributes) or set(attributes) - ({"href"} if tag == "a" else set()):
            raise ValueError("Неподдерживаемые атрибуты оформления")
        if any(parent in {"code", "pre"} for parent, _ in self.stack) or (
            tag in {"code", "pre"} and self.stack
        ):
            raise ValueError("Код нельзя вкладывать в другое оформление")
        entity = {"type": TAGS[tag], "offset": self.utf16_offset}
        if tag == "a":
            url = attributes.get("href") or ""
            parsed = urlsplit(url)
            if parsed.scheme not in {"http", "https", "tg", "mailto"} or not (parsed.netloc or parsed.path):
                raise ValueError("Укажите корректную ссылку с https://, tg:// или mailto:")
            if any(parent == "a" for parent, _ in self.stack):
                raise ValueError("Ссылки нельзя вкладывать друг в друга")
            entity["url"] = url
        self.stack.append((tag, entity))

    def handle_endtag(self, tag: str) -> None:
        if not self.stack or self.stack[-1][0] != tag:
            raise ValueError("Незакрытые или пересекающиеся теги оформления")
        _, entity = self.stack.pop()
        entity["length"] = self.utf16_offset - entity["offset"]
        if entity["length"]:
            self.entities.append(entity)

    def handle_comment(self, data: str) -> None:
        raise ValueError("HTML-комментарии не поддерживаются")


def telegram_html(text: str) -> tuple[str, list[dict]]:
    parser = TelegramHTMLParser()
    parser.feed(text)
    parser.close()
    if parser.stack:
        raise ValueError("Не закрыты теги оформления")
    text = "".join(parser.parts)
    left = len(text[:len(text) - len(text.lstrip())].encode("utf-16-le")) // 2
    end = len(text.rstrip().encode("utf-16-le")) // 2
    entities = []
    for item in parser.entities:
        start = max(left, item["offset"])
        stop = min(end, item["offset"] + item["length"])
        if stop > start:
            entities.append({**item, "offset": start - left, "length": stop - start})
    return text.strip(), sorted(entities, key=lambda item: (item["offset"], -item["length"]))


def mtproto_entities(entities: list[dict]):
    from telethon.tl import types

    constructors = {"bold": types.MessageEntityBold, "italic": types.MessageEntityItalic,
                    "underline": types.MessageEntityUnderline, "strikethrough": types.MessageEntityStrike,
                    "spoiler": types.MessageEntitySpoiler, "code": types.MessageEntityCode,
                    "pre": types.MessageEntityPre, "blockquote": types.MessageEntityBlockquote,
                    "text_link": types.MessageEntityTextUrl}
    result = []
    for entity in entities:
        kind = entity["type"]
        extra = {"url": entity["url"]} if kind == "text_link" else {"language": ""} if kind == "pre" else {}
        result.append(constructors[kind](offset=entity["offset"], length=entity["length"], **extra))
    return result
