"""Shared data-directory helper for binance-mm.

Logs live in a single user-owned folder so that:
  * the command works from ANY directory (no `cd` needed),
  * every terminal (bot + live + watch) reads/writes the SAME files.

Default:  ~/.binance-mm/logs/demo.jsonl  and  .../live.jsonl
Override with the env var  BINANCE_MM_HOME  if you want logs elsewhere.
"""

from __future__ import annotations

import os
from pathlib import Path


def logs_dir() -> Path:
    base = os.environ.get("BINANCE_MM_HOME") or str(Path.home() / ".binance-mm")
    d = Path(base) / "logs"
    d.mkdir(parents=True, exist_ok=True)
    return d


def demo_log() -> Path:
    return logs_dir() / "demo.jsonl"


def live_log() -> Path:
    return logs_dir() / "live.jsonl"
