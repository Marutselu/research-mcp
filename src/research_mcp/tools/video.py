"""YouTube / Video tools (Group 3: video)."""

from __future__ import annotations

from fastmcp import Context, FastMCP

from research_mcp.cache import Cache
from research_mcp.models.search import PaginatedContent
from research_mcp.models.video import VideoMetadata
from research_mcp.services.video import VideoService


def register_video_tools(mcp: FastMCP) -> None:

    @mcp.tool(tags={"video"})
    async def research_youtube_transcript(
        video_url_or_id: str,
        language: str = "en",
        include_timestamps: bool = False,
        start_index: int = 0,
        max_length: int = 20000,
        bypass_cache: bool = False,
        ctx: Context = None,
    ) -> PaginatedContent:
        """Extract transcript from a YouTube video.

        Fallback chain: YouTube transcript API -> yt-dlp subtitles -> faster-whisper audio transcription.
        Auto-caption noise ([Music], [Applause], etc.) is stripped. Output is cleaned of excessive whitespace.

        Args:
            video_url_or_id: YouTube URL (youtube.com/watch?v=..., youtu.be/..., shorts/...) or video ID.
            language: Preferred transcript language code (e.g., 'en', 'ja').
            include_timestamps: Include sparse timestamps (every 30s) in the output. Default false to save tokens.
            start_index: Character offset for pagination.
            max_length: Maximum characters to return.
            bypass_cache: Skip cache.
        """
        cache: Cache = ctx.lifespan_context["cache"]
        service: VideoService = ctx.lifespan_context["video_service"]
        config = ctx.lifespan_context["config"]

        cache_key = cache.make_key("research_youtube_transcript", {
            "video": video_url_or_id, "language": language, "timestamps": include_timestamps,
        })

        if not bypass_cache:
            cached = cache.get(cache_key)
            if cached:
                return _paginate_text(cached["text"], start_index, max_length)

        transcript = await service.get_transcript(video_url_or_id, language=language)

        if include_timestamps:
            text = transcript.to_timestamped_text()
        else:
            text = transcript.full_text

        # Prepend metadata
        metadata_header = f"Video ID: {transcript.video_id}\nLanguage: {transcript.language}\nSource: {transcript.source_method}\n\n"
        full_text = metadata_header + text

        cache.set(
            cache_key, {"text": full_text}, ttl_seconds=config.cache.ttl.transcripts, source="youtube_transcript"
        )
        return _paginate_text(full_text, start_index, max_length)

    @mcp.tool(tags={"video"})
    async def research_video_metadata(
        video_url_or_id: str,
        ctx: Context = None,
    ) -> VideoMetadata:
        """Get metadata for a YouTube video (title, author, duration, etc.) without downloading.

        Args:
            video_url_or_id: YouTube URL or video ID.
        """
        service: VideoService = ctx.lifespan_context["video_service"]
        return await service.get_metadata(video_url_or_id)


def _paginate_text(text: str, start_index: int, max_length: int) -> PaginatedContent:
    total = len(text)
    chunk = text[start_index : start_index + max_length]
    return PaginatedContent(
        content=chunk,
        total_length=total,
        start_index=start_index,
        retrieved_length=len(chunk),
        is_truncated=start_index + len(chunk) < total,
        has_more=start_index + len(chunk) < total,
    )
