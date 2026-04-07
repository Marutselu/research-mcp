"""CLI entry point for the research MCP server."""

from __future__ import annotations

import argparse
import logging
import sys


def main() -> None:
    parser = argparse.ArgumentParser(
        prog="research-mcp",
        description="Research MCP Server — web search, academic papers, video transcripts, and more.",
    )
    parser.add_argument(
        "--transport",
        choices=["stdio", "http"],
        default=None,
        help="Transport mode (default: from config, fallback 'http')",
    )
    parser.add_argument("--host", default=None, help="HTTP host (default: from config)")
    parser.add_argument("--port", type=int, default=None, help="HTTP port (default: from config)")
    parser.add_argument("--config", default=None, help="Path to config.yaml")
    parser.add_argument(
        "--validate-config",
        action="store_true",
        help="Validate config and print active groups, then exit",
    )
    args = parser.parse_args()

    from research_mcp.config import load_config

    config = load_config(args.config)

    # CLI args override config
    if args.transport:
        config.transport = args.transport
    if args.host:
        config.host = args.host
    if args.port:
        config.port = args.port

    # Set up logging
    logging.basicConfig(
        level=getattr(logging, config.log_level.upper(), logging.INFO),
        format="%(asctime)s [%(name)s] %(levelname)s: %(message)s",
        stream=sys.stderr,
    )

    if args.validate_config:
        from research_mcp.server import compute_disabled_groups

        disabled = compute_disabled_groups(config)
        groups = config.groups.model_dump()
        print("Research MCP Server — Config Validation")
        print("=" * 40)
        for group, enabled in groups.items():
            if group in disabled:
                status = "DISABLED (missing deps)" if enabled else "DISABLED (config)"
            else:
                status = "ACTIVE"
            print(f"  {group}: {status}")
        print(f"\nTransport: {config.transport}")
        if config.transport == "http":
            print(f"Endpoint: http://{config.host}:{config.port}")
        print(f"Cache: {'enabled' if config.cache.enabled else 'disabled'}")
        return

    from research_mcp.server import create_server

    server = create_server(config)

    if config.transport == "stdio":
        server.run(transport="stdio")
    else:
        server.run(transport="http", host=config.host, port=config.port)


if __name__ == "__main__":
    main()
