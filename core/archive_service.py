from __future__ import annotations

import shutil
import subprocess
import tempfile
import zipfile
from dataclasses import dataclass, field
from pathlib import Path
from typing import Optional

from core.survivors import SurvivorRegistry
from core.vpk_service import VpkService


ARCHIVE_EXTENSIONS = {".zip", ".rar", ".7z"}


@dataclass
class SourcePreparationResult:
    """Validated mod source resolution result for drop/browse files and archives."""

    valid: bool
    resolved_path: Optional[Path] = None
    candidate_vpks: list[Path] = field(default_factory=list)
    temp_dir: Optional[Path] = None
    error_key: str = ""
    error_kwargs: dict[str, str] = field(default_factory=dict)


class ArchiveSourceManager:
    """Validates dropped mod folders/VPKs and unpacks .zip/.rar/.7z mod bundles safely."""

    @staticmethod
    def is_supported_drop_path(path: Path) -> bool:
        """Fast check for dragEnterEvent accepting folders, .vpk, .zip, .rar, and .7z."""
        if path.is_dir():
            return True
        if path.is_file():
            ext = path.suffix.lower()
            return ext == ".vpk" or ext in ARCHIVE_EXTENSIONS
        return False

    @classmethod
    def _has_survivor_mod_paths(cls, rel_paths: list[str]) -> bool:
        norm = [p.replace("\\", "/").lstrip("./").lower() for p in rel_paths]
        if SurvivorRegistry.detect_from_paths(norm) is not None:
            return True
        return any(
            (p.startswith("models/survivors/") and p.endswith(".mdl"))
            or (p.startswith("models/weapons/arms/") and p.endswith(".mdl"))
            for p in norm
        )

    @classmethod
    def _is_valid_vpk(cls, vpk_path: Path) -> bool:
        try:
            with VpkService._open_vpk(vpk_path) as pak:
                rel_paths = [str(entry) for entry in pak]
            return cls._has_survivor_mod_paths(rel_paths)
        except Exception:
            return False

    @classmethod
    def _folder_has_direct_mod_assets(cls, folder: Path) -> bool:
        for sub in ("models/survivors", "models/weapons/arms", "materials/vgui"):
            sub_dir = folder / sub
            if sub_dir.exists() and sub_dir.is_dir():
                rel_paths = [
                    p.relative_to(folder).as_posix()
                    for p in sub_dir.rglob("*")
                    if p.is_file()
                ]
                if cls._has_survivor_mod_paths(rel_paths):
                    return True
        return False

    @staticmethod
    def _find_cli_unpacker(ext: str) -> list[tuple[str, Path]]:
        tools: list[tuple[str, Path]] = []
        tar_path = shutil.which("tar")
        if tar_path:
            tools.append(("tar", Path(tar_path)))

        seven_z = shutil.which("7z") or shutil.which("7za")
        if seven_z:
            tools.append(("7z", Path(seven_z)))
        else:
            for p in (
                Path(r"C:\Program Files\7-Zip\7z.exe"),
                Path(r"C:\Program Files (x86)\7-Zip\7z.exe"),
            ):
                if p.exists():
                    tools.append(("7z", p))
                    break

        if ext == ".rar":
            unrar = shutil.which("UnRAR") or shutil.which("WinRAR")
            if unrar:
                tools.append(("unrar", Path(unrar)))
            else:
                for p in (
                    Path(r"C:\Program Files\WinRAR\UnRAR.exe"),
                    Path(r"C:\Program Files (x86)\WinRAR\UnRAR.exe"),
                ):
                    if p.exists():
                        tools.append(("unrar", p))
                        break
        return tools

    @classmethod
    def _extract_archive(cls, archive_path: Path, dest_dir: Path) -> Optional[str]:
        ext = archive_path.suffix.lower()
        dest_root = dest_dir.resolve()
        creationflags = getattr(subprocess, "CREATE_NO_WINDOW", 0)

        if ext == ".zip":
            try:
                with zipfile.ZipFile(archive_path, "r") as zf:
                    for info in zf.infolist():
                        if info.is_dir():
                            continue
                        rel = info.filename.replace("\\", "/").lstrip("/")
                        target = (dest_root / rel).resolve()
                        if not target.is_relative_to(dest_root):
                            return "Unsafe archive path traversal detected"
                        target.parent.mkdir(parents=True, exist_ok=True)
                        with zf.open(info, "r") as src, target.open("wb") as dst:
                            shutil.copyfileobj(src, dst)
                return None
            except Exception as exc:
                return str(exc)

        last_err = "No compatible archive extractor found (.zip/.rar/.7z)"
        for kind, exe in cls._find_cli_unpacker(ext):
            try:
                if kind == "tar":
                    list_proc = subprocess.run(
                        [str(exe), "-tf", str(archive_path)],
                        capture_output=True,
                        text=True,
                        errors="replace",
                        creationflags=creationflags,
                    )
                    if list_proc.returncode != 0:
                        last_err = (list_proc.stderr or list_proc.stdout).strip()
                        continue
                    for line in list_proc.stdout.splitlines():
                        clean = line.strip().replace("\\", "/")
                        if not clean:
                            continue
                        if clean.startswith("/") or ".." in clean.split("/"):
                            return "Unsafe archive path traversal detected"
                    proc = subprocess.run(
                        [str(exe), "-xf", str(archive_path), "-C", str(dest_root)],
                        capture_output=True,
                        text=True,
                        errors="replace",
                        creationflags=creationflags,
                    )
                elif kind == "7z":
                    proc = subprocess.run(
                        [str(exe), "x", "-y", f"-o{dest_root}", str(archive_path)],
                        capture_output=True,
                        text=True,
                        errors="replace",
                        creationflags=creationflags,
                    )
                else:
                    proc = subprocess.run(
                        [str(exe), "x", "-y", "-o+", str(archive_path), str(dest_root) + "\\"],
                        capture_output=True,
                        text=True,
                        errors="replace",
                        creationflags=creationflags,
                    )

                if proc.returncode == 0:
                    return None
                last_err = (proc.stderr or proc.stdout).strip() or f"Exit {proc.returncode}"
            except OSError as exc:
                last_err = str(exc)

        return last_err

    @classmethod
    def prepare_source(cls, source_path: Path) -> SourcePreparationResult:
        """Validate a dropped/selected .vpk, extracted folder, or .zip/.rar/.7z archive."""
        path = Path(source_path)
        if not path.exists():
            return SourcePreparationResult(
                valid=False,
                error_key="err_drop_missing",
                error_kwargs={"name": path.name},
            )

        if path.is_file():
            ext = path.suffix.lower()
            if ext == ".vpk":
                if cls._is_valid_vpk(path):
                    return SourcePreparationResult(valid=True, resolved_path=path)
                return SourcePreparationResult(
                    valid=False,
                    error_key="err_drop_not_survivor_vpk",
                    error_kwargs={"name": path.name},
                )

            if ext in ARCHIVE_EXTENSIONS:
                temp_dir = Path(tempfile.mkdtemp(prefix="l4d2sw_arch_"))
                extract_err = cls._extract_archive(path, temp_dir)
                if extract_err is not None:
                    shutil.rmtree(temp_dir, ignore_errors=True)
                    return SourcePreparationResult(
                        valid=False,
                        error_key="err_drop_archive_failed",
                        error_kwargs={"name": path.name, "error": extract_err},
                    )

                sub_res = cls._resolve_extracted_tree(temp_dir, temp_dir=temp_dir, archive_name=path.name)
                if not sub_res.valid:
                    shutil.rmtree(temp_dir, ignore_errors=True)
                    sub_res.temp_dir = None
                return sub_res

            return SourcePreparationResult(
                valid=False,
                error_key="err_drop_unsupported_ext",
                error_kwargs={"name": path.name},
            )

        if path.is_dir():
            return cls._resolve_extracted_tree(path, temp_dir=None, archive_name=path.name)

        return SourcePreparationResult(
            valid=False,
            error_key="err_drop_unsupported_ext",
            error_kwargs={"name": path.name},
        )

    @classmethod
    def _resolve_extracted_tree(
        cls,
        folder: Path,
        temp_dir: Optional[Path],
        archive_name: str,
    ) -> SourcePreparationResult:
        if cls._folder_has_direct_mod_assets(folder):
            return SourcePreparationResult(valid=True, resolved_path=folder, temp_dir=temp_dir)

        direct_vpks = sorted(
            p for p in folder.iterdir()
            if p.is_file() and p.suffix.lower() == ".vpk" and cls._is_valid_vpk(p)
        )
        if not direct_vpks and temp_dir is not None:
            direct_vpks = sorted(
                p for p in folder.rglob("*.vpk")
                if p.is_file() and cls._is_valid_vpk(p)
            )
        if len(direct_vpks) == 1:
            return SourcePreparationResult(valid=True, resolved_path=direct_vpks[0], temp_dir=temp_dir)
        if len(direct_vpks) > 1:
            return SourcePreparationResult(
                valid=True,
                candidate_vpks=direct_vpks,
                temp_dir=temp_dir,
            )

        subfolders = [p for p in sorted(folder.iterdir()) if p.is_dir()][:40]
        valid_subfolders = [sub for sub in subfolders if cls._folder_has_direct_mod_assets(sub)]
        if len(valid_subfolders) == 1:
            return SourcePreparationResult(
                valid=True,
                resolved_path=valid_subfolders[0],
                temp_dir=temp_dir,
            )
        if len(valid_subfolders) > 1:
            return SourcePreparationResult(
                valid=True,
                resolved_path=valid_subfolders[0],
                temp_dir=temp_dir,
            )

        if temp_dir is not None:
            for candidate_dir in sorted(folder.rglob("models")):
                parent = candidate_dir.parent
                if cls._folder_has_direct_mod_assets(parent):
                    return SourcePreparationResult(valid=True, resolved_path=parent, temp_dir=temp_dir)

        return SourcePreparationResult(
            valid=False,
            error_key="err_drop_invalid_folder",
            error_kwargs={"name": archive_name},
        )
