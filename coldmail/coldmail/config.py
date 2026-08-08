"""Load coldmail configuration from config.yaml."""
from __future__ import annotations

import os
import sys
from pathlib import Path

import yaml

ROOT = Path(__file__).resolve().parent.parent
DEFAULT_CONFIG = ROOT / "config.yaml"
DATA_DIR = ROOT / "data"


def ensure_data_dir() -> Path:
    DATA_DIR.mkdir(exist_ok=True)
    return DATA_DIR


def load_config(path: Path | None = None) -> dict:
    cfg_path = Path(path) if path else DEFAULT_CONFIG
    if not cfg_path.exists():
        sys.exit(f"config file not found: {cfg_path}  (copy config.yaml)")
    with open(cfg_path, "r", encoding="utf-8") as fh:
        cfg = yaml.safe_load(fh) or {}
    return cfg


def save_config(cfg: dict, path: Path | None = None) -> None:
    cfg_path = Path(path) if path else DEFAULT_CONFIG
    with open(cfg_path, "w", encoding="utf-8") as fh:
        yaml.safe_dump(cfg, fh, sort_keys=False, allow_unicode=True)


def ollama_available(base_url: str, timeout: float = 2.5) -> bool:
    import requests

    try:
        r = requests.get(base_url.rstrip("/") + "/api/tags", timeout=timeout)
        return r.status_code == 200
    except Exception:
        return False
