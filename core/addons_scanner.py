from __future__ import annotations

import re
from pathlib import Path
from typing import Optional

import vdf

from core.models import AddonConflict, CancelCallback, InstalledAddonEntry, SurvivorId
from core.survivors import SurvivorRegistry
from core.vpk_service import VpkService


class AddonsScanner:
    """Scans left4dead2/addons and workshop VPKs for survivor mods, conflicts, and addonlist states."""

    _SURVIVOR_PREFIXES = ("models/survivors/", "models/weapons/arms/", "materials/vgui/")
    _PREVIEW_CANDIDATES = ("addonimage.jpg", "addonimage.jpeg", "addonimage.png")

    @classmethod
    def _read_sibling_preview_image(cls, vpk_path: Path) -> Optional[bytes]:
        for ext in (".jpg", ".jpeg", ".png"):
            sibling = vpk_path.with_suffix(ext)
            if sibling.is_file():
                try:
                    return sibling.read_bytes()
                except OSError:
                    return None
        return None

    @classmethod
    def read_addon_preview_image(cls, vpk_path: Path) -> Optional[bytes]:
        """Extract addonimage.jpg or addonimage.png bytes from a VPK or sibling workshop preview."""
        if not vpk_path.exists() or not vpk_path.is_file():
            return None
        try:
            with VpkService._open_vpk(vpk_path) as pak:
                for entry in pak:
                    norm = entry.replace("\\", "/").lstrip("./").lower()
                    if norm in cls._PREVIEW_CANDIDATES:
                        return pak[entry].read()
        except Exception:
            pass
        return cls._read_sibling_preview_image(vpk_path)

    @classmethod
    def read_source_preview_image(cls, source_path: Path) -> Optional[bytes]:
        """Extract addonimage bytes from either a .vpk archive or an extracted mod folder."""
        if source_path.is_file() and source_path.suffix.lower() == ".vpk":
            return cls.read_addon_preview_image(source_path)
        if source_path.is_dir():
            for child in source_path.iterdir():
                if child.is_file() and child.name.lower() in cls._PREVIEW_CANDIDATES:
                    try:
                        return child.read_bytes()
                    except OSError:
                        return None
        return None

    @staticmethod
    def load_addonlist_states(addons_dir: Path) -> dict[str, bool]:
        """Parse left4dead2/addonlist.txt into normalized relative VPK key -> enabled flag."""
        addonlist_path = addons_dir.parent / "addonlist.txt"
        if not addonlist_path.exists():
            return {}

        text = addonlist_path.read_text(encoding="utf-8", errors="ignore")
        states: dict[str, bool] = {}

        try:
            parsed = vdf.loads(text)
            for section_key, section_val in parsed.items():
                if section_key.lower() == "addonlist" and isinstance(section_val, dict):
                    for k, v in section_val.items():
                        norm_key = str(k).replace("\\", "/").lstrip("/").lower()
                        states[norm_key] = str(v).strip() != "0"
                    return states
        except Exception:
            pass

        for match in re.finditer(r'^\s*"([^"]+)"\s+"([^"]*)"', text, re.M):
            norm_key = match.group(1).replace("\\", "/").lstrip("/").lower()
            states[norm_key] = match.group(2).strip() != "0"
        return states

    @classmethod
    def scan_survivor_addons(
        cls,
        addons_dir: Path,
        include_workshop: bool = True,
        cancel_cb: Optional[CancelCallback] = None,
    ) -> list[InstalledAddonEntry]:
        """Inspect VPKs in addons/ (and addons/workshop/) and return those affecting survivors."""
        if not addons_dir.exists() or not addons_dir.is_dir():
            return []

        addonlist_states = cls.load_addonlist_states(addons_dir)
        candidates: list[tuple[Path, str]] = [(p, "addons") for p in sorted(addons_dir.glob("*.vpk"))]
        if include_workshop:
            workshop_dir = addons_dir / "workshop"
            if workshop_dir.exists() and workshop_dir.is_dir():
                candidates.extend((p, "workshop") for p in sorted(workshop_dir.glob("*.vpk")))

        entries: list[InstalledAddonEntry] = []
        for vpk_path, source_kind in candidates:
            if cancel_cb is not None and cancel_cb():
                return []
            entry = cls._inspect_vpk_fast(vpk_path, source_kind, addons_dir, addonlist_states)
            if entry is not None:
                entries.append(entry)

        entries.sort(key=lambda e: (e.source_kind != "addons", e.title.lower(), e.vpk_path.name.lower()))
        return entries

    @classmethod
    def find_conflicts(
        cls,
        addons_dir: Path,
        planned_installs: list[tuple[SurvivorId, str]],
        include_workshop: bool = True,
    ) -> list[AddonConflict]:
        """Find enabled addons in addons/ or workshop/ replacing any survivor in planned_installs."""
        if not planned_installs or not addons_dir.exists():
            return []

        entries = cls.scan_survivor_addons(addons_dir, include_workshop=include_workshop)
        conflicts: list[AddonConflict] = []

        for target_id, new_vpk_name in planned_installs:
            new_name_lower = new_vpk_name.lower()
            for entry in entries:
                if not entry.enabled_in_game:
                    continue
                if entry.source_kind == "addons" and entry.vpk_path.name.lower() == new_name_lower:
                    continue
                if target_id in entry.replaced_survivors or (
                    not entry.replaced_survivors and entry.origin == target_id
                ):
                    conflicts.append(
                        AddonConflict(
                            target_survivor=target_id,
                            new_vpk_name=new_vpk_name,
                            existing_addon=entry,
                        )
                    )
        return conflicts

    @classmethod
    def update_addonlist(
        cls,
        addons_dir: Path,
        disable_entries: list[InstalledAddonEntry],
        enable_filenames: list[str] | None = None,
    ) -> Path:
        """Set conflicting addons to '0' and newly installed VPKs to '1' in addonlist.txt."""
        addonlist_path = addons_dir.parent / "addonlist.txt"
        ordered_pairs: list[tuple[str, str]] = []
        key_index: dict[str, int] = {}

        if addonlist_path.exists():
            raw_text = addonlist_path.read_text(encoding="utf-8", errors="ignore")
            try:
                parsed = vdf.loads(raw_text)
                for sec_k, sec_v in parsed.items():
                    if sec_k.lower() == "addonlist" and isinstance(sec_v, dict):
                        for k, v in sec_v.items():
                            norm = str(k).replace("\\", "/").lstrip("/").lower()
                            win_key = str(k).replace("/", "\\")
                            key_index[norm] = len(ordered_pairs)
                            ordered_pairs.append((win_key, str(v)))
                        break
            except Exception:
                for match in re.finditer(r'^\s*"([^"]+)"\s+"([^"]*)"', raw_text, re.M):
                    win_key = match.group(1).replace("/", "\\")
                    norm = win_key.replace("\\", "/").lstrip("/").lower()
                    key_index[norm] = len(ordered_pairs)
                    ordered_pairs.append((win_key, match.group(2)))

        def upsert(rel_path: Path, state: str) -> None:
            rel_posix = rel_path.as_posix().lstrip("/").lower()
            rel_win = rel_posix.replace("/", "\\")
            if rel_posix in key_index:
                idx = key_index[rel_posix]
                ordered_pairs[idx] = (ordered_pairs[idx][0], state)
            else:
                key_index[rel_posix] = len(ordered_pairs)
                ordered_pairs.append((rel_win, state))

        for entry in disable_entries:
            try:
                rel = entry.vpk_path.relative_to(addons_dir)
            except ValueError:
                rel = Path(entry.vpk_path.name)
            upsert(rel, "0")

        for fname in enable_filenames or []:
            upsert(Path(fname), "1")

        lines = ['"AddonList"', "{"]
        for k, v in ordered_pairs:
            safe_k = k.replace('"', "")
            safe_v = "1" if str(v).strip() != "0" else "0"
            lines.append(f'\t"{safe_k}"\t\t"{safe_v}"')
        lines.append("}")
        addonlist_path.write_text("\n".join(lines) + "\n", encoding="utf-8", newline="\n")
        return addonlist_path

    @classmethod
    def _inspect_vpk_fast(
        cls,
        vpk_path: Path,
        source_kind: str,
        addons_dir: Path,
        addonlist_states: dict[str, bool],
        allow_non_survivor: bool = False,
    ) -> Optional[InstalledAddonEntry]:
        try:
            with VpkService._open_vpk(vpk_path) as pak:
                orig_entries = list(pak)
                lower_paths = [entry.replace("\\", "/").lstrip("./").lower() for entry in orig_entries]
                has_survivor_asset = any(
                    any(p.startswith(pref) for pref in cls._SURVIVOR_PREFIXES) for p in lower_paths
                )
                if not has_survivor_asset and not allow_non_survivor:
                    return None

                replaced_body = [
                    spec.id
                    for spec in SurvivorRegistry.all()
                    if f"models/survivors/{spec.model_file.lower()}" in lower_paths
                ]
                origin = SurvivorRegistry.detect_from_paths(lower_paths)
                if origin is None and not replaced_body and not allow_non_survivor:
                    return None

                replaced_all = tuple(replaced_body) if replaced_body else ((origin,) if origin else ())
                addoninfo_text = None
                preview_bytes: Optional[bytes] = None
                for orig_entry in orig_entries:
                    norm_entry = orig_entry.replace("\\", "/").lstrip("./").lower()
                    if norm_entry == "addoninfo.txt" and addoninfo_text is None:
                        data = pak[orig_entry].read()
                        try:
                            addoninfo_text = data.decode("utf-8")
                        except UnicodeDecodeError:
                            addoninfo_text = data.decode("latin-1", errors="replace")
                    elif norm_entry in cls._PREVIEW_CANDIDATES and preview_bytes is None:
                        preview_bytes = pak[orig_entry].read()
                    if addoninfo_text is not None and preview_bytes is not None:
                        break
        except Exception:
            return None

        if preview_bytes is None:
            preview_bytes = cls._read_sibling_preview_image(vpk_path)

        meta = VpkService.parse_addoninfo_text(addoninfo_text, fallback_title=vpk_path.stem)
        tagline = ""
        for k, v in meta.extra_fields.items():
            if k.lower() == "addontagline":
                tagline = v.strip()
                break

        has_arms = any(p.startswith("models/weapons/arms/") and p.endswith(".mdl") for p in lower_paths)
        has_vgui = any(p.startswith("materials/vgui/") and (p.endswith(".vtf") or p.endswith(".vmt")) for p in lower_paths)
        try:
            file_size_bytes = vpk_path.stat().st_size
        except OSError:
            file_size_bytes = 0

        try:
            rel_key = vpk_path.relative_to(addons_dir).as_posix().lower()
        except ValueError:
            rel_key = vpk_path.name.lower()

        return InstalledAddonEntry(
            vpk_path=vpk_path,
            title=meta.title or vpk_path.stem,
            author=meta.author,
            origin=origin or (replaced_all[0] if replaced_all else None),
            replaced_survivors=replaced_all,
            source_kind=source_kind,
            enabled_in_game=addonlist_states.get(rel_key, True),
            version=meta.version if addoninfo_text else "",
            description=meta.description,
            url=meta.url,
            author_steam_id=meta.author_steam_id,
            tagline=tagline,
            file_size_bytes=file_size_bytes,
            has_arms=has_arms,
            has_vgui=has_vgui,
            preview_bytes=preview_bytes,
        )

    @classmethod
    def detect_non_survivor_kind(
        cls,
        vpk_path: Optional[Path] = None,
        tags: tuple[str, ...] = (),
    ) -> str:
        """Identify concrete L4D2 non-survivor VPK mod category, or empty string if unclear."""
        if vpk_path is not None and vpk_path.is_file():
            try:
                with VpkService._open_vpk(vpk_path) as pak:
                    lower_paths = [
                        entry.replace("\\", "/").lstrip("./").lower()
                        for entry in pak
                    ]
                if any(
                    p.startswith(("scripts/vscripts/", "modes/", "scripts/talker/")) or p.endswith(".nut")
                    for p in lower_paths
                ):
                    return "dl_mod_type_vscript"
                if any(
                    p.startswith("missions/") or (p.startswith("maps/") and p.endswith(".bsp"))
                    for p in lower_paths
                ):
                    return "dl_mod_type_campaign"
                if any(
                    p.startswith(("models/weapons/", "models/v_models/", "models/w_models/"))
                    for p in lower_paths
                ):
                    return "dl_mod_type_weapon"
                if any(p.startswith("models/infected/") for p in lower_paths):
                    return "dl_mod_type_infected"
                has_models = any(p.startswith("models/") for p in lower_paths)
                if any(
                    p.startswith("resource/ui/") or p == "scripts/hudlayout.res"
                    for p in lower_paths
                ) or (not has_models and any(p.startswith("materials/vgui/") for p in lower_paths)):
                    return "dl_mod_type_hud"
                if any(p.startswith("sound/") for p in lower_paths) and not has_models:
                    return "dl_mod_type_audio"
                return ""
            except Exception:
                return ""

        tag_set = {t.strip().lower() for t in tags if t and t.strip()}
        if "scripts" in tag_set:
            return "dl_mod_type_vscript"
        if "campaigns" in tag_set or "maps" in tag_set:
            return "dl_mod_type_campaign"
        if "weapons" in tag_set:
            return "dl_mod_type_weapon"
        if "sounds" in tag_set or "audio" in tag_set:
            return "dl_mod_type_audio"
        if "ui" in tag_set or "hud" in tag_set:
            return "dl_mod_type_hud"
        return ""
