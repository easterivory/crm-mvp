from __future__ import annotations

import asyncio
import logging
import tempfile
from pathlib import Path

logger = logging.getLogger(__name__)

VIDEO_NOTE_FILTER = "crop=w='min(in_w,in_h)':h='min(in_w,in_h)',scale=320:320"
FFMPEG_TIMEOUT_SECONDS = 120


class VideoProcessingError(RuntimeError):
    """Raised when ffmpeg cannot produce a Telegram-compatible video note."""


async def crop_video_to_square(input_bytes: bytes) -> bytes:
    if not input_bytes:
        raise VideoProcessingError("Input video is empty")

    with tempfile.TemporaryDirectory(prefix="crm_video_note_") as temp_dir:
        input_path = Path(temp_dir) / "input_video"
        output_path = Path(temp_dir) / "video_note.mp4"
        await asyncio.to_thread(input_path.write_bytes, input_bytes)
        return await crop_video_file_to_square(input_path, output_path=output_path)


async def crop_video_file_to_square(
    input_path: Path,
    *,
    output_path: Path | None = None,
) -> bytes:
    if not input_path.exists():
        raise VideoProcessingError(f"Input video file does not exist: {input_path}")

    if output_path is None:
        with tempfile.TemporaryDirectory(prefix="crm_video_note_") as temp_dir:
            temp_output_path = Path(temp_dir) / "video_note.mp4"
            await _run_ffmpeg(input_path=input_path, output_path=temp_output_path)
            return await asyncio.to_thread(temp_output_path.read_bytes)

    await _run_ffmpeg(input_path=input_path, output_path=output_path)
    return await asyncio.to_thread(output_path.read_bytes)


async def _run_ffmpeg(*, input_path: Path, output_path: Path) -> None:
    command = (
        "ffmpeg",
        "-hide_banner",
        "-loglevel",
        "error",
        "-i",
        str(input_path),
        "-vf",
        VIDEO_NOTE_FILTER,
        "-c:v",
        "libx264",
        "-profile:v",
        "baseline",
        "-pix_fmt",
        "yuv420p",
        "-r",
        "30",
        "-c:a",
        "aac",
        "-b:a",
        "64k",
        "-movflags",
        "+faststart",
        "-y",
        str(output_path),
    )

    try:
        process = await asyncio.create_subprocess_exec(
            *command,
            stdout=asyncio.subprocess.PIPE,
            stderr=asyncio.subprocess.PIPE,
        )
    except FileNotFoundError as exc:
        raise VideoProcessingError("ffmpeg executable was not found") from exc

    try:
        stdout, stderr = await asyncio.wait_for(
            process.communicate(),
            timeout=FFMPEG_TIMEOUT_SECONDS,
        )
    except asyncio.TimeoutError as exc:
        process.kill()
        await process.wait()
        raise VideoProcessingError(
            f"ffmpeg timed out after {FFMPEG_TIMEOUT_SECONDS} seconds"
        ) from exc

    if process.returncode != 0:
        stderr_text = stderr.decode("utf-8", errors="replace").strip()
        stdout_text = stdout.decode("utf-8", errors="replace").strip()
        details = stderr_text or stdout_text or f"returncode={process.returncode}"
        raise VideoProcessingError(f"ffmpeg failed: {details[:1000]}")

    if not output_path.exists() or output_path.stat().st_size == 0:
        raise VideoProcessingError("ffmpeg produced an empty output file")

    logger.debug(
        "Video note crop completed input=%s output=%s output_size=%s",
        input_path,
        output_path,
        output_path.stat().st_size,
    )
