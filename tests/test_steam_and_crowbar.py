from __future__ import annotations

import json
import xml.etree.ElementTree as ET
from pathlib import Path

from core.config_manager import ConfigManager
from core.crowbar_settings import CrowbarSettingsManager
from core.models import AppConfig
from core.steam_locator import SteamLocator


def test_config_manager_migrates_legacy_settings(tmp_path: Path) -> None:
    fake_l4d2 = tmp_path / "Left 4 Dead 2"
    fake_bin = fake_l4d2 / "bin"
    fake_bin.mkdir(parents=True)
    vpk_exe = fake_bin / "vpk.exe"
    studiomdl_exe = fake_bin / "studiomdl.exe"
    vpk_exe.write_bytes(b"")
    studiomdl_exe.write_bytes(b"")

    settings_file = tmp_path / "settings.json"
    settings_file.write_text(
        json.dumps(
            {
                "vpk_executable": str(vpk_exe),
                "delete_folders_when_swap": True,
                "close_crowbar_when_swap": True,
            }
        ),
        encoding="utf-8",
    )

    mgr = ConfigManager(config_path=settings_file, project_root=tmp_path)
    cfg = mgr.load()

    assert cfg.vpk_executable == str(vpk_exe)
    assert cfg.l4d2_dir == str(fake_l4d2)
    assert cfg.studiomdl_executable == str(studiomdl_exe)
    assert cfg.output_dir == "Swapped_Survivors"

    cfg.first_run_completed = True
    cfg.theme = "Light"
    mgr.save(cfg)

    reloaded = mgr.load()
    assert reloaded.first_run_completed is True
    assert reloaded.theme == "Light"


def test_steam_locator_discovers_vdf_libraries_and_apps(tmp_path: Path) -> None:
    steam_dir = tmp_path / "Steam"
    (steam_dir / "steamapps").mkdir(parents=True)

    lib2 = tmp_path / "SteamLib2"
    l4d2_dir = lib2 / "steamapps" / "common" / "Left 4 Dead 2"
    (l4d2_dir / "left4dead2" / "addons").mkdir(parents=True)
    (l4d2_dir / "left4dead2" / "gameinfo.txt").write_text('"GameInfo" {}', encoding="utf-8")
    (l4d2_dir / "bin").mkdir(parents=True)
    (l4d2_dir / "bin" / "studiomdl.exe").write_bytes(b"")
    (l4d2_dir / "bin" / "vpk.exe").write_bytes(b"")

    (lib2 / "steamapps" / "appmanifest_550.acf").write_text(
        '"AppState"\n{\n\t"installdir"\t"Left 4 Dead 2"\n}\n',
        encoding="utf-8",
    )
    (lib2 / "steamapps" / "appmanifest_563.acf").write_text(
        '"AppState"\n{\n\t"installdir"\t"Left 4 Dead 2"\n}\n',
        encoding="utf-8",
    )

    escaped_lib2 = str(lib2).replace("\\", "\\\\")
    (steam_dir / "steamapps" / "libraryfolders.vdf").write_text(
        f'"libraryfolders"\n{{\n\t"0"\n\t{{\n\t\t"path"\t"{escaped_lib2}"\n\t}}\n}}\n',
        encoding="utf-8",
    )

    locator = SteamLocator(project_root=tmp_path)
    libs = locator.find_steam_libraries(steam_dir)
    assert any(p.resolve() == lib2.resolve() for p in libs)

    resolved_l4d2 = locator._resolve_l4d2_dir(libs, AppConfig())
    assert resolved_l4d2 is not None and resolved_l4d2.resolve() == l4d2_dir.resolve()
    assert locator._has_appmanifest(libs, "563") is True

    studiomdl, vpk_exe = locator._resolve_authoring_binaries(resolved_l4d2, AppConfig())
    assert studiomdl == resolved_l4d2 / "bin" / "studiomdl.exe"
    assert vpk_exe == resolved_l4d2 / "bin" / "vpk.exe"


def test_crowbar_settings_apply_creates_backup_and_validates(tmp_path: Path, monkeypatch) -> None:
    xml_path = tmp_path / "Crowbar 0.74" / "Crowbar Settings.xml"
    xml_path.parent.mkdir(parents=True)
    xml_path.write_text(
        """<?xml version="1.0" encoding="utf-8"?>
<AppSettings>
  <DecompileTextureBmpFilesIsChecked>false</DecompileTextureBmpFilesIsChecked>
  <GameSetups>
    <GameSetup>
      <GameName>Half-Life 2</GameName>
      <GameEngine>Source</GameEngine>
    </GameSetup>
    <GameSetup>
      <GameName>Left 4 Dead 2</GameName>
      <GameEngine>Source</GameEngine>
      <GamePathFileName>C:\\old\\gameinfo.txt</GamePathFileName>
    </GameSetup>
  </GameSetups>
  <SetUpGamesGameSetupSelectedIndex>0</SetUpGamesGameSetupSelectedIndex>
  <CompileGameSetupSelectedIndex>0</CompileGameSetupSelectedIndex>
</AppSettings>
""",
        encoding="utf-8",
    )

    l4d2_dir = tmp_path / "L4D2"
    mgr = CrowbarSettingsManager(settings_path=xml_path)
    monkeypatch.setattr(mgr, "is_crowbar_running", lambda: False)

    valid_before, issues_before = mgr.validate(l4d2_dir=l4d2_dir)
    assert valid_before is False
    assert len(issues_before) > 0

    mgr.apply(l4d2_dir=l4d2_dir, create_backup=True)

    backup = xml_path.with_suffix(".xml.bak")
    assert backup.exists()

    valid_after, issues_after = mgr.validate(l4d2_dir=l4d2_dir)
    assert valid_after is True
    assert issues_after == []

    tree = ET.parse(xml_path)
    root = tree.getroot()
    game_names = [n.text for n in root.findall("./GameSetups/GameSetup/GameName")]
    assert "Half-Life 2" in game_names
    assert "Left 4 Dead 2" in game_names
    assert root.findtext("DecompileQcUseMixedCaseForKeywordsIsChecked") == "false"
    assert root.findtext("DecompileGroupIntoQciFilesIsChecked") == "false"
    assert root.findtext("DecompileProceduralBonesVrdFileIsChecked") == "true"
    assert root.findtext("CompileGameSetupSelectedIndex") == "1"
