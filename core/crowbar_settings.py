from __future__ import annotations

import os
import shutil
import xml.etree.ElementTree as ET
from pathlib import Path
from typing import Optional

import psutil


class CrowbarSettingsManager:
    """Validates and injects required Left 4 Dead 2 settings into Crowbar 0.74's XML config."""

    REQUIRED_DECOMPILE_SETTINGS: dict[str, str] = {
        "DecompileOutputFolderOption": "Subfolder",
        "DecompileOutputSubfolderName": "decompiled 0.74",
        "DecompileQcFileIsChecked": "true",
        "DecompileGroupIntoQciFilesIsChecked": "false",
        "DecompileQcSkinFamilyOnSingleLineIsChecked": "true",
        "DecompileQcOnlyChangedMaterialsInTextureGroupLinesIsChecked": "true",
        "DecompileQcIncludeDefineBoneLinesIsChecked": "true",
        "DecompileQcUseMixedCaseForKeywordsIsChecked": "false",
        "DecompileReferenceMeshSmdFileIsChecked": "true",
        "DecompileRemovePathFromSmdMaterialFileNamesIsChecked": "true",
        "DecompileUseNonValveUvConversionIsChecked": "false",
        "DecompileTextureBmpFilesIsChecked": "true",
        "DecompileLodMeshSmdFilesIsChecked": "true",
        "DecompilePhysicsMeshSmdFileIsChecked": "true",
        "DecompileVertexAnimationVtaFileIsChecked": "true",
        "DecompileProceduralBonesVrdFileIsChecked": "true",
        "DecompileBoneAnimationSmdFilesIsChecked": "true",
        "DecompileBoneAnimationPlaceInSubfolderIsChecked": "true",
        "DecompileFolderForEachModelIsChecked": "false",
        "DecompilePrefixFileNamesWithModelNameIsChecked": "false",
        "DecompileStricterFormatIsChecked": "false",
        "DecompileLogFileIsChecked": "false",
        "DecompileDebugInfoFilesIsChecked": "false",
        "DecompileDeclareSequenceQciFileIsChecked": "false",
        "DecompileOverrideMdlVersion": "DoNotOverride",
        "DecompileMode": "File",
    }

    REQUIRED_COMPILE_SETTINGS: dict[str, str] = {
        "CompileOutputFolderOption": "Subfolder",
        "CompileOutputSubfolderName": "compiled 0.74",
        "CompileOptionDefineBonesIsChecked": "false",
        "CompileOptionNoP4IsChecked": "true",
        "CompileOptionVerboseIsChecked": "true",
        "CompileMode": "File",
    }

    def __init__(self, settings_path: Optional[Path] = None) -> None:
        if settings_path is not None:
            self.settings_path = settings_path
        else:
            appdata = os.environ.get("APPDATA", str(Path.home() / "AppData" / "Roaming"))
            self.settings_path = Path(appdata) / "ZeqMacaw" / "Crowbar 0.74" / "Crowbar Settings.xml"

    @staticmethod
    def is_crowbar_running() -> bool:
        for proc in psutil.process_iter(["name"]):
            try:
                name = proc.info.get("name") or ""
                if name.lower() == "crowbar.exe":
                    return True
            except (psutil.NoSuchProcess, psutil.AccessDenied):
                continue
        return False

    def validate(self, l4d2_dir: Optional[Path] = None) -> tuple[bool, list[str]]:
        """Check whether Crowbar Settings.xml matches the required decompile/compile & L4D2 setup."""
        issues: list[str] = []
        if not self.settings_path.exists():
            return False, ["Crowbar Settings.xml does not exist yet."]

        try:
            tree = ET.parse(self.settings_path)
            root = tree.getroot()
        except Exception as exc:
            return False, [f"Failed to parse Crowbar Settings.xml: {exc}"]

        for key, expected in {**self.REQUIRED_DECOMPILE_SETTINGS, **self.REQUIRED_COMPILE_SETTINGS}.items():
            elem = root.find(key)
            if elem is None or (elem.text or "").strip() != expected:
                actual = elem.text if elem is not None else "<missing>"
                issues.append(f"{key}: expected '{expected}', got '{actual}'")

        l4d2_index, l4d2_node = self._find_l4d2_gamesetup(root)
        if l4d2_node is None:
            issues.append("GameSetup for 'Left 4 Dead 2' is missing.")
        else:
            if l4d2_dir is not None:
                expected_gameinfo = str(l4d2_dir / "left4dead2" / "gameinfo.txt")
                expected_studiomdl = str(l4d2_dir / "bin" / "studiomdl.exe")
                expected_vpk = str(l4d2_dir / "bin" / "vpk.exe")
                expected_hlmv = str(l4d2_dir / "bin" / "hlmv.exe")
                for tag, exp in (
                    ("GamePathFileName", expected_gameinfo),
                    ("CompilerPathFileName", expected_studiomdl),
                    ("PackerPathFileName", expected_vpk),
                    ("ViewerPathFileName", expected_hlmv),
                ):
                    node = l4d2_node.find(tag)
                    val = (node.text or "").strip() if node is not None else ""
                    if val.lower() != exp.lower():
                        issues.append(f"L4D2 {tag}: expected '{exp}', got '{val}'")

            for idx_tag in ("SetUpGamesGameSetupSelectedIndex", "CompileGameSetupSelectedIndex"):
                idx_node = root.find(idx_tag)
                if idx_node is None or (idx_node.text or "").strip() != str(l4d2_index):
                    issues.append(f"{idx_tag} is not pointing to Left 4 Dead 2 (index {l4d2_index}).")

        return len(issues) == 0, issues

    def apply(self, l4d2_dir: Optional[Path] = None, create_backup: bool = True) -> Path:
        """Create or update Crowbar Settings.xml with the verified configuration."""
        if self.is_crowbar_running():
            raise RuntimeError("Crowbar.exe is currently running. Close Crowbar before updating its settings.")

        self.settings_path.parent.mkdir(parents=True, exist_ok=True)
        if self.settings_path.exists():
            if create_backup:
                backup_path = self.settings_path.with_suffix(".xml.bak")
                shutil.copy2(self.settings_path, backup_path)
            tree = ET.parse(self.settings_path)
            root = tree.getroot()
        else:
            root = ET.Element(
                "AppSettings",
                {
                    "xmlns:xsi": "http://www.w3.org/2001/XMLSchema-instance",
                    "xmlns:xsd": "http://www.w3.org/2001/XMLSchema",
                },
            )
            tree = ET.ElementTree(root)

        for key, value in {**self.REQUIRED_DECOMPILE_SETTINGS, **self.REQUIRED_COMPILE_SETTINGS}.items():
            self._set_child_text(root, key, value)

        l4d2_index, l4d2_node = self._find_l4d2_gamesetup(root)
        if l4d2_node is None:
            game_setups = root.find("GameSetups")
            if game_setups is None:
                game_setups = ET.SubElement(root, "GameSetups")
            l4d2_node = ET.SubElement(game_setups, "GameSetup")
            self._set_child_text(l4d2_node, "GameName", "Left 4 Dead 2")
            self._set_child_text(l4d2_node, "GameEngine", "Source")
            l4d2_index = len(game_setups.findall("GameSetup")) - 1

        if l4d2_dir is not None:
            self._set_child_text(l4d2_node, "GamePathFileName", str(l4d2_dir / "left4dead2" / "gameinfo.txt"))
            self._set_child_text(l4d2_node, "GameAppPathFileName", str(l4d2_dir / "left4dead2.exe"))
            self._set_child_text(l4d2_node, "CompilerPathFileName", str(l4d2_dir / "bin" / "studiomdl.exe"))
            self._set_child_text(l4d2_node, "ViewerPathFileName", str(l4d2_dir / "bin" / "hlmv.exe"))
            self._set_child_text(l4d2_node, "MappingToolPathFileName", str(l4d2_dir / "bin" / "hammer.exe"))
            self._set_child_text(l4d2_node, "PackerPathFileName", str(l4d2_dir / "bin" / "vpk.exe"))

        if l4d2_index >= 0:
            self._set_child_text(root, "SetUpGamesGameSetupSelectedIndex", str(l4d2_index))
            self._set_child_text(root, "CompileGameSetupSelectedIndex", str(l4d2_index))

        ET.indent(tree, space="\t")
        tree.write(self.settings_path, encoding="utf-8", xml_declaration=True)
        return self.settings_path

    @staticmethod
    def _set_child_text(parent: ET.Element, tag: str, value: str) -> None:
        node = parent.find(tag)
        if node is None:
            node = ET.SubElement(parent, tag)
        node.text = value

    @staticmethod
    def _find_l4d2_gamesetup(root: ET.Element) -> tuple[int, Optional[ET.Element]]:
        game_setups = root.find("GameSetups")
        if game_setups is None:
            return -1, None
        for idx, setup in enumerate(game_setups.findall("GameSetup")):
            name_node = setup.find("GameName")
            if name_node is not None and (name_node.text or "").strip().lower() == "left 4 dead 2":
                return idx, setup
        return -1, None
