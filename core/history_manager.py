from __future__ import annotations

import json
import os
from dataclasses import asdict
from pathlib import Path
from typing import Optional

from core.models import ConversionHistoryEntry, ConversionHistoryOutput


class HistoryManager:
    """Persists and manages conversion history records in conversion_history.json."""

    MAX_ENTRIES = 200

    def __init__(
        self,
        history_path: Optional[Path] = None,
        project_root: Optional[Path] = None,
    ) -> None:
        self.project_root = (
            Path(project_root) if project_root else Path(__file__).resolve().parent.parent
        )
        self.history_path = (
            Path(history_path)
            if history_path
            else self.project_root / "conversion_history.json"
        )

    def load(self) -> list[ConversionHistoryEntry]:
        if not self.history_path.exists():
            return []
        try:
            raw = json.loads(self.history_path.read_text(encoding="utf-8", errors="ignore"))
        except (OSError, json.JSONDecodeError, TypeError):
            return []
        if not isinstance(raw, list):
            return []

        entries: list[ConversionHistoryEntry] = []
        for item in raw:
            if not isinstance(item, dict):
                continue
            outputs_raw = item.get("outputs") or []
            outputs: list[ConversionHistoryOutput] = []
            if isinstance(outputs_raw, list):
                for out_item in outputs_raw:
                    if not isinstance(out_item, dict):
                        continue
                    outputs.append(
                        ConversionHistoryOutput(
                            destination=str(out_item.get("destination", "")),
                            success=bool(out_item.get("success", False)),
                            cancelled=bool(out_item.get("cancelled", False)),
                            vpk_path=str(out_item.get("vpk_path", "")),
                            error_message=str(out_item.get("error_message", "")),
                            warnings=[str(w) for w in (out_item.get("warnings") or [])],
                        )
                    )
            entries.append(
                ConversionHistoryEntry(
                    entry_id=str(item.get("entry_id", "")),
                    created_at=str(item.get("created_at", "")),
                    mod_title=str(item.get("mod_title", "")),
                    author=str(item.get("author", "")),
                    source_path=str(item.get("source_path", "")),
                    origin=str(item.get("origin", "")),
                    destinations=[str(d) for d in (item.get("destinations") or [])],
                    output_dir=str(item.get("output_dir", "")),
                    installed_to_addons=bool(item.get("installed_to_addons", False)),
                    custom_cover_used=bool(item.get("custom_cover_used", False)),
                    outputs=outputs,
                )
            )
        return entries

    def save(self, entries: list[ConversionHistoryEntry]) -> Path:
        self.history_path.parent.mkdir(parents=True, exist_ok=True)
        trimmed = entries[: self.MAX_ENTRIES]
        payload = [asdict(entry) for entry in trimmed]
        tmp_path = self.history_path.with_suffix(".json.tmp")
        tmp_path.write_text(
            json.dumps(payload, indent=2, ensure_ascii=False) + "\n",
            encoding="utf-8",
            newline="\n",
        )
        os.replace(tmp_path, self.history_path)
        return self.history_path

    def add_entry(self, entry: ConversionHistoryEntry) -> list[ConversionHistoryEntry]:
        entries = self.load()
        entries.insert(0, entry)
        self.save(entries)
        return entries[: self.MAX_ENTRIES]

    def remove_entry(self, entry_id: str) -> list[ConversionHistoryEntry]:
        entries = [e for e in self.load() if e.entry_id != entry_id]
        self.save(entries)
        return entries

    def clear(self) -> None:
        self.save([])
