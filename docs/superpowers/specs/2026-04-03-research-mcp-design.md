# Research MCP Server — Design Spec

**Date:** 2026-04-03
**Status:** Approved for implementation

---

## Context

A self-hosted MCP server for research workflows, designed to work with both OpenWebUI (Streamable HTTP transport) and OpenCode (stdio transport). The server provides tools for web search, academic paper discovery, YouTube transcript extraction, GitHub and documentation search, PDF extraction via Docling, Wikipedia, and a local vector index for saving and retrieving research content.

The design draws heavily on existing open-source MCP servers:
- **Scrapling** (D4Vinci/Scrapling) — 3-tier scraping pattern
- **paper-search-mcp** (openags/paper-search-mcp) — academic platform connector pattern, concurrent fan-out, download-with-fallback chain
- **scholar-search-mcp** (Silung/scholar-search-mcp) — normalized paper schema, fallback chains
- **mcp-server-searxng** (kevinwatt) — instance fallback, category support
- **scrapling-fetch-mcp** (cyberchitta) — pagination pattern

---

## Architecture: Three Layers

```
Client (OpenWebUI / OpenCode)
    │ HTTP or stdio
    ▼
tools/          ← MCP registration: validates input, checks cache, calls service, formats output
    │
    ▼
services/       ← Orchestration: fallback chains, fan-out, normalization, deduplication
    │
    ▼
clients/        ← API wrappers: one per external API, pure I/O, typed exceptions
```

---

## Project Structure

```
research-mcp/
├── pyproject.toml
├── config.example.yaml
├── src/research_mcp/
│   ├── __init__.py
│   ├── __main__.py               # CLI entry: --transport, --host, --port, --config
│   ├── server.py                 # FastMCP instance, lifespan, tag-based group enable/disable
│   ├── config.py                 # Pydantic Settings + YAML loader, env var merging
│   ├── cache.py                  # SQLite TTL cache, SHA-256 key hashing
│   │
│   ├── models/
│   │   ├── search.py             # NormalizedResult, SearchResponse
│   │   ├── academic.py           # Paper, Author
│   │   ├── video.py              # Transcript, VideoMetadata
│   │   ├── document.py           # ExtractedDocument, Table
│   │   └── index.py              # IndexEntry, SearchHit
│   │
│   ├── clients/
│   │   ├── http.py               # Shared httpx.AsyncClient, retry/backoff (tenacity)
│   │   ├── searxng.py
│   │   ├── scrapling_client.py   # 3-tier facade: Fetcher → DynamicFetcher → StealthyFetcher
│   │   ├── semantic_scholar.py
│   │   ├── arxiv.py
│   │   ├── crossref.py
│   │   ├── core_api.py
│   │   ├── pubmed.py             # PubMed E-utilities
│   │   ├── europepmc.py
│   │   ├── openalex.py
│   │   ├── biorxiv.py            # bioRxiv + medRxiv
│   │   ├── doaj.py
│   │   ├── dblp.py
│   │   ├── pmc.py                # PubMed Central (OA full text)
│   │   ├── unpaywall.py          # DOI → OA PDF resolver
│   │   ├── youtube.py            # youtube-transcript-api + yt-dlp
│   │   ├── whisper.py            # faster-whisper (optional import)
│   │   ├── github.py             # GitHub REST API
│   │   ├── docling.py            # HTTP to Docling Serve
│   │   ├── ollama.py             # Ollama embedding API
│   │   └── wikipedia.py          # Wikipedia REST API
│   │
│   ├── services/
│   │   ├── web_search.py         # SearXNG + domain filtering
│   │   ├── scraper.py            # 3-tier escalation, content → markdown, pagination
│   │   ├── academic_search.py    # Fan-out across 13 sources, dedup, DOI resolution
│   │   ├── video.py              # Transcript fallback chain
│   │   ├── github_docs.py        # GitHub search + file read + package/docs search
│   │   ├── document.py           # Docling extraction + article cleanup
│   │   ├── wiki.py               # Wikipedia search + article retrieval
│   │   └── vector_index.py       # sqlite-vec CRUD + Ollama embedding
│   │
│   └── tools/
│       ├── __init__.py           # register_tools(): check dep availability, disable missing groups
│       ├── web.py                # group: web_search
│       ├── academic.py           # group: academic
│       ├── video.py              # group: video
│       ├── github_docs.py        # group: github_docs
│       ├── document.py           # group: document
│       ├── wiki.py               # group: wikipedia
│       └── index.py              # group: vector_index
│
└── tests/
    ├── conftest.py
    ├── clients/
    ├── services/
    └── tools/
```

