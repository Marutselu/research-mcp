"""Video and transcript models."""

from __future__ import annotations

from pydantic import BaseModel


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
        return " ".join(seg.text for seg in self.segments)

    def to_timestamped_text(self) -> str:
        lines = []
        for seg in self.segments:
            mins, secs = divmod(int(seg.start), 60)
            hours, mins = divmod(mins, 60)
            if hours:
                ts = f"{hours}:{mins:02d}:{secs:02d}"
            else:
                ts = f"{mins:02d}:{secs:02d}"
            lines.append(f"[{ts}] {seg.text}")
        return "\n".join(lines)


class VideoMetadata(BaseModel):
    video_id: str
    title: str
    author: str
    duration_seconds: int | None = None
    description: str | None = None
    publish_date: str | None = None
    view_count: int | None = None
    url: str
