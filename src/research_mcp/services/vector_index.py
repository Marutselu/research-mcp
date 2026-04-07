"""Vector index service: sqlite-vec + Ollama embeddings."""

from __future__ import annotations

import json
import logging
import sqlite3
import struct
import uuid
from datetime import datetime, timezone
from pathlib import Path

from research_mcp.clients.ollama import OllamaClient
from research_mcp.clients.http import create_http_client
from research_mcp.config import ResearchMCPConfig
from research_mcp.models.index import IndexEntry, SearchHit

logger = logging.getLogger(__name__)


def _serialize_vector(vec: list[float]) -> bytes:
    """Serialize a float vector to bytes for sqlite-vec."""
    return struct.pack(f"{len(vec)}f", *vec)


class VectorIndexService:
    def __init__(self, config: ResearchMCPConfig) -> None:
        self._config = config
        self._ollama = OllamaClient(
            create_http_client(timeout=60.0),
            config.services.ollama_url,
            config.services.ollama_embed_model,
        )
        self._conn: sqlite3.Connection | None = None
        self._dims = config.vector_index.embedding_dimensions

    async def initialize(self) -> None:
        """Create database tables and load sqlite-vec extension."""
        db_path = Path(self._config.vector_index.db_path)
        db_path.parent.mkdir(parents=True, exist_ok=True)

        self._conn = sqlite3.connect(str(db_path), check_same_thread=False)
        self._conn.execute("PRAGMA journal_mode=WAL")

        # Load sqlite-vec extension
        import sqlite_vec

        self._conn.enable_load_extension(True)
        sqlite_vec.load(self._conn)
        self._conn.enable_load_extension(False)

        # Create metadata table
        self._conn.execute(
            """
            CREATE TABLE IF NOT EXISTS entries (
                id TEXT PRIMARY KEY,
                title TEXT NOT NULL,
                url TEXT,
                source_type TEXT NOT NULL,
                tags TEXT NOT NULL DEFAULT '[]',
                content TEXT NOT NULL,
                created_at TEXT NOT NULL
            )
            """
        )

        # Create vector table
        self._conn.execute(
            f"""
            CREATE VIRTUAL TABLE IF NOT EXISTS vec_entries USING vec0(
                entry_id TEXT,
                embedding float[{self._dims}]
            )
            """
        )

        self._conn.commit()
        logger.info("Vector index initialized at %s", db_path)

    def close(self) -> None:
        if self._conn:
            self._conn.close()
            self._conn = None

    async def save(
        self,
        content: str,
        title: str,
        url: str | None = None,
        source_type: str = "webpage",
        tags: list[str] | None = None,
    ) -> str:
        """Embed and store content in the vector index."""
        entry_id = str(uuid.uuid4())
        now = datetime.now(timezone.utc).isoformat()

        # Compute embedding for the content (truncate to ~2000 chars for embedding)
        embed_text = f"{title}\n\n{content[:2000]}"
        embedding = await self._ollama.embed(embed_text)

        # Store metadata
        self._conn.execute(
            "INSERT INTO entries (id, title, url, source_type, tags, content, created_at) VALUES (?, ?, ?, ?, ?, ?, ?)",
            (entry_id, title, url, source_type, json.dumps(tags or []), content, now),
        )

        # Store embedding
        self._conn.execute(
            "INSERT INTO vec_entries (entry_id, embedding) VALUES (?, ?)",
            (entry_id, _serialize_vector(embedding)),
        )

        self._conn.commit()
        return entry_id

    async def search(
        self,
        query: str,
        source_type: str | None = None,
        tags: list[str] | None = None,
        top_k: int = 10,
    ) -> list[SearchHit]:
        """Semantic search over stored content."""
        query_embedding = await self._ollama.embed(query)

        # KNN search
        rows = self._conn.execute(
            """
            SELECT entry_id, distance
            FROM vec_entries
            WHERE embedding MATCH ?
            ORDER BY distance
            LIMIT ?
            """,
            (_serialize_vector(query_embedding), top_k * 3),  # Over-fetch for filtering
        ).fetchall()

        hits = []
        for entry_id, distance in rows:
            # Fetch metadata
            entry_row = self._conn.execute(
                "SELECT id, title, url, source_type, tags, content, created_at FROM entries WHERE id = ?",
                (entry_id,),
            ).fetchone()

            if not entry_row:
                continue

            eid, etitle, eurl, esource_type, etags, econtent, ecreated = entry_row

            # Apply filters
            if source_type and esource_type != source_type:
                continue

            entry_tags = json.loads(etags) if etags else []
            if tags and not any(t in entry_tags for t in tags):
                continue

            # Build snippet
            snippet = econtent[:200] + "..." if len(econtent) > 200 else econtent

            hits.append(
                SearchHit(
                    entry=IndexEntry(
                        id=eid,
                        title=etitle,
                        url=eurl,
                        source_type=esource_type,
                        tags=entry_tags,
                        created_at=ecreated,
                        content_preview=snippet,
                    ),
                    score=1.0 - distance,  # Convert distance to similarity
                    snippet=snippet,
                )
            )

            if len(hits) >= top_k:
                break

        return hits

    async def list_entries(
        self,
        source_type: str | None = None,
        limit: int = 20,
        offset: int = 0,
    ) -> list[IndexEntry]:
        """List stored entries with optional filtering."""
        if source_type:
            rows = self._conn.execute(
                "SELECT id, title, url, source_type, tags, content, created_at FROM entries WHERE source_type = ? ORDER BY created_at DESC LIMIT ? OFFSET ?",
                (source_type, limit, offset),
            ).fetchall()
        else:
            rows = self._conn.execute(
                "SELECT id, title, url, source_type, tags, content, created_at FROM entries ORDER BY created_at DESC LIMIT ? OFFSET ?",
                (limit, offset),
            ).fetchall()

        entries = []
        for eid, etitle, eurl, esource_type, etags, econtent, ecreated in rows:
            entries.append(
                IndexEntry(
                    id=eid,
                    title=etitle,
                    url=eurl,
                    source_type=esource_type,
                    tags=json.loads(etags) if etags else [],
                    created_at=ecreated,
                    content_preview=econtent[:200] if econtent else None,
                )
            )

        return entries

    async def delete(self, entry_id: str) -> None:
        """Remove an entry from both metadata and vector tables."""
        self._conn.execute("DELETE FROM entries WHERE id = ?", (entry_id,))
        self._conn.execute("DELETE FROM vec_entries WHERE entry_id = ?", (entry_id,))
        self._conn.commit()
