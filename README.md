# research-mcp

A self-hosted MCP server for research workflows: web search, academic papers, YouTube transcripts, GitHub/docs, document extraction, Wikipedia, and local vector index.

## Install

```bash
pip install "research-mcp[all]"
```

## Usage

```bash
# HTTP mode (for OpenWebUI)
python -m research_mcp --transport http --port 8000

# stdio mode (for OpenCode)
python -m research_mcp --transport stdio
```

See `config.example.yaml` for full configuration options.
