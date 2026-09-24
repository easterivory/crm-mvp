"""Readable representations for messages without a downloadable media file."""
from typing import Any


def telegram_message_summary(payload: dict[str, Any]) -> str:
    venue = payload.get("venue")
    location = payload.get("location")
    if isinstance(venue, dict):
        location = venue.get("location")
    if isinstance(location, dict):
        latitude, longitude = location.get("latitude"), location.get("longitude")
        heading = "Геолокация"
        if isinstance(venue, dict):
            heading = " · ".join(str(venue[key]) for key in ("title", "address") if venue.get(key)) or heading
        if isinstance(latitude, (int, float)) and isinstance(longitude, (int, float)):
            return f"{heading}\n{latitude}, {longitude}\nhttps://maps.google.com/?q={latitude},{longitude}"
        return heading
    poll = payload.get("poll")
    if isinstance(poll, dict):
        lines = [f"Опрос: {poll.get('question', '')}"]
        options = poll.get("options")
        if isinstance(options, list):
            lines.extend(f"• {option['text']}" for option in options if isinstance(option, dict) and isinstance(option.get("text"), str))
        return "\n".join(lines)
    dice = payload.get("dice")
    if isinstance(dice, dict):
        return f"Игровое сообщение: {dice.get('emoji', '')} · {dice.get('value', '')}"
    labels = {
        "story": "История Telegram: содержимое недоступно через Bot API.",
        "paid_media": "Платное медиа Telegram: просмотр в CRM не поддерживается.",
        "game": "Игра Telegram",
        "invoice": "Счёт Telegram",
        "successful_payment": "Уведомление об успешной оплате в Telegram",
        "new_chat_members": "В чат добавлены участники",
        "left_chat_member": "Участник покинул чат",
        "pinned_message": "Закреплено сообщение",
        "message_auto_delete_timer_changed": "Изменён таймер автоудаления сообщений",
        "web_app_data": "Данные из приложения Telegram",
        "users_shared": "Пользователь поделился контактами Telegram",
        "chat_shared": "Пользователь поделился чатом Telegram",
    }
    for key, label in labels.items():
        if key in payload:
            value = payload[key]
            title = value.get("title") if isinstance(value, dict) else None
            return f"{label}: {title}" if isinstance(title, str) else label
    return "Сообщение Telegram неподдерживаемого типа. Исходные данные сохранены для диагностики."
