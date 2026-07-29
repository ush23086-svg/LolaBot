from __future__ import annotations

import asyncio
import logging
import os
import shutil
import socket
import subprocess
import sys
import tempfile
from contextlib import suppress
from dataclasses import dataclass
from pathlib import Path

import yt_dlp
from aiogram import Bot
from aiogram.client.session.aiohttp import AiohttpSession
from aiogram.types import FSInputFile
from dotenv import load_dotenv

from app.services.video_queue import VideoJob, VideoQueueService

logger = logging.getLogger(__name__)

VIDEO_EXTENSIONS = {".mp4", ".mov", ".mkv", ".webm", ".m4v"}
AUDIO_EXTENSIONS = {".m4a", ".aac", ".mp3", ".ogg", ".opus", ".weba", ".wav"}


class PermanentJobError(RuntimeError):
    """A link that should not be retried automatically."""


@dataclass(frozen=True, slots=True)
class WorkerSettings:
    telegram_bot_token: str
    database_url: str
    worker_id: str
    poll_seconds: float
    max_attempts: int
    retry_delay_seconds: int
    lease_timeout_minutes: int
    max_duration_seconds: int
    max_upload_bytes: int
    download_timeout_seconds: int
    upload_timeout_seconds: int
    cookies_file: Path | None

    @classmethod
    def from_env(cls) -> "WorkerSettings":
        token = (os.getenv("TELEGRAM_BOT_TOKEN") or os.getenv("BOT_TOKEN") or "").strip()
        database_url = (os.getenv("DATABASE_URL") or "").strip()
        if not token:
            raise RuntimeError("TELEGRAM_BOT_TOKEN topilmadi")
        if not database_url:
            raise RuntimeError("DATABASE_URL topilmadi")

        configured_worker_id = (os.getenv("VIDEO_WORKER_ID") or "").strip()
        worker_id = configured_worker_id or f"{socket.gethostname()}-{os.getpid()}"
        cookies_value = (os.getenv("VIDEO_COOKIES_FILE") or "cookies.txt").strip()
        cookies_path = Path(cookies_value).expanduser() if cookies_value else None
        if cookies_path and not cookies_path.exists():
            cookies_path = None

        max_upload_mb = _env_float("VIDEO_MAX_UPLOAD_MB", 49.0, minimum=1.0)
        return cls(
            telegram_bot_token=token,
            database_url=database_url,
            worker_id=worker_id,
            poll_seconds=_env_float("VIDEO_POLL_SECONDS", 3.0, minimum=1.0),
            max_attempts=_env_int("VIDEO_MAX_ATTEMPTS", 3, minimum=1),
            retry_delay_seconds=_env_int("VIDEO_RETRY_DELAY_SECONDS", 90, minimum=10),
            lease_timeout_minutes=_env_int("VIDEO_LEASE_TIMEOUT_MINUTES", 30, minimum=5),
            max_duration_seconds=_env_int("VIDEO_MAX_DURATION_SECONDS", 600, minimum=10),
            max_upload_bytes=int(max_upload_mb * 1024 * 1024),
            download_timeout_seconds=_env_int("VIDEO_DOWNLOAD_TIMEOUT_SECONDS", 420, minimum=60),
            upload_timeout_seconds=_env_int("VIDEO_UPLOAD_TIMEOUT_SECONDS", 300, minimum=60),
            cookies_file=cookies_path,
        )


def _env_int(name: str, default: int, minimum: int) -> int:
    try:
        value = int((os.getenv(name) or str(default)).strip())
    except ValueError:
        value = default
    return max(minimum, value)


def _env_float(name: str, default: float, minimum: float) -> float:
    try:
        value = float((os.getenv(name) or str(default)).strip())
    except ValueError:
        value = default
    return max(minimum, value)


def _load_environment() -> None:
    explicit = (os.getenv("VIDEO_WORKER_ENV_FILE") or ".env.worker").strip()
    if explicit:
        load_dotenv(explicit, override=False)
    load_dotenv(override=False)


def _resolve_ffmpeg() -> str:
    direct = shutil.which("ffmpeg")
    if direct:
        return direct

    try:
        import imageio_ffmpeg

        return imageio_ffmpeg.get_ffmpeg_exe()
    except Exception as exc:  # pragma: no cover - depends on local machine
        raise RuntimeError("ffmpeg topilmadi") from exc


