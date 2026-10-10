"""Validated photo attachments shared by immediate and scheduled chat albums."""
import io
import json
from pathlib import Path
from dataclasses import dataclass

from fastapi import HTTPException
from PIL import Image, ImageOps, UnidentifiedImageError

from app.core.config import settings


@dataclass(frozen=True)
class AlbumPhoto:
    content: bytes
    file_name: str
    mime_type: str


def validate_album(photos: list[AlbumPhoto]) -> None:
    if not 2 <= len(photos) <= 10:
        raise HTTPException(status_code=422, detail="Альбом должен содержать от 2 до 10 фотографий.")
    for photo in photos:
        if not photo.content or len(photo.content) > min(settings.CHAT_PHOTO_MAX_MB, 10) * 1024 * 1024:
            raise HTTPException(status_code=413, detail="Фото пустое или превышает допустимый размер.")
        try:
            with Image.open(io.BytesIO(photo.content)) as image:
                width, height = image.size
                if (image.format not in {"JPEG", "PNG", "WEBP"} or getattr(image, "is_animated", False)
                        or width + height > 10000 or max(width, height) > 20 * min(width, height)):
                    raise ValueError("Unsupported Telegram photo")
                image.verify()
        except (ValueError, OSError, UnidentifiedImageError, Image.DecompressionBombError) as exc:
            raise HTTPException(status_code=422, detail="В альбом можно добавить только корректные фото JPEG, PNG или WebP.") from exc


def prepare_album(photos: list[AlbumPhoto]) -> list[AlbumPhoto]:
    validate_album(photos)
    prepared = []
    for photo in photos:
        with Image.open(io.BytesIO(photo.content)) as image:
            content = photo.content
            if image.format == "WEBP":
                output = io.BytesIO()
                ImageOps.exif_transpose(image).convert("RGB").save(output, format="JPEG", quality=90)
                content = output.getvalue()
            extension = ".png" if image.format == "PNG" else ".jpg"
            name = Path(photo.file_name).name
            prepared.append(AlbumPhoto(content, f"{Path(name).stem[:200] or 'photo'}{extension}",
                                       "image/png" if extension == ".png" else "image/jpeg"))
    validate_album(prepared)
    return prepared


def photo_album_form(photos: list[AlbumPhoto], external_chat_id: str,
                     caption: str | None, reply_parameters: dict | None) -> tuple[dict, dict]:
    media = [{"type": "photo", "media": f"attach://photo_{index}",
              **({"caption": caption} if index == 0 and caption else {})}
             for index in range(len(photos))]
    data = {"chat_id": external_chat_id, "media": json.dumps(media)}
    if reply_parameters:
        data["reply_parameters"] = json.dumps(reply_parameters)
    files = {f"photo_{index}": (photo.file_name, photo.content, photo.mime_type)
             for index, photo in enumerate(photos)}
    return data, files
