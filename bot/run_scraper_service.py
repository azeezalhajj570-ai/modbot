"""Command entry point for the scraper worker service."""

from __future__ import annotations

import os
import shutil
import sys


def main() -> None:
    executable = shutil.which("dramatiq")
    if executable is None:
        raise SystemExit("dramatiq is not installed or not available on PATH")

    os.execvp(executable, [executable, "bot.agents.worker", *sys.argv[1:]])


if __name__ == "__main__":
    main()
