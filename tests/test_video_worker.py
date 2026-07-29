import tempfile
import unittest
from pathlib import Path
from types import SimpleNamespace
from unittest.mock import patch

from app.services.video_queue import VideoJob
from worker.video_worker import WorkerSettings, _process_job


class FakeQueue:
    def __init__(self) -> None:
        self.events: list[str] = []

    def renew_lease(self, job_id: int, worker_id: str) -> bool:
        return True

    def mark_sent(self, job_id: int, sent_message_id: int, worker_id: str) -> None:
        self.events.append("mark_sent")

    def mark_failed(self, job_id: int, error: str, **kwargs) -> None:
        self.events.append("mark_failed")

    def mark_ignored(self, job_id: int, reason: str, worker_id: str) -> None:
        self.events.append("mark_ignored")


class FakeBot:
    def __init__(self, queue: FakeQueue, fail_send: bool = False) -> None:
        self.queue = queue
        self.fail_send = fail_send
        self.send_kwargs = None
        self.deleted: list[int] = []

    async def send_video(self, **kwargs):
        self.queue.events.append("send")
        self.send_kwargs = kwargs
        if self.fail_send:
            raise RuntimeError("upload failed")
        return SimpleNamespace(message_id=777)

    async def delete_message(self, *, chat_id: int, message_id: int) -> None:
        self.queue.events.append(f"delete:{message_id}")
        self.deleted.append(message_id)


class VideoWorkerTest(unittest.IsolatedAsyncioTestCase):
    def setUp(self) -> None:
        self.settings = WorkerSettings(
            telegram_bot_token="test-token",
            database_url="postgresql://example.invalid/db",
            worker_id="test-worker",
            poll_seconds=1,
            max_attempts=3,
            retry_delay_seconds=10,
            lease_timeout_minutes=30,
            max_duration_seconds=600,
            max_upload_bytes=49 * 1024 * 1024,
            download_timeout_seconds=60,
            upload_timeout_seconds=60,
            cookies_file=None,
        )
        self.job = VideoJob(
            id=1,
            chat_id=-1001,
            message_id=123,
            message_thread_id=None,
            user_id=5,
            url="https://youtu.be/example",
            source="youtube",
            attempts=1,
        )

    @staticmethod
    def _fake_download(job, work_dir: Path, ffmpeg_path: str, settings):
        source = work_dir / "source.mp4"
        source.write_bytes(b"video")
        return source, None

    @staticmethod
    def _fake_prepare(source_video, source_audio, work_dir, ffmpeg_path, settings):
        return source_video

    async def test_success_is_captionless_non_reply_and_deletes_link_last(self) -> None:
        queue = FakeQueue()
        bot = FakeBot(queue)
        with patch("worker.video_worker._download_source", self._fake_download), patch(
            "worker.video_worker._prepare_telegram_video", self._fake_prepare
        ):
            await _process_job(bot, queue, self.job, "ffmpeg", self.settings)

        self.assertEqual(queue.events, ["send", "mark_sent", "delete:123"])
        self.assertEqual(bot.deleted, [123])
        self.assertNotIn("caption", bot.send_kwargs)
        self.assertNotIn("reply_to_message_id", bot.send_kwargs)
        self.assertNotIn("reply_parameters", bot.send_kwargs)

    async def test_upload_failure_keeps_original_link_and_stays_silent(self) -> None:
        queue = FakeQueue()
        bot = FakeBot(queue, fail_send=True)
        with patch("worker.video_worker._download_source", self._fake_download), patch(
            "worker.video_worker._prepare_telegram_video", self._fake_prepare
        ):
            await _process_job(bot, queue, self.job, "ffmpeg", self.settings)

        self.assertEqual(queue.events, ["send", "mark_failed"])
        self.assertEqual(bot.deleted, [])


if __name__ == "__main__":
    unittest.main()
