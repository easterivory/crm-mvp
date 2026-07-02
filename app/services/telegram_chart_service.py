from __future__ import annotations

from io import BytesIO
from pathlib import Path
from typing import Sequence

from PIL import Image, ImageDraw, ImageFont


WIDTH = 1280
HEIGHT = 820
BACKGROUND = "#0d1222"
PANEL = "#141b2d"
GRID = "#2c354b"
TEXT = "#f3f4f6"
MUTED = "#929bb0"
LEADS = "#35d0a2"
SUBMITTED = "#a78bfa"
SPEND = "#29c4df"


def render_stats_chart(
    *,
    title: str,
    labels: Sequence[str],
    leads: Sequence[int],
    submitted: Sequence[int],
    spend: Sequence[float],
    primary_label: str = "Leads",
    secondary_label: str = "Submitted",
) -> bytes:
    if not labels or not (len(labels) == len(leads) == len(submitted) == len(spend)):
        raise ValueError("Chart series must be non-empty and have equal lengths")

    image = Image.new("RGB", (WIDTH, HEIGHT), BACKGROUND)
    draw = ImageDraw.Draw(image)
    title_font = _font(34, bold=True)
    label_font = _font(20)
    small_font = _font(17)

    draw.text((54, 38), title, fill=TEXT, font=title_font)
    period = f"{labels[0]} - {labels[-1]}"
    draw.text((54, 86), period, fill=MUTED, font=label_font)

    top = (54, 132, WIDTH - 54, 468)
    bottom = (54, 510, WIDTH - 54, HEIGHT - 48)
    _panel(draw, top)
    _panel(draw, bottom)
    draw.text((78, 152), f"{primary_label} / {secondary_label}", fill=TEXT, font=label_font)
    draw.text((78, 530), "Расход, USD", fill=TEXT, font=label_font)

    _draw_line_panel(
        draw,
        bounds=(82, 202, WIDTH - 82, 432),
        labels=labels,
        series=[(leads, LEADS), (submitted, SUBMITTED)],
        font=small_font,
    )
    _draw_spend_panel(
        draw,
        bounds=(82, 574, WIDTH - 82, HEIGHT - 82),
        labels=labels,
        values=spend,
        font=small_font,
    )

    draw.rounded_rectangle((WIDTH - 430, 54, WIDTH - 390, 70), radius=8, fill=LEADS)
    draw.text((WIDTH - 378, 48), primary_label, fill=MUTED, font=small_font)
    draw.rounded_rectangle((WIDTH - 270, 54, WIDTH - 230, 70), radius=8, fill=SUBMITTED)
    draw.text((WIDTH - 218, 48), secondary_label, fill=MUTED, font=small_font)

    output = BytesIO()
    image.save(output, format="PNG", optimize=True)
    return output.getvalue()


def _panel(draw: ImageDraw.ImageDraw, bounds: tuple[int, int, int, int]) -> None:
    draw.rounded_rectangle(bounds, radius=18, fill=PANEL, outline=GRID, width=2)


def _draw_line_panel(
    draw: ImageDraw.ImageDraw,
    *,
    bounds: tuple[int, int, int, int],
    labels: Sequence[str],
    series: Sequence[tuple[Sequence[int], str]],
    font: ImageFont.FreeTypeFont | ImageFont.ImageFont,
) -> None:
    left, top, right, bottom = bounds
    maximum = max(1, *(max(values, default=0) for values, _ in series))
    _grid(draw, bounds, maximum, font, money=False)
    x_positions = _x_positions(left, right, len(labels))
    for values, color in series:
        points = [
            (x, bottom - int((value / maximum) * (bottom - top)))
            for x, value in zip(x_positions, values)
        ]
        if len(points) > 1:
            draw.line(points, fill=color, width=5, joint="curve")
        for x, y in points:
            draw.ellipse((x - 6, y - 6, x + 6, y + 6), fill=color)
    _x_labels(draw, labels, x_positions, bottom + 10, font)


def _draw_spend_panel(
    draw: ImageDraw.ImageDraw,
    *,
    bounds: tuple[int, int, int, int],
    labels: Sequence[str],
    values: Sequence[float],
    font: ImageFont.FreeTypeFont | ImageFont.ImageFont,
) -> None:
    left, top, right, bottom = bounds
    maximum = max(1.0, max(values, default=0.0))
    _grid(draw, bounds, maximum, font, money=True)
    x_positions = _x_positions(left, right, len(labels))
    slot = max((right - left) / max(len(labels), 1), 1)
    bar_width = max(8, min(int(slot * 0.55), 56))
    for x, value in zip(x_positions, values):
        height = int((value / maximum) * (bottom - top))
        draw.rounded_rectangle(
            (x - bar_width // 2, bottom - height, x + bar_width // 2, bottom),
            radius=5,
            fill=SPEND,
        )
    _x_labels(draw, labels, x_positions, bottom + 10, font)


def _grid(
    draw: ImageDraw.ImageDraw,
    bounds: tuple[int, int, int, int],
    maximum: float,
    font: ImageFont.FreeTypeFont | ImageFont.ImageFont,
    *,
    money: bool,
) -> None:
    left, top, right, bottom = bounds
    for index in range(5):
        ratio = index / 4
        y = bottom - int((bottom - top) * ratio)
        draw.line((left, y, right, y), fill=GRID, width=2)
        value = maximum * ratio
        label = f"${value:.0f}" if money else f"{value:.0f}"
        draw.text((left, y - 24), label, fill=MUTED, font=font)


def _x_positions(left: int, right: int, count: int) -> list[int]:
    if count <= 1:
        return [(left + right) // 2]
    return [left + int((right - left) * index / (count - 1)) for index in range(count)]


def _x_labels(
    draw: ImageDraw.ImageDraw,
    labels: Sequence[str],
    positions: Sequence[int],
    y: int,
    font: ImageFont.FreeTypeFont | ImageFont.ImageFont,
) -> None:
    step = max(1, len(labels) // 7)
    for index, (label, x) in enumerate(zip(labels, positions)):
        if index % step != 0 and index != len(labels) - 1:
            continue
        box = draw.textbbox((0, 0), label, font=font)
        draw.text((x - (box[2] - box[0]) / 2, y), label, fill=MUTED, font=font)


def _font(size: int, *, bold: bool = False) -> ImageFont.FreeTypeFont | ImageFont.ImageFont:
    candidates = [
        Path("/usr/share/fonts/truetype/dejavu/DejaVuSans-Bold.ttf" if bold else "/usr/share/fonts/truetype/dejavu/DejaVuSans.ttf"),
        Path("/System/Library/Fonts/Supplemental/Arial Bold.ttf" if bold else "/System/Library/Fonts/Supplemental/Arial.ttf"),
    ]
    for path in candidates:
        if path.exists():
            return ImageFont.truetype(str(path), size=size)
    return ImageFont.load_default()
