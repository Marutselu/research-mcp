"""faster-whisper local audio transcription client (optional dependency)."""

from __future__ import annotations

import asyncio
import logging
import tempfile

from research_mcp.clients.http import APIError
from research_mcp.models.video import Transcript, TranscriptSegment

logger = logging.getLogger(__name__)


def is_available() -> bool:
    """Check if faster-whisper is installed."""
    try:
        import faster_whisper  # noqa: F401
        return True
    except ImportError:
        return False


class WhisperClient:
    def __init__(self, model_size: str = "base", device: str = "cpu") -> None:
        self._model_size = model_size
        self._device = device
        self._model = None

    def _get_model(self):
        if self._model is None:
            from faster_whisper import WhisperModel
            logger.info("Loading Whisper model '%s' on '%s'...", self._model_size, self._device)
            self._model = WhisperModel(self._model_size, device=self._device, compute_type="int8")
        return self._model

    async def transcribe_video(self, video_id: str, language: str = "en") -> Transcript:
        """Download audio from YouTube and transcribe with Whisper."""
        # Download audio
        audio_path = await self._download_audio(video_id)

        try:
            segments, info = await asyncio.to_thread(
                self._transcribe_file, audio_path, language
            )
        finally:
            import os
            try:
                os.unlink(audio_path)
            except OSError:
                pass

        return Transcript(
            video_id=video_id,
            language=info.language or language,
            segments=segments,
            is_auto_generated=True,
            source_method="whisper",
        )

    async def _download_audio(self, video_id: str) -> str:
        """Download audio from YouTube via yt-dlp."""
        import yt_dlp

        tmp = tempfile.mktemp(suffix=".mp3")

        def _download():
            opts = {
                "format": "bestaudio/best",
                "outtmpl": tmp.replace(".mp3", ".%(ext)s"),
                "postprocessors": [
                    {
                        "key": "FFmpegExtractAudio",
                        "preferredcodec": "mp3",
                        "preferredquality": "128",
                    }
                ],
                "quiet": True,
                "no_warnings": True,
            }
            with yt_dlp.YoutubeDL(opts) as ydl:
                ydl.download([f"https://www.youtube.com/watch?v={video_id}"])

        await asyncio.to_thread(_download)

        # yt-dlp may change the extension
        import glob
        import os

        base = tmp.replace(".mp3", "")
        candidates = glob.glob(f"{base}.*")
        if candidates:
            return candidates[0]

        raise APIError(f"Failed to download audio for {video_id}", source="whisper")

    def _transcribe_file(self, audio_path: str, language: str) -> tuple[list[TranscriptSegment], object]:
        """Run Whisper transcription on an audio file."""
        model = self._get_model()
        segments_iter, info = model.transcribe(audio_path, language=language, beam_size=5)

        segments = []
        for seg in segments_iter:
            segments.append(
                TranscriptSegment(
                    text=seg.text.strip(),
                    start=seg.start,
                    duration=seg.end - seg.start,
                )
            )

        return segments, info
