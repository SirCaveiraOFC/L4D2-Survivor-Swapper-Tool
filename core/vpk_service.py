from __future__ import annotations

import os
import re
import shutil
import uuid
from pathlib import Path, PurePosixPath
from typing import Optional

import vdf
import vpk

from core.mdl_toolchain import run_subprocess_cancellable
from core.models import CancelCallback, DetectedModInfo, ModMetadata
from core.survivors import SurvivorRegistry


class VpkService:
    """Inspects, extracts, packs VPK archives, and parses/writes addoninfo.txt."""

    def __init__(self) -> None:
        self.active_cancel_cb: Optional[CancelCallback] = None

    def inspect_source(self, source_path: Path) -> DetectedModInfo:
        """Inspect a .vpk archive or extracted mod folder and auto-detect origin survivor."""
        source_path = Path(source_path)
        if not source_path.exists():
            raise FileNotFoundError(f"Mod source does not exist: {source_path}")

        is_vpk = source_path.is_file() and source_path.suffix.lower() == ".vpk"
        if is_vpk:
            file_list = self.list_vpk_files(source_path)
            addoninfo_text = self._read_vpk_text_case_insensitive(source_path, "addoninfo.txt")
        elif source_path.is_dir():
            file_list = [
                p.relative_to(source_path).as_posix()
                for p in source_path.rglob("*")
                if p.is_file()
            ]
            addoninfo_file = self._find_case_insensitive_file(source_path, "addoninfo.txt")
            addoninfo_text = (
                addoninfo_file.read_text(encoding="utf-8", errors="ignore")
                if addoninfo_file
                else None
            )
        else:
            raise ValueError(f"Unsupported mod source (expected .vpk file or folder): {source_path}")

        detected_origin = SurvivorRegistry.detect_from_paths(file_list)

        arms_mdls = [
            f for f in file_list
            if f.replace("\\", "/").lower().startswith("models/weapons/arms/")
            and f.lower().endswith(".mdl")
        ]
        detected_arms_mdl: Optional[str] = None
        if arms_mdls:
            if detected_origin is not None:
                expected_arms = SurvivorRegistry.get(detected_origin).fp_arms.mdl.lower()
                for cand in arms_mdls:
                    if PurePosixPath(cand).name.lower() == expected_arms:
                        detected_arms_mdl = cand
                        break
            if detected_arms_mdl is None:
                detected_arms_mdl = arms_mdls[0]

        vgui_files = [
            f for f in file_list
            if f.replace("\\", "/").lower().startswith("materials/vgui/")
            and (f.lower().endswith(".vtf") or f.lower().endswith(".vmt"))
        ]

        has_weapons = any(
            f.replace("\\", "/").lower().startswith("models/weapons/")
            and not f.replace("\\", "/").lower().startswith("models/weapons/arms/")
            for f in file_list
        )
        has_physics = any(
            f.replace("\\", "/").lower().startswith("models/survivors/")
            and f.lower().endswith(".phy")
            for f in file_list
        )
        light_models = sorted(
            f for f in file_list
            if f.replace("\\", "/").lower().startswith("models/survivors/")
            and "_light" in PurePosixPath(f).stem.lower()
            and f.lower().endswith(".mdl")
        )

        metadata = self.parse_addoninfo_text(addoninfo_text, fallback_title=source_path.stem)

        return DetectedModInfo(
            source_path=source_path,
            is_vpk=is_vpk,
            detected_origin=detected_origin,
            has_arms=bool(arms_mdls),
            detected_arms_mdl=detected_arms_mdl,
            has_vgui=bool(vgui_files),
            vgui_files=vgui_files,
            has_weapons=has_weapons,
            has_physics=has_physics,
            metadata=metadata,
            file_list=file_list,
            light_models=light_models,
        )

    def list_vpk_files(self, vpk_path: Path) -> list[str]:
        with self._open_vpk(vpk_path) as pak:
            return [entry.replace("\\", "/") for entry in pak]

    def extract_vpk(self, vpk_path: Path, dest_dir: Path) -> list[str]:
        """Extract all entries from a .vpk archive into dest_dir safely."""
        dest_dir.mkdir(parents=True, exist_ok=True)
        dest_root = dest_dir.resolve()
        extracted: list[str] = []

        with self._open_vpk(vpk_path) as pak:
            for rel_path in pak:
                clean_rel = rel_path.replace("\\", "/").lstrip("/")
                target = (dest_root / clean_rel).resolve()
                if not target.is_relative_to(dest_root):
                    raise ValueError(f"Unsafe path traversal detected in VPK entry: {rel_path}")
                target.parent.mkdir(parents=True, exist_ok=True)
                pak[rel_path].save(str(target))
                extracted.append(clean_rel)

        return extracted

    def pack_folder_to_vpk(
        self,
        source_dir: Path,
        output_vpk: Path,
        vpk_exe: Path,
        cancel_cb: Optional[CancelCallback] = None,
    ) -> list[str]:
        """Pack a mod directory into a .vpk file using Valve's vpk.exe."""
        if not vpk_exe.exists():
            raise FileNotFoundError(f"vpk.exe not found at: {vpk_exe}")
        if not source_dir.exists() or not source_dir.is_dir():
            raise FileNotFoundError(f"Source directory for VPK packing does not exist: {source_dir}")

        output_vpk.parent.mkdir(parents=True, exist_ok=True)

        expected_adjacent_lower = source_dir.parent / f"{source_dir.name.lower()}.vpk"
        expected_adjacent_exact = source_dir.parent / f"{source_dir.name}.vpk"
        for candidate in (expected_adjacent_lower, expected_adjacent_exact):
            if candidate.exists():
                candidate.unlink()

        returncode, stdout, stderr = run_subprocess_cancellable(
            [str(vpk_exe), str(source_dir)],
            cwd=source_dir.parent,
            cancel_cb=cancel_cb or self.active_cancel_cb,
        )
        logs = [line for line in (stdout + "\n" + stderr).splitlines() if line.strip()]
        if returncode != 0:
            raise RuntimeError(f"vpk.exe failed (exit {returncode}):\n" + "\n".join(logs[-20:]))

        produced = None
        for candidate in (expected_adjacent_exact, expected_adjacent_lower):
            if candidate.exists():
                produced = candidate
                break
        if produced is None:
            vpk_matches = list(source_dir.parent.glob("*.vpk"))
            if vpk_matches:
                produced = vpk_matches[0]

        if produced is None or not produced.exists():
            raise FileNotFoundError(f"vpk.exe succeeded but output VPK was not created next to {source_dir}")

        tmp_target = output_vpk.with_name(f".{output_vpk.stem}.{uuid.uuid4().hex[:8]}.vpk.tmp")
        try:
            shutil.copy2(produced, tmp_target)
            os.replace(tmp_target, output_vpk)
        finally:
            tmp_target.unlink(missing_ok=True)
            produced.unlink(missing_ok=True)
        return logs

    @staticmethod
    def parse_addoninfo_text(text: Optional[str], fallback_title: str = "Swapped Survivor Skin") -> ModMetadata:
        meta = ModMetadata(title=fallback_title, original_title=fallback_title)
        if not text:
            return meta

        parsed: dict = {}
        try:
            parsed = vdf.loads(text)
        except Exception:
            parsed = {}

        section = None
        for key, val in parsed.items():
            if key.lower() == "addoninfo" and isinstance(val, dict):
                section = val
                break

        if section is None:
            for match in re.finditer(r'^\s*"?([A-Za-z0-9_]+)"?\s+"([^"]*)"', text, re.M):
                k, v = match.group(1), match.group(2)
                VpkService._assign_metadata_field(meta, k, v)
            return meta

        for k, v in section.items():
            VpkService._assign_metadata_field(meta, str(k), str(v))
        return meta

    @staticmethod
    def serialize_addoninfo(metadata: ModMetadata) -> str:
        def esc(value: str) -> str:
            return value.replace('"', "'").replace("\r", " ").replace("\n", " ").strip()

        lines = [
            '"AddonInfo"',
            "{",
            f'\tAddonTitle\t\t"{esc(metadata.title or "Swapped Survivor Skin")}"',
            f'\tAddonVersion\t\t"{esc(metadata.version or "1.0")}"',
            f'\tAddonDescription\t"{esc(metadata.description)}"',
            f'\tAddonAuthor\t\t"{esc(metadata.author)}"',
        ]
        if metadata.author_steam_id.strip():
            lines.append(f'\tAddonAuthorSteamID\t"{esc(metadata.author_steam_id)}"')
        if metadata.url.strip():
            lines.append(f'\tAddonURL0\t\t"{esc(metadata.url)}"')

        lines.extend(
            [
                "",
                f"\tAddonSteamAppID\t\t{esc(metadata.steam_app_id or '550')}",
                "\tAddonContent_Skin\t1",
                "\tAddonContent_Survivor\t1",
            ]
        )

        handled_lower = {
            "addontitle",
            "addonversion",
            "addondescription",
            "addonauthor",
            "addonauthorsteamid",
            "addonurl0",
            "addonsteamappid",
            "addoncontent_skin",
            "addoncontent_survivor",
        }
        for k, v in metadata.extra_fields.items():
            if k.lower() not in handled_lower:
                lines.append(f'\t{k}\t"{esc(v)}"')

        lines.append("}")
        return "\n".join(lines) + "\n"

    @staticmethod
    def _assign_metadata_field(meta: ModMetadata, key: str, value: str) -> None:
        kl = key.lower()
        if kl == "addontitle":
            meta.title = value
            meta.original_title = value
        elif kl == "addonversion":
            meta.version = value
        elif kl == "addondescription":
            meta.description = value
        elif kl == "addonauthor":
            meta.author = value
        elif kl == "addonauthorsteamid":
            meta.author_steam_id = value
        elif kl == "addonurl0":
            meta.url = value
        elif kl == "addonsteamappid":
            meta.steam_app_id = value
        else:
            meta.extra_fields[key] = value

    @staticmethod
    def _open_vpk(vpk_path: Path) -> vpk.VPK:
        try:
            pak = vpk.open(str(vpk_path), path_enc="utf-8")
            for _ in pak:
                break
            return pak
        except UnicodeDecodeError:
            return vpk.open(str(vpk_path), path_enc="latin-1")

    def _read_vpk_text_case_insensitive(self, vpk_path: Path, target_rel: str) -> Optional[str]:
        target_lower = target_rel.lower()
        with self._open_vpk(vpk_path) as pak:
            for entry in pak:
                if entry.replace("\\", "/").lstrip("/").lower() == target_lower:
                    raw = pak[entry].read()
                    try:
                        return raw.decode("utf-8")
                    except UnicodeDecodeError:
                        return raw.decode("latin-1", errors="replace")
        return None

    @staticmethod
    def _find_case_insensitive_file(root: Path, filename: str) -> Optional[Path]:
        target = filename.lower()
        for entry in root.iterdir():
            if entry.is_file() and entry.name.lower() == target:
                return entry
        return None
