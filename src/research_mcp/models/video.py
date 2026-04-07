"""Video and transcript models."""

from __future__ import annotations

import re

from pydantic import BaseModel

# Auto-caption artifacts to strip
_NOISE_PATTERNS = re.compile(
    r"\[(?:Music|Applause|Laughter|Silence|Inaudible)\]",
    re.IGNORECASE,
)


class TranscriptSegment(BaseModel):
    text: str
    start: float
    duration: float


class Transcript(BaseModel):
    video_id: str
    language: str
    segments: list[TranscriptSegment]
    is_auto_generated: bool = False
    source_method: str  # "youtube_api", "yt_dlp", "whisper"

    @property
    def full_text(self) -> str:
        """Clean, concatenated transcript text with no timestamps."""
        parts = []
        for seg in self.segments:
            text = _clean_segment(seg.text)
            if text:
                parts.append(text)
        # Join and collapse whitespace
        joined = " ".join(parts)
        joined = re.sub(r"\s{2,}", " ", joined)
        return joined.strip()

    def to_timestamped_text(self, interval_seconds: int = 30) -> str:
        """Transcript with sparse timestamps (one per interval, not per segment).

        Groups segments into time buckets and emits one timestamp per bucket,
        drastically reducing token count vs per-segment timestamps.
        """
        if not self.segments:
            return ""

        lines = []
        current_bucket_start = 0
        current_texts: list[str] = []

        for seg in self.segments:
            text = _clean_segment(seg.text)
            if not text:
                continue

            bucket = int(seg.start // interval_seconds) * interval_seconds

            if bucket > current_bucket_start and current_texts:
                ts = _format_timestamp(current_bucket_start)
                lines.append(f"[{ts}] {' '.join(current_texts)}")
                current_texts = []
                current_bucket_start = bucket

            current_texts.append(text)

        # Flush remaining
        if current_texts:
            ts = _format_timestamp(current_bucket_start)
            lines.append(f"[{ts}] {' '.join(current_texts)}")

        return "\n\n".join(lines)


class VideoMetadata(BaseModel):
    video_id: str
    title: str
    author: str
    duration_seconds: int | None = None
    description: str | None = None
    publish_date: str | None = None
    view_count: int | None = None
    url: str


def _clean_segment(text: str) -> str:
    """Clean a single transcript segment."""
    # Strip noise tags
    text = _NOISE_PATTERNS.sub("", text)
    # Normalize whitespace (newlines, tabs, non-breaking spaces)
    text = text.replace("\xa0", " ").replace("\n", " ").replace("\r", "")
    text = re.sub(r"\s{2,}", " ", text)
    return text.strip()


def _format_timestamp(seconds: int) -> str:
    mins, secs = divmod(seconds, 60)
    hours, mins = divmod(mins, 60)
    if hours:
        return f"{hours}:{mins:02d}:{secs:02d}"
    return f"{mins:02d}:{secs:02d}"
