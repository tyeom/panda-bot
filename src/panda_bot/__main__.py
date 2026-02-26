"""CLI entry point for panda-bot."""

from __future__ import annotations

import argparse
import asyncio
import signal
import sys
from pathlib import Path

from panda_bot.app import PandaBotApp
from panda_bot.config import load_config
from panda_bot.log import setup_logging


def main() -> None:
    parser = argparse.ArgumentParser(
        prog="panda-bot",
        description="Multi-messenger bot platform with Claude AI integration",
    )
    subparsers = parser.add_subparsers(dest="command", help="Available commands")

    # start command
    start_parser = subparsers.add_parser("start", help="Start the bot")
    start_parser.add_argument(
        "-c", "--config", default="config.yaml", help="Path to config file"
    )
    start_parser.add_argument(
        "-e", "--env", default=".env", help="Path to .env file"
    )

    # config-check command
    check_parser = subparsers.add_parser("config-check", help="Validate configuration")
    check_parser.add_argument(
        "-c", "--config", default="config.yaml", help="Path to config file"
    )
    check_parser.add_argument(
        "-e", "--env", default=".env", help="Path to .env file"
    )

    # model-info command
    model_parser = subparsers.add_parser("model-info", help="Show AI model info per bot")
    model_parser.add_argument(
        "-c", "--config", default="config.yaml", help="Path to config file"
    )
    model_parser.add_argument(
        "-e", "--env", default=".env", help="Path to .env file"
    )

    args = parser.parse_args()

    if args.command is None:
        # Default to start
        args.command = "start"
        args.config = "config.yaml"
        args.env = ".env"

    if args.command == "config-check":
        _check_config(args.config, args.env)
    elif args.command == "model-info":
        _model_info(args.config, args.env)
    elif args.command == "start":
        _run(args.config, args.env)


def _check_config(config_path: str, env_path: str) -> None:
    """Validate configuration and print summary."""
    try:
        config = load_config(config_path, env_path)
        print(f"Configuration valid: {config_path}")
        print(f"  Data directory: {config.data_dir}")
        print(f"  Bots configured: {len(config.bots)}")
        for bot in config.bots:
            model = config.claude_code.model if bot.ai.backend == "claude_code" else bot.ai.model
            print(f"    - {bot.id} ({bot.platform}) [{bot.ai.backend}: {model}]")
        print(f"  Storage: {config.storage.db_path}")
        print(f"  Browser: {config.services.browser.browser_type} (headless={config.services.browser.headless})")
    except Exception as e:
        print(f"Configuration error: {e}", file=sys.stderr)
        sys.exit(1)


def _model_info(config_path: str, env_path: str) -> None:
    """Show AI model information for each bot."""
    try:
        config = load_config(config_path, env_path)
    except Exception as e:
        print(f"Configuration error: {e}", file=sys.stderr)
        sys.exit(1)

    print("AI Model Configuration")
    print("=" * 50)
    for bot in config.bots:
        print(f"\n  Bot: {bot.id} ({bot.platform})")
        print(f"    Backend : {bot.ai.backend}")
        if bot.ai.backend == "anthropic":
            print(f"    Model   : {bot.ai.model}")
            print(f"    Tokens  : {bot.ai.max_tokens}")
        elif bot.ai.backend == "claude_code":
            print(f"    Model   : {config.claude_code.model}")
            print(f"    CLI     : {config.claude_code.cli_path}")
            print(f"    Timeout : {config.claude_code.timeout}s")
        print(f"    Temp    : {bot.ai.temperature}")
        tools = bot.ai.tools
        print(f"    Tools   : {', '.join(tools) if tools else '(none)'}")
        if bot.ai.backend == "claude_code" and config.claude_code.allowed_tools:
            print(f"    CLI Tools: {', '.join(config.claude_code.allowed_tools)}")
    print()


def _run(config_path: str, env_path: str) -> None:
    """Load config and start the application."""
    try:
        config = load_config(config_path, env_path)
    except FileNotFoundError as e:
        print(f"Error: {e}", file=sys.stderr)
        print("Run 'python install.py' first or copy config.example.yaml to config.yaml")
        sys.exit(1)
    except Exception as e:
        print(f"Configuration error: {e}", file=sys.stderr)
        sys.exit(1)

    setup_logging(config.log_level)

    async def _async_main() -> None:
        loop = asyncio.get_event_loop()
        stop_event = asyncio.Event()

        def _signal_handler() -> None:
            stop_event.set()

        for sig in (signal.SIGINT, signal.SIGTERM):
            try:
                loop.add_signal_handler(sig, _signal_handler)
            except NotImplementedError:
                # Windows doesn't support add_signal_handler
                signal.signal(sig, lambda s, f: _signal_handler())

        cfg = config
        while True:
            app = PandaBotApp(cfg)
            await app.start()

            # Wait for shutdown signal OR restart request
            restart_task = asyncio.create_task(app.restart_requested.wait())
            stop_task = asyncio.create_task(stop_event.wait())
            done, pending = await asyncio.wait(
                {restart_task, stop_task},
                return_when=asyncio.FIRST_COMPLETED,
            )
            for t in pending:
                t.cancel()

            await app.stop()

            if stop_event.is_set():
                # Normal shutdown
                break

            # Restart: reload config
            try:
                cfg = load_config(config_path, env_path)
                setup_logging(cfg.log_level)
            except Exception as e:
                print(f"Config reload error: {e}", file=sys.stderr)
                # Fall back to previous config
                cfg = config

    asyncio.run(_async_main())


if __name__ == "__main__":
    main()