---

## Tool Inventory (22 tools, 7 groups)

All tools are prefixed `research_` to avoid name collisions. All content-returning tools support `start_index` + `max_length` pagination. All search tools support `bypass_cache: bool = False`.

### Group 1: `web_search`

| Tool | Key Parameters | Returns |
|---|---|---|
| `research_web_search` | `query, categories=["general"], time_range, max_results=10` | `SearchResponse` |
| `research_scrape_url` | `url, tier="auto", extract_markdown=True, start_index=0, max_length=20000` | Markdown text + pagination metadata |
| `research_forum_search` | `query, site` (reddit/stackoverflow/stackexchange/hackernews), `max_results=10` | `SearchResponse` + extracted thread content |

**Scraping tiers (auto-escalation on failure):**
1. `basic` — `scrapling.Fetcher` (curl_cffi, TLS impersonation, fast HTTP)
2. `dynamic` — `scrapling.DynamicFetcher` (Playwright Chromium, renders JS)
3. `stealth` — `scrapling.StealthyFetcher` (Camoufox, anti-bot fingerprinting, Cloudflare bypass)

### Group 2: `academic`

| Tool | Key Parameters | Returns |
|---|---|---|
| `research_academic_search` | `query, sources=config.default_sources, year_min, year_max, open_access_only=False, max_results=10` | `list[Paper]` deduplicated |
| `research_paper_details` | `paper_id` (DOI/arXiv/S2/PMID/PMCID) | `Paper` with full metadata |
| `research_paper_citations` | `paper_id, direction` (cited_by/references), `max_results=20` | `list[Paper]` |
| `research_resolve_doi` | `doi` | `Paper` + OA PDF URL via Crossref + Unpaywall |
| `research_download_paper` | `paper_id_or_doi, output_format="markdown"` | Extracted paper text (via Docling) using fallback chain |

**Academic sources (13):**
- Semantic Scholar, arXiv, Crossref, CORE, PubMed, Europe PMC
- OpenAlex, bioRxiv, medRxiv, DOAJ, dblp, PMC, Unpaywall

**Fan-out pattern:** All selected sources queried concurrently via `asyncio.gather`. Results merged and deduplicated: DOI as primary key, normalized title similarity as fallback.

**Download-with-fallback chain:** source-native PDF → CORE full text → Europe PMC → PMC → Unpaywall → report unavailable.

Note: `research_download_paper` belongs to the `academic` group (not `document`). If Docling Serve is unreachable or the `document` group is disabled, the tool returns the best OA PDF URL it found rather than extracted text, with a clear note that extraction is unavailable.

### Group 3: `video`

| Tool | Key Parameters | Returns |
|---|---|---|
| `research_youtube_transcript` | `video_url_or_id, language="en", start_index=0, max_length=20000` | Transcript text with timestamps, paginated |
| `research_video_metadata` | `video_url_or_id` | `VideoMetadata` (title, author, duration, description, publish_date) |

**Transcript fallback chain:** youtube-transcript-api → yt-dlp subtitle extraction → faster-whisper audio transcription.

### Group 4: `github_docs`

| Tool | Key Parameters | Returns |
|---|---|---|
| `research_github_search` | `query, search_type` (repos/code/issues/discussions), `language, max_results=10` | `SearchResponse` |
| `research_github_read_file` | `owner, repo, path="README.md", ref` | File content as markdown |
| `research_package_docs` | `package_name, registry` (pypi/npm), `query` | `SearchResponse` + scraped doc content |
| `research_docs_search` | `query, site` (optional domain restriction) | `SearchResponse` |

### Group 5: `document`

| Tool | Key Parameters | Returns |
|---|---|---|
| `research_extract_document` | `url_or_path, extract_tables=True, extract_images=False, start_index=0, max_length=20000` | `ExtractedDocument` (markdown + tables) |
| `research_extract_article` | `url, start_index=0, max_length=20000` | Clean article text as markdown |

`research_extract_document` sends files to Docling Serve for full layout-aware extraction (tables, figures, headings). `research_extract_article` uses Scrapling + readability-style content extraction to isolate the main article body from a web page (strips nav, ads, sidebars) — no Docling needed.

`research_extract_document` calls the user's running **Docling Serve** instance at `config.services.docling_url`. If Docling is unreachable, only `research_extract_document` is disabled (not the whole group). `research_extract_article` works independently using Scrapling + readability extraction.

### Group 6: `wikipedia`

