#!/usr/bin/env python3
"""Cross-platform install script for panda-bot.

Usage:
    python install.py          # Production install
    python install.py --dev    # Development install (includes test/lint tools)
"""

import os
import platform
import shutil
import subprocess
import sys

MIN_PYTHON = (3, 11)


def main() -> None:
    # 1. Check Python version
    if sys.version_info < MIN_PYTHON:
        sys.exit(
            f"Error: Python {MIN_PYTHON[0]}.{MIN_PYTHON[1]}+ is required. "
            f"You have {sys.version_info.major}.{sys.version_info.minor}."
        )

    print(f"Python {sys.version_info.major}.{sys.version_info.minor} detected. OK.")

    dev = "--dev" in sys.argv
    project_dir = os.path.dirname(os.path.abspath(__file__))
    venv_dir = os.path.join(project_dir, ".venv")
    is_windows = platform.system() == "Windows"

    bin_dir = "Scripts" if is_windows else "bin"
    pip = os.path.join(venv_dir, bin_dir, "pip")
    python_exe = os.path.join(venv_dir, bin_dir, "python")

    # 2. Create virtual environment
    if not os.path.isdir(venv_dir):
        print("Creating virtual environment...")
        subprocess.check_call([sys.executable, "-m", "venv", venv_dir])
    else:
        print("Virtual environment already exists.")

    # 3. Upgrade pip
    print("Upgrading pip...")
    subprocess.check_call([pip, "install", "--upgrade", "pip"])

    # 4. Install project
    if dev:
        print("Installing panda-bot in development mode...")
        subprocess.check_call([pip, "install", "-e", ".[dev]"], cwd=project_dir)
    else:
        print("Installing panda-bot...")
        subprocess.check_call([pip, "install", "."], cwd=project_dir)

    # 5. Install Playwright browsers
    print("Installing Playwright Chromium browser...")
    subprocess.check_call([python_exe, "-m", "playwright", "install", "chromium"])

    # 6. Create data directory
    data_dir = os.path.join(project_dir, "data")
    os.makedirs(data_dir, exist_ok=True)
    gitkeep = os.path.join(data_dir, ".gitkeep")
    if not os.path.exists(gitkeep):
        with open(gitkeep, "w") as f:
            pass

    # 7. Copy config files if missing
    for src, dst in [("config.example.yaml", "config.yaml"), (".env.example", ".env")]:
        src_path = os.path.join(project_dir, src)
        dst_path = os.path.join(project_dir, dst)
        if not os.path.exists(dst_path) and os.path.exists(src_path):
            shutil.copy(src_path, dst_path)
            print(f"Created {dst} from {src}")
        elif os.path.exists(dst_path):
            print(f"{dst} already exists, skipping.")

    # 8. Print instructions
    if is_windows:
        activate_cmd = r".\.venv\Scripts\activate"
    else:
        activate_cmd = "source .venv/bin/activate"

    print()
    print("=" * 50)
    print("  panda-bot installation complete!")
    print("=" * 50)
    print()
    print("Next steps:")
    print(f"  1. Edit config.yaml - configure your bots")
    print(f"  2. Edit .env - set your API keys:")
    print(f"       ANTHROPIC_API_KEY=sk-ant-...")
    print(f"       TELEGRAM_BOT_TOKEN=...")
    print(f"       DISCORD_BOT_TOKEN=...")
    print(f"  3. Activate the virtual environment:")
    print(f"       {activate_cmd}")
    print(f"  4. Start the bot:")
    print(f"       python -m panda_bot")
    print(f"  5. Or check config:")
    print(f"       python -m panda_bot config-check")
    print()


if __name__ == "__main__":
    main()
