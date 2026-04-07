"""Video service: transcript fallback chain, metadata extraction."""

from __future__ import annotations

import logging

from research_mcp.clients.http import ServiceError
from research_mcp.clients.youtube import YouTubeClient
from research_mcp.config import ResearchMCPConfig
from research_mcp.models.video import Transcript, VideoMetadata

logger = logging.getLogger(__name__)


class VideoService:
    def __init__(self, config: ResearchMCPConfig) -> None:
        self._youtube = YouTubeClient()
        self._whisper = None

        # Try to initialize Whisper client if available
        try:
            from research_mcp.clients.whisper import WhisperClient, is_available

            if is_available():
                self._whisper = WhisperClient()
                logger.info("Whisper transcription available as fallback")
        except ImportError:
            logger.info("faster-whisper not installed, Whisper fallback disabled")

    async def get_transcript(self, video_url_or_id: str, language: str = "en") -> Transcript:
        """Get transcript with fallback chain: youtube API -> yt-dlp -> whisper."""
        # Try YouTube transcript methods (includes yt-dlp fallback)
        try:
            return await self._youtube.get_transcript(video_url_or_id, language=language)
        except Exception as e:
            logger.info("YouTube transcript methods exhausted: %s", e)

        # Final fallback: Whisper
        if self._whisper:
            logger.info("Attempting Whisper transcription for %s", video_url_or_id)
            try:
                from research_mcp.clients.youtube import extract_video_id

                video_id = extract_video_id(video_url_or_id)
                return await self._whisper.transcribe_video(video_id, language=language)
            except Exception as e:
                logger.warning("Whisper transcription failed: %s", e)

        raise ServiceError(
            f"No transcript could be obtained for {video_url_or_id}. "
            "Tried: youtube-transcript-api, yt-dlp subtitles"
            + (", faster-whisper" if self._whisper else "")
        )

    async def get_metadata(self, video_url_or_id: str) -> VideoMetadata:
        """Get video metadata."""
        return await self._youtube.get_metadata(video_url_or_id)
