"""YouTube transcript client: youtube-transcript-api + yt-dlp fallback."""

from __future__ import annotations

import logging
import re

from research_mcp.clients.http import APIError
from research_mcp.models.video import Transcript, TranscriptSegment, VideoMetadata

logger = logging.getLogger(__name__)


def extract_video_id(url_or_id: str) -> str:
    """Extract video ID from various YouTube URL formats or bare ID."""
    url_or_id = url_or_id.strip()

    # Already a bare ID
    if re.match(r"^[\w-]{11}$", url_or_id):
        return url_or_id

    # Standard URL patterns
    patterns = [
        r"(?:youtube\.com/watch\?.*v=)([\w-]{11})",
        r"(?:youtu\.be/)([\w-]{11})",
        r"(?:youtube\.com/shorts/)([\w-]{11})",
        r"(?:youtube\.com/embed/)([\w-]{11})",
    ]
    for pattern in patterns:
        match = re.search(pattern, url_or_id)
        if match:
            return match.group(1)

    raise APIError(f"Could not extract video ID from: {url_or_id}", source="youtube")


class YouTubeClient:

    async def get_transcript(self, video_url_or_id: str, language: str = "en") -> Transcript:
        """Get transcript using fallback chain."""
        video_id = extract_video_id(video_url_or_id)

        # Try youtube-transcript-api first
        try:
            return await self._get_via_transcript_api(video_id, language)
        except (APIError, ImportError) as e:
            logger.info("youtube-transcript-api failed: %s, trying yt-dlp", e)
        except Exception as e:
            logger.warning("youtube-transcript-api unexpected error: %s", e, exc_info=True)

        # Try yt-dlp
        try:
            return await self._get_via_ytdlp(video_id, language)
        except (APIError, ImportError) as e:
            logger.info("yt-dlp subtitle extraction failed: %s", e)
        except Exception as e:
            logger.warning("yt-dlp unexpected error: %s", e, exc_info=True)

        raise APIError(
            f"No transcript available for video {video_id}. "
            "Whisper transcription may be used as a last resort if configured.",
            source="youtube",
        )

    async def _get_via_transcript_api(self, video_id: str, language: str) -> Transcript:
        """Primary method: youtube-transcript-api."""
        import asyncio

        from youtube_transcript_api import YouTubeTranscriptApi

        def _fetch():
            from youtube_transcript_api import NoTranscriptFound

            ytt_api = YouTubeTranscriptApi()
            transcript_list = ytt_api.list(video_id)

            # Try manual transcripts first, then auto-generated
            try:
                transcript = transcript_list.find_transcript([language])
            except NoTranscriptFound:
                try:
                    transcript = transcript_list.find_transcript(["en"])
                except NoTranscriptFound:
                    # Fall back to any available transcript
                    transcript = transcript_list.find_transcript(
                        [t.language_code for t in transcript_list]
                    )

            fetched = transcript.fetch()
            return fetched, transcript.language_code, transcript.is_generated

        fetched, lang_code, is_generated = await asyncio.to_thread(_fetch)

        segments = [
            TranscriptSegment(
                text=item.text,
                start=item.start,
                duration=item.duration,
            )
            for item in fetched
        ]

        return Transcript(
            video_id=video_id,
            language=lang_code,
            segments=segments,
            is_auto_generated=is_generated,
            source_method="youtube_api",
        )

    async def _get_via_ytdlp(self, video_id: str, language: str) -> Transcript:
        """Fallback: yt-dlp subtitle extraction."""
        import asyncio
        import json

        import yt_dlp

        def _fetch():
            opts = {
                "skip_download": True,
                "writesubtitles": True,
                "writeautomaticsub": True,
                "subtitleslangs": [language, "en"],
                "subtitlesformat": "json3",
                "quiet": True,
                "no_warnings": True,
            }
            with yt_dlp.YoutubeDL(opts) as ydl:
                info = ydl.extract_info(f"https://www.youtube.com/watch?v={video_id}", download=False)
                return info

        info = await asyncio.to_thread(_fetch)

        # Try manual subtitles first, then auto
        subs = info.get("subtitles", {})
        auto_subs = info.get("automatic_captions", {})
        is_auto = False

        sub_data = None
        actual_lang = language

        for lang in [language, "en"]:
            if lang in subs:
                for fmt in subs[lang]:
                    if fmt.get("ext") == "json3":
                        sub_data = fmt
                        actual_lang = lang
                        break
            if sub_data:
                break

        if not sub_data:
            is_auto = True
            for lang in [language, "en"]:
                if lang in auto_subs:
                    for fmt in auto_subs[lang]:
                        if fmt.get("ext") == "json3":
                            sub_data = fmt
                            actual_lang = lang
                            break
                if sub_data:
                    break

        if not sub_data:
            raise APIError(f"No subtitles found via yt-dlp for {video_id}", source="youtube")

        # Fetch the subtitle content
        import httpx

        async with httpx.AsyncClient() as client:
            resp = await client.get(sub_data["url"])
            if not resp.is_success:
                raise APIError(f"Failed to fetch subtitles (HTTP {resp.status_code})", source="youtube")
            content = resp.json()

        segments = []
        for event in content.get("events", []):
            text_parts = []
            for seg in event.get("segs", []):
                if seg.get("utf8"):
                    text_parts.append(seg["utf8"])
            text = "".join(text_parts).strip()
            if text and text != "\n":
                segments.append(
                    TranscriptSegment(
                        text=text,
                        start=event.get("tStartMs", 0) / 1000.0,
                        duration=event.get("dDurationMs", 0) / 1000.0,
                    )
                )

        return Transcript(
            video_id=video_id,
            language=actual_lang,
            segments=segments,
            is_auto_generated=is_auto,
            source_method="yt_dlp",
        )

    async def get_metadata(self, video_url_or_id: str) -> VideoMetadata:
        """Extract video metadata via yt-dlp."""
        import asyncio

        import yt_dlp

        video_id = extract_video_id(video_url_or_id)

        def _fetch():
            opts = {
                "skip_download": True,
                "quiet": True,
                "no_warnings": True,
            }
            with yt_dlp.YoutubeDL(opts) as ydl:
                return ydl.extract_info(f"https://www.youtube.com/watch?v={video_id}", download=False)

        info = await asyncio.to_thread(_fetch)

        return VideoMetadata(
            video_id=video_id,
            title=info.get("title", ""),
            author=info.get("uploader", info.get("channel", "")),
            duration_seconds=info.get("duration"),
            description=info.get("description"),
            publish_date=info.get("upload_date"),
            view_count=info.get("view_count"),
            url=f"https://www.youtube.com/watch?v={video_id}",
        )