def _iter_media_files(root: Path, extensions: set[str]) -> list[Path]:
    files: list[Path] = []
    for path in root.rglob("*"):
        if not path.is_file():
            continue
        if path.suffix.lower() not in extensions:
            continue
        lowered = path.name.lower()
        if lowered.endswith((".part", ".temp", ".tmp", ".ytdl")):
            continue
        if path.stat().st_size <= 0:
            continue
        files.append(path)
    return sorted(files, key=lambda item: item.stat().st_size, reverse=True)


def _first_entry(info: dict | None) -> dict:
    if not info:
        return {}
    entries = info.get("entries")
    if entries:
        for entry in entries:
            if entry:
                return entry
    return info


def _base_ydl_options(
    work_dir: Path,
    ffmpeg_path: str,
    cookies_file: Path | None,
) -> dict:
    options: dict = {
        "quiet": True,
        "no_warnings": True,
        "noplaylist": True,
        "restrictfilenames": True,
        "windowsfilenames": True,
        "outtmpl": str(work_dir / "source_%(id)s.%(ext)s"),
        "ffmpeg_location": ffmpeg_path,
        "socket_timeout": 30,
        "retries": 3,
        "fragment_retries": 3,
    }
    if cookies_file:
        options["cookiefile"] = str(cookies_file)
    return options


def _download_with_ytdlp(
    url: str,
    work_dir: Path,
    ffmpeg_path: str,
    cookies_file: Path | None,
    max_duration_seconds: int,
) -> tuple[Path, Path | None]:
    probe_options = _base_ydl_options(work_dir, ffmpeg_path, cookies_file)
    probe_options["skip_download"] = True

    with yt_dlp.YoutubeDL(probe_options) as ydl:
        info = _first_entry(ydl.extract_info(url, download=False))

    duration = info.get("duration")
    if duration is not None and float(duration) > max_duration_seconds:
        raise PermanentJobError("video duration limit exceeded")

    download_options = _base_ydl_options(work_dir, ffmpeg_path, cookies_file)
    download_options.update(
        {
            "format": (
                "bestvideo[height<=720][ext=mp4]+bestaudio[ext=m4a]/"
                "bestvideo[height<=720]+bestaudio/"
                "best[height<=720][ext=mp4]/best[height<=720]/best"
            ),
            "merge_output_format": "mp4",
        }
    )

    with yt_dlp.YoutubeDL(download_options) as ydl:
        ydl.extract_info(url, download=True)

    videos = _iter_media_files(work_dir, VIDEO_EXTENSIONS)
    if not videos:
        raise RuntimeError("yt-dlp video topmadi")
    return videos[0], None


def _download_with_gallery_dl(
    url: str,
    work_dir: Path,
    cookies_file: Path | None,
    timeout_seconds: int,
) -> tuple[Path, Path | None]:
    command = [
        sys.executable,
        "-m",
        "gallery_dl",
        "--no-mtime",
        "-D",
        str(work_dir),
    ]
    if cookies_file:
        command.extend(["--cookies", str(cookies_file)])
    command.append(url)

    result = subprocess.run(
        command,
        capture_output=True,
        text=True,
        encoding="utf-8",
        errors="ignore",
        timeout=timeout_seconds,
        check=False,
    )
    if result.returncode != 0:
        detail = (result.stderr or result.stdout or "gallery-dl failed").strip()
        raise RuntimeError(detail[-1000:])

    videos = _iter_media_files(work_dir, VIDEO_EXTENSIONS)
    if not videos:
        raise PermanentJobError("postda video topilmadi")
    audios = _iter_media_files(work_dir, AUDIO_EXTENSIONS)
    return videos[0], audios[0] if audios else None


def _download_source(
    job: VideoJob,
    work_dir: Path,
    ffmpeg_path: str,
    settings: WorkerSettings,
) -> tuple[Path, Path | None]:
    first_error: Exception | None = None
    try:
        return _download_with_ytdlp(
            job.url,
            work_dir,
            ffmpeg_path,
            settings.cookies_file,
            settings.max_duration_seconds,
        )
    except PermanentJobError:
        raise
    except Exception as exc:
        first_error = exc

    if job.source not in {"instagram", "tiktok", "x"}:
        raise RuntimeError(str(first_error or "download failed"))

    try:
        return _download_with_gallery_dl(
            job.url,
            work_dir,
            settings.cookies_file,
            settings.download_timeout_seconds,
        )
    except PermanentJobError:
        raise
    except Exception as fallback_error:
        raise RuntimeError(
            f"yt-dlp: {first_error}; gallery-dl: {fallback_error}"
        ) from fallback_error


