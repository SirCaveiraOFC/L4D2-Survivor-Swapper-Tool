from __future__ import annotations

import json
from dataclasses import asdict
from pathlib import Path
from typing import Optional

from core.models import AppConfig


class ConfigManager:
    """Handles loading and persisting application configuration in settings.json."""

    def __init__(self, config_path: Optional[Path] = None, project_root: Optional[Path] = None) -> None:
        self.project_root = project_root or Path(__file__).resolve().parent.parent
        self.config_path = config_path or (self.project_root / "settings.json")

    def load(self) -> AppConfig:
        config = AppConfig()
        if not self.config_path.exists():
            return config

        try:
            raw = json.loads(self.config_path.read_text(encoding="utf-8"))
        except (OSError, json.JSONDecodeError):
            return config

        if not isinstance(raw, dict):
            return config

        if "vpk_executable" in raw and raw["vpk_executable"]:
            config.vpk_executable = str(raw["vpk_executable"])
            vpk_path = Path(config.vpk_executable)
            if vpk_path.exists() and not raw.get("l4d2_dir"):
                config.l4d2_dir = str(vpk_path.parent.parent)
            if not raw.get("studiomdl_executable"):
                candidate = vpk_path.parent / "studiomdl.exe"
                if candidate.exists():
                    config.studiomdl_executable = str(candidate)

        for field_name in (
            "l4d2_dir",
            "studiomdl_executable",
            "output_dir",
            "workshop_download_dir",
            "kit_dir",
            "theme",
            "language",
            "github_repo",
        ):
            if field_name in raw and raw[field_name]:
                setattr(config, field_name, str(raw[field_name]))

        for bool_field in (
            "auto_install_to_addons",
            "keep_temp_on_error",
            "first_run_completed",
            "sanitize_origin_title",
            "auto_check_updates",
        ):
            if bool_field in raw:
                setattr(config, bool_field, bool(raw[bool_field]))

        return config

    def save(self, config: AppConfig) -> None:
        self.config_path.parent.mkdir(parents=True, exist_ok=True)
        payload = asdict(config)
        self.config_path.write_text(json.dumps(payload, indent=4, ensure_ascii=False), encoding="utf-8")

    def resolve_path(self, configured_path: str) -> Path:
        p = Path(configured_path)
        if p.is_absolute():
            return p
        return (self.project_root / p).resolve()