| Tool | Key Parameters | Returns |
|---|---|---|
| `research_wiki_search` | `query, max_results=5` | `SearchResponse` |
| `research_wiki_article` | `title, sections, start_index=0, max_length=20000` | Article text as markdown, paginated |

### Group 7: `vector_index`

| Tool | Key Parameters | Returns | RO? |
|---|---|---|---|
| `research_index_save` | `content, title, url, source_type` (paper/transcript/webpage/document), `tags=[]` | Entry ID | Write |
| `research_index_search` | `query, source_type, tags, top_k=10` | `list[SearchHit]` with scores and snippets | Read |
| `research_index_list` | `source_type, limit=20, offset=0` | Paginated `list[IndexEntry]` | Read |
| `research_index_delete` | `entry_id` | Confirmation | Write |

Uses **sqlite-vec** (SQLite extension) for vector similarity. Embeddings computed via **Ollama** (user's existing instance). Configurable model via `ollama_embed_model` (default: `nomic-embed-text`, 768 dims).

---

## Configuration System

### File: `config.yaml` (non-secrets)

```yaml
groups:
  web_search: true
  academic: true
  video: true
  github_docs: true
  document: false        # Requires Docling Serve
  wikipedia: true
  vector_index: false    # Requires Ollama

services:
  searxng_url: "http://localhost:8080"
  docling_url: "http://localhost:5001"
  ollama_url: "http://localhost:11434"
  ollama_embed_model: "nomic-embed-text"

transport: "http"              # "stdio" | "http" (http = Streamable HTTP)
host: "127.0.0.1"
port: 8000

scraping:
  default_tier: "basic"
  auto_escalate: true
  timeout_seconds: 30
  max_content_length: 50000

academic:
  default_sources: ["semantic_scholar", "arxiv", "crossref", "openalex"]
  max_results_per_source: 10

cache:
  enabled: true
  db_path: "~/.research-mcp/cache.db"
  ttl:
    search_results: 1800       # 30 min (SearXNG, GitHub search)
    web_pages: 3600            # 1 hour
    academic: 86400            # 24 hours
    transcripts: 604800        # 7 days
    embeddings: 2592000        # 30 days

vector_index:
  db_path: "~/.research-mcp/index.db"
  embedding_dimensions: 768

domains:
  blocklist: []
  allowlist: []
```

### Environment Variables (secrets, prefix `RESEARCH_MCP_`)

| Variable | Required | Notes |
|---|---|---|
| `RESEARCH_MCP_GITHUB_PAT` | Recommended | 60→5000 req/hr |
| `RESEARCH_MCP_SEMANTIC_SCHOLAR_API_KEY` | Optional | Improves rate limits |
| `RESEARCH_MCP_CORE_API_KEY` | Recommended | Free at core.ac.uk |
| `RESEARCH_MCP_PUBMED_API_KEY` | Optional | 3→10 req/sec |
| `RESEARCH_MCP_CROSSREF_MAILTO` | Optional | Polite pool |
| `RESEARCH_MCP_UNPAYWALL_EMAIL` | Required for Unpaywall | Any valid email |
| `RESEARCH_MCP_DOAJ_API_KEY` | Optional | Free |

---

## Caching Strategy

SQLite with TTL (`~/.research-mcp/cache.db`, WAL mode):

```sql
CREATE TABLE cache (
    key TEXT PRIMARY KEY,          -- SHA-256(tool_name + sorted params)
    value BLOB,                    -- zlib-compressed JSON
    created_at REAL,               -- Unix timestamp
    ttl_seconds INTEGER,
    source TEXT
);
```

| Content Type | Default TTL |
|---|---|
| SearXNG results | 30 min |
| Web pages | 1 hour |
| Academic metadata | 24 hours |
| Transcripts | 7 days |
| Embeddings | 30 days |

Eviction: `DELETE WHERE created_at + ttl_seconds < unixepoch()` — runs on startup and hourly.
All tools accept `bypass_cache: bool = False`.

---

## Shared Models

### `NormalizedResult` (in `models/search.py`)
```python
class NormalizedResult(BaseModel):
    title: str
    url: str | None
    snippet: str
    source: str          # "searxng", "semantic_scholar", "github", etc.
    content_type: str    # "webpage", "paper", "repo", "video", etc.
    date: str | None     # ISO 8601
    score: float | None
    metadata: dict       # Source-specific extras
```

### `Paper` (in `models/academic.py`)
```python
class Paper(BaseModel):
    title: str
    authors: list[str]
    abstract: str | None
    doi: str | None
    arxiv_id: str | None
    year: int | None
    venue: str | None
    citation_count: int | None
    url: str | None
    pdf_url: str | None
    is_open_access: bool | None
    source: str
    external_ids: dict[str, str] = {}
```

---

## Transport

Same codebase serves both transports:

```bash
# OpenCode (stdio)
python -m research_mcp --transport stdio

# OpenWebUI (Streamable HTTP)
python -m research_mcp --transport http --port 8000
```

FastMCP's `transport="http"` implements the Streamable HTTP protocol that OpenWebUI expects.

For using both simultaneously: run two separate processes sharing the same config, cache DB, and vector index DB. SQLite WAL mode handles concurrent reads.

**OpenCode config:**
```json
{
  "mcp": {
    "research": {
      "type": "local",
      "command": ["python", "-m", "research_mcp", "--transport", "stdio"],
      "environment": {"RESEARCH_MCP_GITHUB_PAT": "..."}
    }
  }
}
```

**OpenWebUI config:** Admin Settings → External Tools → Add Server → Type: MCP (Streamable HTTP) → URL: `http://localhost:8000/mcp`

---

## Dependencies

```toml
[project]
requires-python = ">=3.11"
dependencies = [
    "fastmcp>=3.0",
    "httpx>=0.27",
    "pydantic>=2.0",
    "pydantic-settings>=2.0",
    "pyyaml>=6.0",
    "tenacity>=8.0",
]

[project.optional-dependencies]
web     = ["scrapling>=0.2", "markdownify>=0.14"]
video   = ["youtube-transcript-api>=1.0", "yt-dlp>=2024.0"]
whisper = ["faster-whisper>=1.0"]
index   = ["sqlite-vec>=0.1"]
all     = ["research-mcp[web,video,index]"]

# Install commands:
# pip install "research-mcp[all]"          — everything except Whisper
# pip install "research-mcp[all,whisper]"  — full install
```

Groups with missing optional deps are auto-disabled at startup with a warning rather than crashing.

---

## Error Handling

| Layer | Responsibility |
|---|---|
| **Clients** | Raise typed exceptions: `APIError`, `RateLimitError`, `NotFoundError`, `AuthenticationError` |
| **Services** | Catch client errors, apply fallbacks, log warnings; raise `ServiceError` if all fallbacks fail |
| **Tools** | Catch service errors, return user-friendly error strings; never crash the MCP protocol |
| **Retry** | `tenacity` with exponential backoff; 429s respect `Retry-After` header |
| **API key fallback** | Auto-retry without key on 401/403 (adopted from paper-search-mcp) |

---

## Server Wiring (`server.py`)

```python
def create_server(config: ResearchMCPConfig) -> FastMCP:
    mcp = FastMCP("research_mcp", lifespan=build_lifespan(config))
    register_all_tools(mcp)   # All 22 tools registered with group tags

    # Disable groups turned off in config OR missing dependencies
    disabled = compute_disabled_groups(config)
    if disabled:
        mcp.disable(tags=disabled)
    return mcp
```

Lifespan initializes shared resources: httpx client (connection pooling), SQLite cache, sqlite-vec index, all client and service objects. Tools access services via `ctx.lifespan_context` (FastMCP's direct property, not nested under `request_context`).

---

## Verification Plan

1. **Install**: `pip install -e ".[all,whisper]"` from the project root — should complete without errors.
2. **Config validation**: `python -m research_mcp --validate-config` — should print active groups.
3. **stdio smoke test**: `echo '{"jsonrpc":"2.0","method":"tools/list","id":1}' | python -m research_mcp` — should return all 22 tools.
4. **HTTP smoke test**: Start server in streamable-http mode, call `GET /tools/list` — should return tool list.
5. **Per-group tests**:
   - Web: `research_web_search(query="python asyncio")` — returns results from SearXNG
   - Academic: `research_academic_search(query="attention is all you need")` — returns deduplicated papers from multiple sources
   - Video: `research_youtube_transcript(video_url_or_id="dQw4w9WgXcQ")` — returns transcript
   - GitHub: `research_github_search(query="fastmcp", search_type="repos")` — returns repos
   - Wikipedia: `research_wiki_article(title="Python (programming language)")` — returns article
   - Vector index: `research_index_save(...)` then `research_index_search(...)` — round-trip works
6. **Cache test**: Call same query twice, second call should be faster and return cached result.
7. **Group disable test**: Set `groups.web_search: false` in config, verify web tools absent from tools/list.
8. **OpenWebUI integration**: Add server URL in OpenWebUI admin settings, verify tools appear in chat.
