"""Load and merge settings.yaml + .env into a unified settings dict."""
from __future__ import annotations

from pathlib import Path
from typing import Any

import yaml
from dotenv import load_dotenv


def load_settings(settings_path: str | Path = "config/settings.yaml") -> dict[str, Any]:
    """Load settings from YAML file and load .env into the process environment."""
    load_dotenv()  # populates os.environ from .env

    settings_path = Path(settings_path)
    if not settings_path.exists():
        raise FileNotFoundError(
            f"Settings file not found: {settings_path}\n"
            "Copy or edit config/settings.yaml to get started."
        )

    with open(settings_path, encoding="utf-8") as f:
        settings = yaml.safe_load(f) or {}

    return settings