def _run_ffmpeg(
    *,
    source_video: Path,
    source_audio: Path | None,
    output: Path,
    ffmpeg_path: str,
    compact: bool,
    timeout_seconds: int,
) -> None:
    if compact:
        scale = "scale=w='min(854,iw)':h='min(480,ih)':force_original_aspect_ratio=decrease:force_divisible_by=2"
        crf = "30"
        audio_bitrate = "96k"
    else:
        scale = "scale=w='min(1280,iw)':h='min(720,ih)':force_original_aspect_ratio=decrease:force_divisible_by=2"
        crf = "25"
        audio_bitrate = "128k"

    command = [ffmpeg_path, "-y", "-i", str(source_video)]
    if source_audio:
        command.extend(["-i", str(source_audio)])

    command.extend(["-map", "0:v:0"])
    if source_audio:
        command.extend(["-map", "1:a:0"])
    else:
        command.extend(["-map", "0:a:0?"])

    command.extend(
        [
            "-vf",
            f"{scale},fps=30,format=yuv420p",
            "-c:v",
            "libx264",
            "-preset",
            "veryfast",
            "-crf",
            crf,
            "-profile:v",
            "high",
            "-level:v",
            "4.1",
            "-c:a",
            "aac",
            "-b:a",
            audio_bitrate,
            "-ar",
            "48000",
            "-ac",
            "2",
            "-movflags",
            "+faststart",
            "-max_muxing_queue_size",
            "2048",
            "-shortest",
            str(output),
        ]
    )

    result = subprocess.run(
        command,
        capture_output=True,
        text=True,
        encoding="utf-8",
        errors="ignore",
        timeout=timeout_seconds,
        check=False,
    )
    if result.returncode != 0 or not output.exists() or output.stat().st_size <= 0:
        detail = (result.stderr or result.stdout or "ffmpeg failed").strip()
        raise RuntimeError(detail[-1500:])


def _prepare_telegram_video(
    source_video: Path,
    source_audio: Path | None,
    work_dir: Path,
    ffmpeg_path: str,
    settings: WorkerSettings,
) -> Path:
    normal_output = work_dir / "telegram_video.mp4"
    _run_ffmpeg(
        source_video=source_video,
        source_audio=source_audio,
        output=normal_output,
        ffmpeg_path=ffmpeg_path,
        compact=False,
        timeout_seconds=settings.download_timeout_seconds,
    )
    if normal_output.stat().st_size <= settings.max_upload_bytes:
        return normal_output

    compact_output = work_dir / "telegram_video_compact.mp4"
    _run_ffmpeg(
        source_video=source_video,
        source_audio=source_audio,
        output=compact_output,
        ffmpeg_path=ffmpeg_path,
        compact=True,
        timeout_seconds=settings.download_timeout_seconds,
    )
    if compact_output.stat().st_size > settings.max_upload_bytes:
        raise PermanentJobError("video Telegram upload limitidan katta")
    return compact_output


async def _mark_sent_with_retry(
    queue: VideoQueueService,
    job_id: int,
    sent_message_id: int,
    worker_id: str,
) -> None:
    last_error: Exception | None = None
    for attempt in range(1, 13):
        try:
            await asyncio.to_thread(queue.mark_sent, job_id, sent_message_id, worker_id)
            return
        except Exception as exc:  # pragma: no cover - requires DB outage
            last_error = exc
            logger.exception("mark_sent failed job_id=%s attempt=%s", job_id, attempt)
            await asyncio.sleep(min(2**attempt, 30))
    raise RuntimeError("sent video could not be committed to database") from last_error


async def _lease_heartbeat(
    queue: VideoQueueService,
    job_id: int,
    worker_id: str,
    lease_timeout_minutes: int,
) -> None:
    interval = max(10.0, min(60.0, lease_timeout_minutes * 20.0))
    while True:
        await asyncio.sleep(interval)
        renewed = await asyncio.to_thread(queue.renew_lease, job_id, worker_id)
        if not renewed:
            raise RuntimeError("video job lease was lost")


def _raise_if_heartbeat_failed(task: asyncio.Task) -> None:
    if task.done():
        task.result()


