from __future__ import annotations

import os
from pathlib import Path
from typing import Optional

import vdf

from core.crowbar_settings import CrowbarSettingsManager
from core.models import AppConfig, EnvironmentStatus

try:
    import winreg
except ImportError:
    winreg = None


class SteamLocator:
    """Detects Steam libraries, Left 4 Dead 2 (550), Authoring Tools (563), and toolchain binaries."""

    L4D2_APP_ID = "550"
    AUTHORING_TOOLS_APP_ID = "563"

    def __init__(self, project_root: Optional[Path] = None) -> None:
        self.project_root = project_root or Path(__file__).resolve().parent.parent

    def inspect_environment(self, config: Optional[AppConfig] = None) -> EnvironmentStatus:
        status = EnvironmentStatus()
        status.decompiler_cli_path = self.find_decompiler_cli()

        steam_path = self.find_steam_path()
        status.steam_path = steam_path

        libraries = self.find_steam_libraries(steam_path) if steam_path else []
        status.steam_libraries = libraries

        l4d2_dir = self._resolve_l4d2_dir(libraries, config)
        if l4d2_dir and l4d2_dir.exists():
            status.l4d2_dir = l4d2_dir
            gameinfo = l4d2_dir / "left4dead2" / "gameinfo.txt"
            if gameinfo.exists():
                status.l4d2_gameinfo = gameinfo
                status.l4d2_installed = True
            addons_dir = l4d2_dir / "left4dead2" / "addons"
            status.l4d2_addons_dir = addons_dir

        studiomdl, vpk_exe = self._resolve_authoring_binaries(l4d2_dir, config)
        status.studiomdl_path = studiomdl
        status.vpk_exe_path = vpk_exe

        manifest_563_found = self._has_appmanifest(libraries, self.AUTHORING_TOOLS_APP_ID)
        status.authoring_tools_installed = bool(
            (studiomdl and studiomdl.exists())
            and (vpk_exe and vpk_exe.exists())
            and (manifest_563_found or l4d2_dir is not None)
        )

        crowbar_mgr = CrowbarSettingsManager()
        status.crowbar_settings_path = crowbar_mgr.settings_path
        status.crowbar_settings_exists = crowbar_mgr.settings_path.exists()
        is_valid, issues = crowbar_mgr.validate(l4d2_dir)
        status.crowbar_settings_valid = is_valid
        status.crowbar_issues = issues

        return status

    def find_decompiler_cli(self) -> Optional[Path]:
        candidate = self.project_root / "tools" / "mdl_decompiler_cli" / "MdlDecompilerCli.exe"
        return candidate if candidate.exists() else None

    def find_steam_path(self) -> Optional[Path]:
        if winreg is None:
            return None

        registry_candidates = [
            (winreg.HKEY_CURRENT_USER, r"Software\Valve\Steam", "SteamPath"),
            (winreg.HKEY_LOCAL_MACHINE, r"SOFTWARE\WOW6432Node\Valve\Steam", "InstallPath"),
            (winreg.HKEY_LOCAL_MACHINE, r"SOFTWARE\Valve\Steam", "InstallPath"),
        ]
        for root, subkey, value_name in registry_candidates:
            try:
                with winreg.OpenKey(root, subkey) as key:
                    val, _ = winreg.QueryValueEx(key, value_name)
                    if val:
                        path = Path(os.path.normpath(str(val)))
                        if path.exists():
                            return path
            except OSError:
                continue

        default_path = Path(r"C:\Program Files (x86)\Steam")
        return default_path if default_path.exists() else None

    def find_steam_libraries(self, steam_path: Optional[Path]) -> list[Path]:
        if steam_path is None:
            return []

        libraries: list[Path] = []
        seen: set[str] = set()

        def add_library(p: Path) -> None:
            norm = os.path.normpath(str(p))
            key = norm.lower()
            if key not in seen and Path(norm).exists():
                seen.add(key)
                libraries.append(Path(norm))

        add_library(steam_path)

        vdf_candidates = [
            steam_path / "steamapps" / "libraryfolders.vdf",
            steam_path / "config" / "libraryfolders.vdf",
        ]
        for vdf_file in vdf_candidates:
            if not vdf_file.exists():
                continue
            try:
                data = vdf.loads(vdf_file.read_text(encoding="utf-8", errors="ignore"))
            except Exception:
                continue

            root_node = data.get("libraryfolders") or data.get("LibraryFolders") or {}
            if not isinstance(root_node, dict):
                continue

            for key, value in root_node.items():
                if not str(key).isdigit():
                    continue
                if isinstance(value, str):
                    add_library(Path(value))
                elif isinstance(value, dict) and "path" in value:
                    add_library(Path(str(value["path"])))

        return libraries

    def _has_appmanifest(self, libraries: list[Path], app_id: str) -> bool:
        for lib in libraries:
            if (lib / "steamapps" / f"appmanifest_{app_id}.acf").exists():
                return True
        return False

    def _resolve_l4d2_dir(self, libraries: list[Path], config: Optional[AppConfig]) -> Optional[Path]:
        if config and config.l4d2_dir:
            configured = Path(config.l4d2_dir)
            if (configured / "left4dead2" / "gameinfo.txt").exists():
                return configured

        for lib in libraries:
            manifest = lib / "steamapps" / f"appmanifest_{self.L4D2_APP_ID}.acf"
            if manifest.exists():
                try:
                    acf = vdf.loads(manifest.read_text(encoding="utf-8", errors="ignore"))
                    app_state = acf.get("AppState") or {}
                    install_dir = app_state.get("installdir", "Left 4 Dead 2")
                    candidate = lib / "steamapps" / "common" / install_dir
                    if (candidate / "left4dead2" / "gameinfo.txt").exists():
                        return candidate
                except Exception:
                    pass

            fallback = lib / "steamapps" / "common" / "Left 4 Dead 2"
            if (fallback / "left4dead2" / "gameinfo.txt").exists():
                return fallback

        return None

    def _resolve_authoring_binaries(
        self, l4d2_dir: Optional[Path], config: Optional[AppConfig]
    ) -> tuple[Optional[Path], Optional[Path]]:
        studiomdl: Optional[Path] = None
        vpk_exe: Optional[Path] = None

        if config:
            if config.studiomdl_executable:
                p = Path(config.studiomdl_executable)
                if p.exists():
                    studiomdl = p
            if config.vpk_executable:
                p = Path(config.vpk_executable)
                if p.exists():
                    vpk_exe = p

        if l4d2_dir:
            if studiomdl is None:
                candidate = l4d2_dir / "bin" / "studiomdl.exe"
                if candidate.exists():
                    studiomdl = candidate
            if vpk_exe is None:
                candidate = l4d2_dir / "bin" / "vpk.exe"
                if candidate.exists():
                    vpk_exe = candidate

        return studiomdl, vpk_exe