async def _process_job(
    bot: Bot,
    queue: VideoQueueService,
    job: VideoJob,
    ffmpeg_path: str,
    settings: WorkerSettings,
) -> None:
    logger.info(
        "Processing video job_id=%s source=%s attempt=%s chat_id=%s",
        job.id,
        job.source,
        job.attempts,
        job.chat_id,
    )

    heartbeat = asyncio.create_task(
        _lease_heartbeat(
            queue,
            job.id,
            settings.worker_id,
            settings.lease_timeout_minutes,
        )
    )
    try:
        with tempfile.TemporaryDirectory(prefix=f"lola-video-{job.id}-") as temp_dir:
            work_dir = Path(temp_dir)
            source_video, source_audio = await asyncio.to_thread(
                _download_source,
                job,
                work_dir,
                ffmpeg_path,
                settings,
            )
            _raise_if_heartbeat_failed(heartbeat)
            prepared = await asyncio.to_thread(
                _prepare_telegram_video,
                source_video,
                source_audio,
                work_dir,
                ffmpeg_path,
                settings,
            )

            _raise_if_heartbeat_failed(heartbeat)
            sent = await bot.send_video(
                chat_id=job.chat_id,
                message_thread_id=job.message_thread_id,
                video=FSInputFile(prepared, filename="video.mp4"),
                supports_streaming=True,
            )
            try:
                await _mark_sent_with_retry(
                    queue,
                    job.id,
                    sent.message_id,
                    settings.worker_id,
                )
            except Exception:
                # If delivery cannot be recorded, remove the just-sent video so
                # a later lease retry cannot leave a duplicate in the group.
                try:
                    await bot.delete_message(
                        chat_id=job.chat_id,
                        message_id=sent.message_id,
                    )
                except Exception:
                    logger.exception(
                        "Could not compensate uncommitted video job_id=%s sent_message_id=%s",
                        job.id,
                        sent.message_id,
                    )
                raise

            try:
                await bot.delete_message(chat_id=job.chat_id, message_id=job.message_id)
            except Exception:
                # The video is already delivered and marked sent, so never retry
                # only because the original link could not be deleted.
                logger.exception(
                    "Video sent but original link could not be deleted job_id=%s chat_id=%s message_id=%s",
                    job.id,
                    job.chat_id,
                    job.message_id,
                )

            logger.info(
                "Video job complete job_id=%s sent_message_id=%s",
                job.id,
                sent.message_id,
            )
    except PermanentJobError as exc:
        logger.warning("Video job ignored job_id=%s reason=%s", job.id, exc)
        try:
            await asyncio.to_thread(
                queue.mark_ignored,
                job.id,
                str(exc),
                settings.worker_id,
            )
        except Exception:
            logger.exception("Could not mark ignored video job_id=%s", job.id)
    except Exception as exc:
        logger.exception("Video job failed job_id=%s source=%s", job.id, job.source)
        await asyncio.to_thread(
            queue.mark_failed,
            job.id,
            str(exc),
            attempts=job.attempts,
            max_attempts=settings.max_attempts,
            retry_delay_seconds=settings.retry_delay_seconds,
            worker_id=settings.worker_id,
        )
    finally:
        heartbeat.cancel()
        with suppress(asyncio.CancelledError, Exception):
            await heartbeat


async def run_worker() -> None:
    _load_environment()
    settings = WorkerSettings.from_env()
    ffmpeg_path = _resolve_ffmpeg()

    queue = VideoQueueService(settings.database_url)
    await asyncio.to_thread(queue.init_db)

    session = AiohttpSession(timeout=settings.upload_timeout_seconds)
    bot = Bot(token=settings.telegram_bot_token, session=session)
    try:
        me = await bot.get_me()
        logger.info(
            "Lola video worker started worker_id=%s bot=@%s",
            settings.worker_id,
            me.username or me.id,
        )

        while True:
            try:
                job = await asyncio.to_thread(
                    queue.claim_next,
                    settings.worker_id,
                    settings.lease_timeout_minutes,
                    settings.max_attempts,
                )
            except Exception:
                logger.exception("Video queue claim failed")
                await asyncio.sleep(max(settings.poll_seconds, 10.0))
                continue

            if job is None:
                await asyncio.sleep(settings.poll_seconds)
                continue

            await _process_job(bot, queue, job, ffmpeg_path, settings)
    finally:
        await bot.session.close()


def main() -> None:
    logging.basicConfig(
        level=logging.INFO,
        format="%(asctime)s | %(levelname)s | %(name)s | %(message)s",
    )
    try:
        asyncio.run(run_worker())
    except KeyboardInterrupt:
        logger.info("Lola video worker stopped")


if __name__ == "__main__":
    main()
