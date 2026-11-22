from __future__ import annotations

import os
import shutil
from pathlib import Path

import vpk

from core.addons_scanner import AddonsScanner
from core.app_meta import APP_META
from core.config_manager import ConfigManager
from core.i18n import TRANSLATIONS, LocalizationManager
from core.models import (
    AddonConflict,
    AppConfig,
    EnvironmentStatus,
    InstalledAddonEntry,
    ModMetadata,
    SurvivorId,
    SwapJobRequest,
    SwapTargetResult,
)
from core.steam_locator import SteamLocator
from core.survivors import SurvivorRegistry
from core.swap_engine import SwapEngine
from core.vpk_service import VpkService


def test_survivor_registry_fixes_ellis_and_has_unique_assets() -> None:
    specs = SurvivorRegistry.all()
    assert len(specs) == 8

    ellis = SurvivorRegistry.get(SurvivorId.ELLIS)
    assert '$includemodel "survivors/anim_mechanic.mdl"' in ellis.default_includemodels
    assert not any("anim_producer" in inc for inc in ellis.default_includemodels)

    louis = SurvivorRegistry.get(SurvivorId.LOUIS)
    assert '$includemodel "survivors/anim_Biker.mdl"' in louis.default_includemodels

    assert len({s.model_file for s in specs}) == 8
    assert len({s.fp_arms.mdl for s in specs}) == 8
    assert len({s.vgui.lobby_icon for s in specs}) == 8


def test_addoninfo_parse_and_serialize_roundtrip() -> None:
    svc = VpkService()
    sample = '''"AddonInfo"
{
    addontitle "Emma Frost (Zoey)"
    addonauthor "Someone"
    AddonDescription "Line 1
Line 2 with \\"quotes\\" inside"
    addonversion "1.2"
    addonSteamAppID 550
    addonContent_Survivor 1
}
'''
    meta = svc.parse_addoninfo_text(sample)
    assert meta.title == "Emma Frost (Zoey)"
    assert meta.author == "Someone"
    assert meta.version == "1.2"
    assert meta.steam_app_id == "550"

    serialized = svc.serialize_addoninfo(
        ModMetadata(
            title="Emma Frost (Coach)",
            version="2.0",
            description="Test\nDesc",
            author="Tester",
            author_steam_id="STEAM_0:0:123",
            url="https://example.com",
        )
    )
    assert 'AddonTitle\t\t"Emma Frost (Coach)"' in serialized
    assert "AddonContent_Survivor\t1" in serialized
    assert '"NAME"' not in serialized


def test_inspect_real_sample_vpks_if_present() -> None:
    svc = VpkService()
    emma = Path("Survivor_Swap") / "emma-zoey.vpk"
    roboco = Path("Survivor_Swap") / "roboco-louis.vpk"

    if emma.exists():
        info = svc.inspect_source(emma)
        assert info.detected_origin == SurvivorId.ZOEY
        assert info.has_arms is True
        assert info.has_vgui is True
        assert info.has_physics is False

    if roboco.exists():
        info = svc.inspect_source(roboco)
        assert info.detected_origin == SurvivorId.LOUIS
        assert info.has_arms is True
        assert info.has_vgui is True
        assert info.has_physics is False


def test_pyside6_gui_offscreen_smoke(tmp_path: Path, monkeypatch) -> None:
    os.environ["QT_QPA_PLATFORM"] = "offscreen"

    from PySide6.QtCore import Qt
    from PySide6.QtWidgets import QApplication
    from ui.main_window import MainWindow
    from ui.setup_wizard import SetupWizardDialog
    from ui.theme import L4d2ThemeManager
    from ui.widgets import DropZoneCard

    app = QApplication.instance() or QApplication([])
    assert app is not None

    cfg_path = tmp_path / "settings.json"
    cfg_mgr = ConfigManager(config_path=cfg_path, project_root=tmp_path)
    cfg = AppConfig(
        first_run_completed=True,
        output_dir=str(tmp_path / "out"),
        theme="System",
        language="en-US",
    )
    cfg_mgr.save(cfg)

    class DummyLocator(SteamLocator):
        def inspect_environment(self, config=None) -> EnvironmentStatus:
            return EnvironmentStatus(crowbar_settings_path=tmp_path / "Crowbar Settings.xml")

    monkeypatch.setattr("ui.main_window.ConfigManager", lambda project_root=None: cfg_mgr)
    monkeypatch.setattr("ui.main_window.SteamLocator", lambda project_root=None: DummyLocator(tmp_path))

    win = MainWindow(project_root=tmp_path)
    win.showMaximized()
    assert win.isMaximized() is True
    assert win.windowTitle() == f"{APP_META.name}  |  v{APP_META.version}"
    assert win.swap_page.hero_banner.title_label.text() == "L4D2 Survivor Swapper Tool"
    assert APP_META.developer == "Sr.Caveira"
    assert not hasattr(win.swap_page.hero_banner, "bio_badge")
    assert win.swap_page is not None
    assert win.environment_page is not None
    assert win.settings_page is not None

    assert win.swap_page.convert_btn.cursor().shape() == Qt.CursorShape.PointingHandCursor
    assert win.swap_page.origin_combo.currentIndex() == 0
    assert win.swap_page.origin_combo.currentData() is None
    assert win.swap_page.origin_combo.text() == "Not selected"
    assert all(b.isEnabled() for b in win.swap_page.dest_picker._buttons.values())
    assert not win.swap_page.dest_picker.btn_all.icon().isNull()
    assert not win.swap_page.dest_picker.btn_l4d1.icon().isNull()
    assert not win.swap_page.dest_picker.btn_l4d2.icon().isNull()
    assert not win.swap_page.dest_picker.btn_clear.icon().isNull()
    win.swap_page.dest_picker.set_origin_survivor(SurvivorId.ZOEY)
    assert win.swap_page.dest_picker._buttons[SurvivorId.ZOEY].cursor().shape() == Qt.CursorShape.ArrowCursor
    assert win.swap_page.dest_picker._buttons[SurvivorId.COACH].cursor().shape() == Qt.CursorShape.PointingHandCursor
    assert win.swap_page.dest_picker.l4d1_section_label.text() == "L4D1:"
    assert win.swap_page.dest_picker.l4d2_section_label.text() == "L4D2:"
    assert win.swap_page.dest_picker.l4d1_card.isVisible()
    assert win.swap_page.dest_picker.l4d2_card.isVisible()
    assert win.swap_page.dest_picker.l4d2_card.x() > win.swap_page.dest_picker.l4d1_card.x()

    win.swap_page.switch_arms.setChecked(True)
    assert win.swap_page.switch_arms.getText() == "Convert First-Person Arms"
    win.swap_page.switch_arms.setChecked(False)
    assert win.swap_page.switch_arms.getText() == "Convert First-Person Arms"

    assert win.swap_page.progress_card.toggle_log_btn.text() == "Show Log"
    win.swap_page.progress_card.update_progress(65, "Test step")
    assert win.swap_page.progress_card.percent_label.text() == "65%"
    assert "[ 65%] Test step" in win.swap_page.progress_card.log_view.toPlainText()

    win.apply_language_preference("pt-BR")
    assert win.swap_page.hero_banner.title_label.text() == "L4D2 Survivor Swapper Tool"
    assert TRANSLATIONS["pt-BR"]["origin_card_title"] == "Sobrevivente de Origem"
    assert win.swap_page.origin_combo.text() == "Não selecionado"
    assert win.swap_page.switch_arms.getText() == "Converter Braços (1ª Pessoa)"
    assert win.swap_page.progress_card.toggle_log_btn.text() == "Mostrar Log"
    win.swap_page.progress_card.toggle_log_btn.setChecked(True)
    assert win.swap_page.progress_card.toggle_log_btn.text() == "Ocultar Log"
    win.apply_language_preference("es-ES")
    assert win.swap_page.origin_combo.text() == "No seleccionado"
    assert win.swap_page.switch_arms.getText() == "Convertir Brazos (1ª Persona)"

    assert L4d2ThemeManager.detect_system_theme() in ("Dark", "Light")
    win.apply_theme_preference("Light")
    win.apply_theme_preference("Dark")
    win.apply_theme_preference("System")

    mod_folder = tmp_path / "mod"
    (mod_folder / "models" / "survivors").mkdir(parents=True)
    (mod_folder / "models" / "survivors" / "survivor_teenangst.mdl").write_bytes(b"")
    info = VpkService().inspect_source(mod_folder)
    assert isinstance(win.swap_page.drop_card, DropZoneCard)
    win.swap_page.drop_card.set_detected_info(info)
    win.swap_page._on_source_selected(mod_folder)
    assert not hasattr(win.swap_page, "preview_btn")

    wizard = SetupWizardDialog(
        config_mgr=cfg_mgr,
        steam_locator=DummyLocator(tmp_path),
        config=cfg,
        i18n=win.i18n,
        parent=win,
    )
    assert wizard.yesButton is not None
    wizard.close()
    win.close()


def test_i18n_translation_parity_and_detection() -> None:
    import re

    en_keys = set(TRANSLATIONS["en-US"].keys())
    pt_keys = set(TRANSLATIONS["pt-BR"].keys())
    es_keys = set(TRANSLATIONS["es-ES"].keys())

    assert "hero_tag" not in en_keys
    assert en_keys == pt_keys == es_keys

    plural_paren = re.compile(r"\((?:s|es|ns|o|a|os|as|aram)\)", re.I)
    for lang, table in TRANSLATIONS.items():
        for key, value in table.items():
            assert not plural_paren.search(value), f"{lang}:{key} still has '{value}'"

    pt_mgr = LocalizationManager("pt-BR")
    assert pt_mgr.tr_plural("addons_dlg_found", 1) == "1 mod de sobrevivente encontrado em addons e workshop."
    assert pt_mgr.tr_plural("addons_dlg_found", 3) == "3 mods de sobrevivente encontrados em addons e workshop."
    assert pt_mgr.tr_plural("info_cancelled_msg", 0) == "Conversão interrompida antes de concluir qualquer alvo."
    assert pt_mgr.tr_plural("info_cancelled_msg", 1) == "Conversão interrompida. 1 alvo já concluído foi mantido."
    assert pt_mgr.tr_plural("info_cancelled_msg", 2) == "Conversão interrompida. 2 alvos já concluídos foram mantidos."

    en_mgr = LocalizationManager("en-US")
    assert en_mgr.tr_plural("info_done_msg", 1) == "Generated 1 VPK file cleanly!"
    assert en_mgr.tr_plural("info_done_msg", 2) == "Generated 2 VPK files cleanly!"

    assert LocalizationManager.normalize_language("pt_BR") == "pt-BR"
    assert LocalizationManager.normalize_language("pt-PT") == "pt-BR"
    assert LocalizationManager.normalize_language("es_MX") == "es-ES"
    assert LocalizationManager.normalize_language("es-ES") == "es-ES"
    assert LocalizationManager.normalize_language("en_US") == "en-US"
    assert LocalizationManager.normalize_language("fr_FR") == "en-US"
    assert LocalizationManager.detect_system_language() in ("en-US", "pt-BR", "es-ES")


def test_swap_engine_format_vgui_and_mocked_run_job(tmp_path: Path, monkeypatch) -> None:
    zoey = SurvivorRegistry.get(SurvivorId.ZOEY)
    coach = SurvivorRegistry.get(SurvivorId.COACH)

    assert SwapEngine._format_output_name("emma-{survivor}", zoey, coach, title="Emma") == "emma-coach"
    assert SwapEngine._format_output_name("{title} ({display_name})", zoey, coach, title="Emma") == "Emma (Coach)"
    assert SwapEngine._format_output_name("Emma Zoey Skin", zoey, coach, multi_target=True) == "Emma Coach Skin"
    assert SwapEngine._sanitize_filename("Skin Name. ") == "Skin Name"

    cp1252_qc = tmp_path / "cp1252.qc"
    cp1252_qc.write_bytes('$cdmaterials "models/café/"\n'.encode("cp1252"))
    assert "café" in SwapEngine._read_text_safe(cp1252_qc)

    vgui_dir = tmp_path / "vgui"
    vgui_dir.mkdir()
    for icon in zoey.vgui.all_filenames():
        (vgui_dir / icon).write_bytes(b"VTF")
        (vgui_dir / Path(icon).with_suffix(".vmt")).write_bytes(b"VMT")

    SwapEngine._process_vgui_directory(vgui_dir, zoey, coach)
    remaining = sorted(p.name for p in vgui_dir.iterdir())
    assert remaining == sorted(coach.vgui.all_filenames())

    l4d2_dir = tmp_path / "L4D2"
    (l4d2_dir / "left4dead2" / "addons").mkdir(parents=True)
    (l4d2_dir / "left4dead2" / "gameinfo.txt").write_text('"GameInfo" {}', encoding="utf-8")
    (l4d2_dir / "bin").mkdir(parents=True)
    studiomdl = l4d2_dir / "bin" / "studiomdl.exe"
    vpk_exe = l4d2_dir / "bin" / "vpk.exe"
    decomp = tmp_path / "MdlDecompilerCli.exe"
    for p in (studiomdl, vpk_exe, decomp):
        p.write_bytes(b"")

    kit_dir = tmp_path / "kit"
    kit_coach_mdl = kit_dir / "replace_coach" / "models" / "survivors" / "survivor_coach.mdl"
    kit_coach_mdl.parent.mkdir(parents=True)
    kit_coach_mdl.write_bytes(b"")

    source_dir = tmp_path / "source_mod"
    (source_dir / "models" / "survivors").mkdir(parents=True)
    (source_dir / "models" / "survivors" / "survivor_teenangst.mdl").write_bytes(b"")
    (source_dir / "materials" / "models" / "custom").mkdir(parents=True)
    (source_dir / "materials" / "models" / "custom" / "tex.vtf").write_bytes(b"TEX")

    env = EnvironmentStatus(
        l4d2_dir=l4d2_dir,
        l4d2_gameinfo=l4d2_dir / "left4dead2" / "gameinfo.txt",
        l4d2_addons_dir=l4d2_dir / "left4dead2" / "addons",
        studiomdl_path=studiomdl,
        vpk_exe_path=vpk_exe,
        decompiler_cli_path=decomp,
        l4d2_installed=True,
        authoring_tools_installed=True,
    )
    engine = SwapEngine(env_status=env, kit_dir=kit_dir, i18n=LocalizationManager("pt-BR"))

    def fake_decompile(mdl_path: Path, output_dir: Path):
        output_dir.mkdir(parents=True, exist_ok=True)
        qc = output_dir / f"{mdl_path.stem}.qc"
        qc.write_text(
            f'$modelname "survivors/{mdl_path.name}"\n'
            '$body "body" "ref.smd"\n'
            '$sequence "Idle" { "anims/idle.smd" fps 30 }\n'
            '$declaresequence "WalkN"\n'
            '$sequence "ragdoll" { "anims/ragdoll.smd" fps 30 }\n'
            '$includemodel "survivors/anim_coach.mdl"\n',
            encoding="utf-8",
        )
        return qc, ["decompiled ok"]

    def fake_compile_qc(qc_path: Path, staging_game_dir: Path):
        surv_out = staging_game_dir / "models" / "survivors"
        surv_out.mkdir(parents=True, exist_ok=True)
        stem = qc_path.stem
        for ext in (".mdl", ".vvd", ".dx90.vtx"):
            (surv_out / f"{stem}{ext}").write_bytes(b"IDST")
        return ["compiled ok"]

    def fake_pack(source_dir: Path, output_vpk: Path, vpk_exe: Path):
        output_vpk.parent.mkdir(parents=True, exist_ok=True)
        output_vpk.write_bytes(b"VPK_STUB")
        return ["packed ok"]

    monkeypatch.setattr(engine.toolchain, "decompile", fake_decompile)
    monkeypatch.setattr(engine.toolchain, "compile_qc", fake_compile_qc)
    monkeypatch.setattr(engine.vpk_service, "pack_folder_to_vpk", fake_pack)

    out_dir = tmp_path / "out"
    events = []
    messages = []
    results = engine.run_job(
        SwapJobRequest(
            source_path=source_dir,
            origin=SurvivorId.ZOEY,
            destinations=[SurvivorId.COACH],
            output_name_template="test-{survivor}",
            metadata=ModMetadata(title="Test Skin", author="Tester"),
            output_dir=out_dir,
            install_to_addons=True,
            include_arms=False,
        ),
        progress_cb=lambda p: (events.append(p.percent), messages.append(p.message)),
    )

    assert len(results) == 1
    assert results[0].success is True
    assert results[0].vpk_path == out_dir / "test-coach.vpk"
    assert results[0].installed_path == l4d2_dir / "left4dead2" / "addons" / "test-coach.vpk"
    assert results[0].vpk_path.exists()
    assert results[0].installed_path.exists()
    assert events[-1] == 100
    assert messages[0].startswith("Preparando mod de origem")
    assert messages[-1] == "Conversão concluída."


def test_environment_autodetect_uses_success_popup_and_heals_stale_paths(tmp_path: Path, monkeypatch) -> None:
    os.environ["QT_QPA_PLATFORM"] = "offscreen"

    from PySide6.QtWidgets import QApplication
    from ui.main_window import MainWindow

    app = QApplication.instance() or QApplication([])
    assert app is not None

    valid_l4d2 = tmp_path / "NewL4D2"
    (valid_l4d2 / "left4dead2").mkdir(parents=True)
    (valid_l4d2 / "left4dead2" / "gameinfo.txt").write_text('"GameInfo" {}', encoding="utf-8")
    (valid_l4d2 / "bin").mkdir(parents=True)
    (valid_l4d2 / "bin" / "studiomdl.exe").write_bytes(b"")
    (valid_l4d2 / "bin" / "vpk.exe").write_bytes(b"")

    cfg_path = tmp_path / "settings.json"
    cfg_mgr = ConfigManager(config_path=cfg_path, project_root=tmp_path)
    cfg_mgr.save(
        AppConfig(
            l4d2_dir=r"Z:\NonExistent\Left 4 Dead 2",
            studiomdl_executable=r"Z:\NonExistent\studiomdl.exe",
            vpk_executable=r"Z:\NonExistent\vpk.exe",
            first_run_completed=True,
        )
    )

    class HealedLocator(SteamLocator):
        def inspect_environment(self, config=None) -> EnvironmentStatus:
            return EnvironmentStatus(
                l4d2_dir=valid_l4d2,
                l4d2_gameinfo=valid_l4d2 / "left4dead2" / "gameinfo.txt",
                l4d2_installed=True,
                studiomdl_path=valid_l4d2 / "bin" / "studiomdl.exe",
                vpk_exe_path=valid_l4d2 / "bin" / "vpk.exe",
                crowbar_settings_path=tmp_path / "Crowbar Settings.xml",
            )

    monkeypatch.setattr("ui.main_window.ConfigManager", lambda project_root=None: cfg_mgr)
    monkeypatch.setattr("ui.main_window.SteamLocator", lambda project_root=None: HealedLocator(tmp_path))

    called: list[str] = []
    monkeypatch.setattr("ui.environment_page.InfoBar.success", lambda *args, **kwargs: called.append(str(args[0])))

    win = MainWindow(project_root=tmp_path)
    assert win.config.l4d2_dir == str(valid_l4d2)
    assert win.config.studiomdl_executable == str(valid_l4d2 / "bin" / "studiomdl.exe")
    assert win.config.vpk_executable == str(valid_l4d2 / "bin" / "vpk.exe")

    win.environment_page._on_autodetect()
    assert len(called) == 1
    win.close()


def test_swap_engine_uses_safe_pack_dir_arms_fallback_and_install_error_handling(tmp_path: Path, monkeypatch) -> None:
    os.environ["QT_QPA_PLATFORM"] = "offscreen"

    from PySide6.QtWidgets import QApplication
    from core.models import SwapTargetResult
    from ui.main_window import MainWindow

    l4d2_dir = tmp_path / "L4D2"
    (l4d2_dir / "left4dead2" / "addons").mkdir(parents=True)
    (l4d2_dir / "left4dead2" / "gameinfo.txt").write_text('"GameInfo" {}', encoding="utf-8")
    (l4d2_dir / "bin").mkdir(parents=True)
    studiomdl = l4d2_dir / "bin" / "studiomdl.exe"
    vpk_exe = l4d2_dir / "bin" / "vpk.exe"
    decomp = tmp_path / "MdlDecompilerCli.exe"
    studiomdl.write_bytes(b"")
    vpk_exe.write_bytes(b"")
    decomp.write_bytes(b"")

    kit_dir = tmp_path / "kit"
    kit_mdl = kit_dir / "replace_coach" / "models" / "survivors" / "survivor_coach.mdl"
    kit_mdl.parent.mkdir(parents=True)
    kit_mdl.write_bytes(b"KIT")

    source_dir = tmp_path / "source_mod"
    (source_dir / "models" / "survivors").mkdir(parents=True)
    (source_dir / "models" / "survivors" / "survivor_teenangst.mdl").write_bytes(b"SRC")
    (source_dir / "models" / "weapons" / "arms").mkdir(parents=True)
    (source_dir / "models" / "weapons" / "arms" / "v_arms_zoey.mdl").write_bytes(b"ARMS")

    env = EnvironmentStatus(
        l4d2_dir=l4d2_dir,
        l4d2_gameinfo=l4d2_dir / "left4dead2" / "gameinfo.txt",
        l4d2_addons_dir=l4d2_dir / "left4dead2" / "addons",
        studiomdl_path=studiomdl,
        vpk_exe_path=vpk_exe,
        decompiler_cli_path=decomp,
        l4d2_installed=True,
        authoring_tools_installed=True,
    )
    engine = SwapEngine(env, kit_dir, i18n=LocalizationManager("en-US"))

    def fake_decompile(mdl_path: Path, out_dir: Path):
        if "v_arms_" in mdl_path.name.lower():
            raise RuntimeError("Corrupt v_arms")
        out_dir.mkdir(parents=True, exist_ok=True)
        qc = out_dir / f"{mdl_path.stem}.qc"
        if "teenangst" in mdl_path.name.lower():
            qc.write_text('$modelname "survivors/survivor_teenangst.mdl"\n$sequence "ragdoll" "a"', encoding="utf-8")
        else:
            qc.write_text('$modelname "survivors/survivor_coach.mdl"\n$sequence "ragdoll" "k"', encoding="utf-8")
        return qc, ["ok"]

    def fake_compile_qc(qc_path: Path, staging_game: Path):
        out_surv = staging_game / "models" / "survivors"
        out_surv.mkdir(parents=True, exist_ok=True)
        for ext in (".mdl", ".vvd", ".dx90.vtx"):
            (out_surv / f"survivor_coach{ext}").write_bytes(b"BIN")
        return ["ok"]

    packed_dirs: list[str] = []

    def fake_pack(source_dir: Path, output_vpk: Path, vpk_exe: Path):
        packed_dirs.append(source_dir.name)
        output_vpk.parent.mkdir(parents=True, exist_ok=True)
        output_vpk.write_bytes(b"VPK_STUB")
        return ["ok"]

    monkeypatch.setattr(engine.toolchain, "decompile", fake_decompile)
    monkeypatch.setattr(engine.toolchain, "compile_qc", fake_compile_qc)
    monkeypatch.setattr(engine.vpk_service, "pack_folder_to_vpk", fake_pack)

    real_copy2 = shutil.copy2

    def guarded_copy2(src, dst, *args, **kwargs):
        if Path(dst).parent == env.l4d2_addons_dir:
            raise PermissionError("Locked by L4D2")
        return real_copy2(src, dst, *args, **kwargs)

    monkeypatch.setattr("core.swap_engine.shutil.copy2", guarded_copy2)

    out_dir = tmp_path / "out"
    results = engine.run_job(
        SwapJobRequest(
            source_path=source_dir,
            origin=SurvivorId.ZOEY,
            destinations=[SurvivorId.COACH],
            output_name_template="Emma v1.2 ({display_name})",
            metadata=ModMetadata(title="Emma v1.2", author="Tester"),
            output_dir=out_dir,
            install_to_addons=True,
            include_arms=True,
        )
    )

    assert packed_dirs == ["pkg"]
    assert len(results) == 1
    assert results[0].success is True
    assert results[0].vpk_path == out_dir / "Emma v1.2 (Coach).vpk"
    assert results[0].installed_path is None
    assert any("v_arms" in w for w in results[0].warnings)
    assert any("addons" in w.lower() for w in results[0].warnings)

    app = QApplication.instance() or QApplication([])
    assert app is not None
    cfg_mgr = ConfigManager(config_path=tmp_path / "settings.json", project_root=tmp_path)
    cfg_mgr.save(AppConfig(first_run_completed=True))

    class AddonsLocator(SteamLocator):
        def inspect_environment(self, config=None) -> EnvironmentStatus:
            return env

    monkeypatch.setattr("ui.main_window.ConfigManager", lambda project_root=None: cfg_mgr)
    monkeypatch.setattr("ui.main_window.SteamLocator", lambda project_root=None: AddonsLocator(tmp_path))
    ui_errors: list[str] = []
    monkeypatch.setattr("ui.swap_page.InfoBar.error", lambda *args, **kwargs: ui_errors.append(str(args[0])))
    monkeypatch.setattr("ui.swap_page.shutil.copy2", guarded_copy2)

    win = MainWindow(project_root=tmp_path)
    win.swap_page._last_results = [
        SwapTargetResult(destination=SurvivorId.COACH, success=True, vpk_path=results[0].vpk_path)
    ]
    win.swap_page._on_install_last_results()
    assert len(ui_errors) == 1
    win.close()


def _build_test_vpk(
    staging: Path,
    out_vpk: Path,
    model_file: str,
    addon_title: str,
    preview_bytes: bytes | None = None,
) -> Path:
    if staging.exists():
        shutil.rmtree(staging)
    (staging / "models" / "survivors").mkdir(parents=True)
    (staging / "models" / "survivors" / model_file).write_bytes(b"MDL")
    (staging / "models" / "weapons" / "arms").mkdir(parents=True)
    (staging / "models" / "weapons" / "arms" / "v_arms_gambler_new.mdl").write_bytes(b"ARMS")
    (staging / "addoninfo.txt").write_text(
        f'"AddonInfo"\n{{\n\taddontitle "{addon_title}"\n\taddonversion "2.1"\n'
        f'\taddondescription "Sample skin description"\n\taddonauthor "Tester"\n'
        f'\taddontagline "Sample tagline"\n}}\n',
        encoding="utf-8",
    )
    if preview_bytes is not None:
        (staging / "addonimage.png").write_bytes(preview_bytes)
    out_vpk.parent.mkdir(parents=True, exist_ok=True)
    vpk.new(str(staging)).save(str(out_vpk))
    return out_vpk


def test_addons_scanner_scan_conflicts_and_update_addonlist(tmp_path: Path) -> None:
    l4d2_root = tmp_path / "Left 4 Dead 2" / "left4dead2"
    addons_dir = l4d2_root / "addons"
    workshop_dir = addons_dir / "workshop"
    addons_dir.mkdir(parents=True)

    active_nick = _build_test_vpk(
        tmp_path / "build_1",
        addons_dir / "active_nick.vpk",
        "survivor_gambler.mdl",
        "Active Nick Skin",
    )
    disabled_nick = _build_test_vpk(
        tmp_path / "build_2",
        workshop_dir / "123456.vpk",
        "survivor_gambler.mdl",
        "Disabled Workshop Nick",
    )
    non_survivor_vpk = tmp_path / "build_3"
    (non_survivor_vpk / "sound").mkdir(parents=True)
    (non_survivor_vpk / "sound" / "shot.wav").write_bytes(b"WAV")
    vpk.new(str(non_survivor_vpk)).save(str(addons_dir / "gun_sound.vpk"))

    addonlist_path = l4d2_root / "addonlist.txt"
    addonlist_path.write_text(
        '"AddonList"\n{\n\t"active_nick.vpk"\t\t"1"\n\t"workshop\\123456.vpk"\t\t"0"\n}\n',
        encoding="utf-8",
    )

    entries = AddonsScanner.scan_survivor_addons(addons_dir)
    assert len(entries) == 2
    by_path = {e.vpk_path: e for e in entries}
    assert by_path[active_nick].title == "Active Nick Skin"
    assert by_path[active_nick].version == "2.1"
    assert by_path[active_nick].description == "Sample skin description"
    assert by_path[active_nick].tagline == "Sample tagline"
    assert by_path[active_nick].has_arms is True
    assert by_path[active_nick].file_size_bytes > 0
    assert by_path[active_nick].enabled_in_game is True
    assert by_path[active_nick].source_kind == "addons"
    assert by_path[disabled_nick].enabled_in_game is False
    assert by_path[disabled_nick].source_kind == "workshop"

    conflicts = AddonsScanner.find_conflicts(addons_dir, [(SurvivorId.NICK, "new_nick.vpk")])
    assert len(conflicts) == 1
    assert conflicts[0].existing_addon.vpk_path == active_nick

    self_overwrite = AddonsScanner.find_conflicts(addons_dir, [(SurvivorId.NICK, "active_nick.vpk")])
    assert self_overwrite == []

    updated = AddonsScanner.update_addonlist(
        addons_dir,
        disable_entries=[conflicts[0].existing_addon],
        enable_filenames=["new_nick.vpk"],
    )
    assert updated == addonlist_path
    states = AddonsScanner.load_addonlist_states(addons_dir)
    assert states["active_nick.vpk"] is False
    assert states["new_nick.vpk"] is True
    assert states["workshop/123456.vpk"] is False


def test_swap_engine_cancellation_keeps_completed_and_cleans_temp(tmp_path: Path, monkeypatch) -> None:
    l4d2_dir = tmp_path / "L4D2"
    (l4d2_dir / "left4dead2").mkdir(parents=True)
    (l4d2_dir / "left4dead2" / "gameinfo.txt").write_text('"GameInfo" {}', encoding="utf-8")
    studiomdl = tmp_path / "studiomdl.exe"
    vpk_exe = tmp_path / "vpk.exe"
    decomp = tmp_path / "MdlDecompilerCli.exe"
    for tool_p in (studiomdl, vpk_exe, decomp):
        tool_p.write_bytes(b"")

    kit_dir = tmp_path / "kit"
    for folder, mdl in (
        ("replace_coach", "survivor_coach.mdl"),
        ("replace_nick", "survivor_gambler.mdl"),
    ):
        mdl_path = kit_dir / folder / "models" / "survivors" / mdl
        mdl_path.parent.mkdir(parents=True)
        mdl_path.write_bytes(b"")

    source_dir = tmp_path / "source_mod"
    (source_dir / "models" / "survivors").mkdir(parents=True)
    (source_dir / "models" / "survivors" / "survivor_teenangst.mdl").write_bytes(b"")

    env = EnvironmentStatus(
        l4d2_dir=l4d2_dir,
        l4d2_gameinfo=l4d2_dir / "left4dead2" / "gameinfo.txt",
        studiomdl_path=studiomdl,
        vpk_exe_path=vpk_exe,
        decompiler_cli_path=decomp,
        l4d2_installed=True,
        authoring_tools_installed=True,
    )
    engine = SwapEngine(env_status=env, kit_dir=kit_dir, i18n=LocalizationManager("en-US"))

    def fake_decompile(mdl_path: Path, output_dir: Path):
        output_dir.mkdir(parents=True, exist_ok=True)
        qc = output_dir / f"{mdl_path.stem}.qc"
        qc.write_text(
            f'$modelname "survivors/{mdl_path.name}"\n'
            '$body "body" "ref.smd"\n'
            '$sequence "Idle" { "anims/idle.smd" fps 30 }\n',
            encoding="utf-8",
        )
        (output_dir / "ref.smd").write_text("version 1\nnodes\n0 \"ValveBiped.Bip01_Pelvis\" -1\nend\nskeleton\ntime 0\n0 0 0 0 0 0 0\nend\ntriangles\nend\n", encoding="utf-8")
        (output_dir / "anims").mkdir(exist_ok=True)
        (output_dir / "anims" / "idle.smd").write_text("version 1\nnodes\nend\nskeleton\ntime 0\nend\n", encoding="utf-8")
        return qc, ["ok"]

    def fake_compile_qc(qc_path: Path, game_dir: Path):
        out_surv = game_dir / "models" / "survivors"
        out_surv.mkdir(parents=True, exist_ok=True)
        stem = qc_path.stem
        for ext in (".mdl", ".vvd", ".dx90.vtx"):
            (out_surv / f"{stem}{ext}").write_bytes(b"BIN")
        return ["ok"]

    cancel_flag = {"stop": False}

    def fake_pack(source_dir: Path, output_vpk: Path, vpk_exe: Path):
        output_vpk.parent.mkdir(parents=True, exist_ok=True)
        output_vpk.write_bytes(b"VPK_STUB")
        cancel_flag["stop"] = True
        return ["ok"]

    monkeypatch.setattr(engine.toolchain, "decompile", fake_decompile)
    monkeypatch.setattr(engine.toolchain, "compile_qc", fake_compile_qc)
    monkeypatch.setattr(engine.vpk_service, "pack_folder_to_vpk", fake_pack)

    out_dir = tmp_path / "out"
    custom_temp = tmp_path / "custom_tmp"
    custom_temp.mkdir()
    monkeypatch.setattr("core.swap_engine.tempfile.gettempdir", lambda: str(custom_temp))

    results = engine.run_job(
        SwapJobRequest(
            source_path=source_dir,
            origin=SurvivorId.ZOEY,
            destinations=[SurvivorId.COACH, SurvivorId.NICK],
            output_name_template="test-{survivor}",
            metadata=ModMetadata(title="Test"),
            output_dir=out_dir,
            include_arms=False,
            include_vgui=False,
        ),
        cancel_cb=lambda: cancel_flag["stop"],
    )

    assert len(results) == 2
    assert results[0].success is True
    assert results[0].vpk_path == out_dir / "test-coach.vpk"
    assert results[1].success is False
    assert results[1].cancelled is True
    assert not (out_dir / "test-nick.vpk").exists()
    assert list(custom_temp.glob("l4d2sw_*")) == []


def test_ui_addons_browser_cancel_and_conflict_dialogs(tmp_path: Path, monkeypatch) -> None:
    os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")
    from PySide6.QtWidgets import QApplication
    from ui.addons_browser_dialog import AddonConflictDialog, AddonsBrowserDialog
    from ui.main_window import MainWindow

    app = QApplication.instance() or QApplication([])
    assert app is not None

    from PySide6.QtCore import QBuffer, QIODevice
    from PySide6.QtGui import QColor, QImage

    img = QImage(32, 18, QImage.Format.Format_RGBA8888)
    img.fill(QColor(217, 43, 43))
    buf = QBuffer()
    buf.open(QIODevice.OpenModeFlag.WriteOnly)
    img.save(buf, "PNG")
    png_bytes = bytes(buf.data())

    l4d2_root = tmp_path / "Left 4 Dead 2" / "left4dead2"
    addons_dir = l4d2_root / "addons"
    existing_nick = _build_test_vpk(
        tmp_path / "exist_nick",
        addons_dir / "old_nick.vpk",
        "survivor_gambler.mdl",
        "Old Nick Mod",
        preview_bytes=png_bytes,
    )
    assert AddonsScanner.read_addon_preview_image(existing_nick) == png_bytes
    scanned_addons = AddonsScanner.scan_survivor_addons(addons_dir)
    assert len(scanned_addons) == 1
    assert scanned_addons[0].preview_bytes == png_bytes
    (l4d2_root / "gameinfo.txt").write_text('"GameInfo" {}', encoding="utf-8")
    studiomdl = tmp_path / "studiomdl.exe"
    vpk_exe = tmp_path / "vpk.exe"
    decomp = tmp_path / "MdlDecompilerCli.exe"
    for tool_p in (studiomdl, vpk_exe, decomp):
        tool_p.write_bytes(b"")

    env = EnvironmentStatus(
        l4d2_dir=tmp_path / "Left 4 Dead 2",
        l4d2_gameinfo=l4d2_root / "gameinfo.txt",
        l4d2_addons_dir=addons_dir,
        studiomdl_path=studiomdl,
        vpk_exe_path=vpk_exe,
        decompiler_cli_path=decomp,
        l4d2_installed=True,
        authoring_tools_installed=True,
    )
    cfg_mgr = ConfigManager(config_path=tmp_path / "settings.json", project_root=tmp_path)
    cfg_mgr.save(AppConfig(first_run_completed=True, language="en-US"))

    class BrowserLocator(SteamLocator):
        def inspect_environment(self, config=None) -> EnvironmentStatus:
            return env

    monkeypatch.setattr("ui.main_window.ConfigManager", lambda project_root=None: cfg_mgr)
    monkeypatch.setattr("ui.main_window.SteamLocator", lambda project_root=None: BrowserLocator(tmp_path))

    win = MainWindow(project_root=tmp_path)
    win.apply_theme_preference("Dark")
    win.show()
    app.processEvents()
    assert win.titleBar.minBtn.getNormalColor().lightness() > 200
    assert win.titleBar.maxBtn.getNormalColor().lightness() > 200
    assert win.titleBar.closeBtn.getNormalColor().lightness() > 200

    win.apply_theme_preference("Light")
    app.processEvents()
    assert win.titleBar.minBtn.getNormalColor().lightness() < 60
    assert win.stackedWidget.styleSheet() != ""

    win.apply_theme_preference("Dark")
    app.processEvents()
    assert win.titleBar.minBtn.getNormalColor().lightness() > 200
    assert win.stackedWidget.styleSheet() == ""

    win.swap_page.dest_picker._buttons[SurvivorId.NICK].setChecked(True)
    assert win.swap_page.install_btn.text() == "Install Result to L4D2 Addons"
    win.swap_page.dest_picker._buttons[SurvivorId.COACH].setChecked(True)
    assert win.swap_page.install_btn.text() == "Install Results to L4D2 Addons"

    monkeypatch.setattr(AddonsBrowserDialog, "exec", lambda dlg_self: (dlg_self.reject(), 0)[1])
    workshop_signals: list[bool] = []
    win.swap_page.drop_card.workshopRequested.connect(lambda: workshop_signals.append(True))
    win.swap_page.drop_card.browse_workshop_btn.click()
    assert workshop_signals == [True]

    assert win.swap_page.cancel_btn.isHidden()
    win.swap_page._set_busy(True)
    assert not win.swap_page.cancel_btn.isHidden()
    assert win.swap_page.cancel_btn.isEnabled()
    win.swap_page._set_busy(False)
    assert win.swap_page.cancel_btn.isHidden()

    entries = [
        InstalledAddonEntry(
            vpk_path=existing_nick,
            title="Old Nick Mod",
            author="AuthorOne",
            origin=SurvivorId.NICK,
            replaced_survivors=(SurvivorId.NICK,),
            source_kind="addons",
            enabled_in_game=True,
            version="2.1",
            description="Sample skin description",
            has_arms=True,
        ),
        InstalledAddonEntry(
            vpk_path=addons_dir / "workshop" / "999.vpk",
            title="Ellis Cyber Skin",
            author="AuthorTwo",
            origin=SurvivorId.ELLIS,
            replaced_survivors=(SurvivorId.ELLIS,),
            source_kind="workshop",
            enabled_in_game=True,
        ),
        InstalledAddonEntry(
            vpk_path=addons_dir / "workshop" / "555.vpk",
            title="Zoey Tactical",
            author="AuthorThree",
            origin=SurvivorId.ZOEY,
            replaced_survivors=(SurvivorId.ZOEY,),
            source_kind="workshop",
            enabled_in_game=True,
        ),
    ]
    from PySide6.QtCore import Qt
    from PySide6.QtWidgets import QLabel

    from ui.addon_ui_shared import CenteredIconHeaderView

    browser = AddonsBrowserDialog(addons_dir, i18n=win.i18n, parent=win, auto_scan=False)
    browser.populate_entries(entries)
    assert isinstance(browser.mod_table.horizontalHeader(), CenteredIconHeaderView)
    assert browser.mod_table.rowCount() == 3
    assert browser.mod_table.columnCount() == 5
    assert all(not browser.mod_table.horizontalHeaderItem(c).icon().isNull() for c in range(5))
    assert browser.mod_table.item(0, 4).text() == "Enabled"
    assert not browser.yesButton.icon().isNull()
    assert not browser.cancelButton.icon().isNull()
    assert browser.yesButton.cursor().shape() == Qt.CursorShape.ArrowCursor
    assert browser.cancelButton.cursor().shape() == Qt.CursorShape.PointingHandCursor

    thumb_cell_0 = browser.mod_table.cellWidget(0, 0)
    assert thumb_cell_0 is not None
    thumb_lbl_0 = thumb_cell_0.findChild(QLabel)
    assert thumb_lbl_0 is not None and not thumb_lbl_0.pixmap().isNull()

    thumb_cell_1 = browser.mod_table.cellWidget(1, 0)
    assert thumb_cell_1 is not None
    thumb_lbl_1 = thumb_cell_1.findChild(QLabel)
    assert thumb_lbl_1 is not None and thumb_lbl_1.text() == "—"

    addons_src_idx = browser.source_combo.findData("addons")
    workshop_src_idx = browser.source_combo.findData("workshop")
    assert addons_src_idx >= 0 and workshop_src_idx >= 0
    browser.source_combo.setCurrentIndex(addons_src_idx)
    assert browser.mod_table.rowCount() == 1
    assert browser.mod_table.item(0, 3).text() == "Old Nick Mod"
    browser.source_combo.setCurrentIndex(workshop_src_idx)
    assert browser.mod_table.rowCount() == 2
    browser.source_combo.setCurrentIndex(0)

    l4d1_idx = browser.filter_combo.findData("GEN:L4D1")
    l4d2_idx = browser.filter_combo.findData("GEN:L4D2")
    assert l4d1_idx >= 0 and l4d2_idx >= 0
    browser.filter_combo.setCurrentIndex(l4d1_idx)
    assert browser.mod_table.rowCount() == 1
    assert browser.mod_table.item(0, 3).text() == "Zoey Tactical"

    browser.filter_combo.setCurrentIndex(l4d2_idx)
    assert browser.mod_table.rowCount() == 2

    browser.filter_combo.setCurrentIndex(0)
    browser.search_edit.setText("old nick")
    assert browser.mod_table.rowCount() == 1
    browser.mod_table.selectRow(0)
    assert browser.yesButton.isEnabled()
    assert browser.yesButton.cursor().shape() == Qt.CursorShape.PointingHandCursor
    assert not browser.preview_image_label.pixmap().isNull()
    assert not browser.zoom_btn.isHidden()
    assert browser.preview_title_label.text() == "Old Nick Mod"
    assert "Sample skin description" in browser.preview_meta_label.text()
    assert "Version: 2.1" in browser.preview_meta_label.text()

    from ui.addons_browser_dialog import AddonImageZoomDialog

    zoom_opened: list[bool] = []

    def fake_zoom_exec(dlg_self) -> int:
        zoom_opened.append(not dlg_self.zoom_image_label.pixmap().isNull())
        dlg_self.reject()
        return 0

    monkeypatch.setattr(AddonImageZoomDialog, "exec", fake_zoom_exec)
    browser.zoom_btn.click()
    assert zoom_opened == [True]

    browser.search_edit.setText("ellis")
    assert browser.mod_table.rowCount() == 1
    browser.mod_table.selectRow(0)
    assert browser.selected_entry().title == "Ellis Cyber Skin"
    assert browser.preview_image_label.text() == "No preview image in .vpk"
    assert browser.zoom_btn.isHidden()
    browser.close()

    assert not hasattr(win.swap_page, "required_hint_label")
    assert "*" not in win.swap_page.drop_card.title_label.text()
    assert "*" not in win.swap_page.origin_label.text()
    assert "Optional" in win.swap_page.meta_card.headerLabel.text()

    win.swap_page._on_source_selected(existing_nick)
    assert win.swap_page.origin_combo.currentData() == SurvivorId.NICK
    assert not win.swap_page.dest_picker._buttons[SurvivorId.NICK].isEnabled()
    assert win.swap_page.cover_status_label.text() == "Original from mod"
    assert not win.swap_page.cover_thumb_label.pixmap().isNull()
    assert not win.swap_page.cover_zoom_badge.isHidden()
    assert not win.swap_page.reset_cover_btn.isEnabled()

    win.swap_page.origin_combo.setCurrentIndex(0)
    assert win.swap_page.origin_combo.currentData() is None
    assert all(b.isEnabled() for b in win.swap_page.dest_picker._buttons.values())
    warn_titles: list[str] = []
    monkeypatch.setattr("ui.swap_page.InfoBar.warning", lambda *args, **kwargs: warn_titles.append(str(args[0])))
    win.swap_page._on_start_conversion()
    assert warn_titles == ["No Origin Selected"]

    zoom_opened.clear()
    monkeypatch.setattr("ui.swap_page.ImageZoomDialog.exec", fake_zoom_exec)
    win.swap_page.cover_thumb_label.clicked.emit()
    assert zoom_opened == [True]

    custom_cover = tmp_path / "my_cover.png"
    custom_cover.write_bytes(png_bytes)
    monkeypatch.setattr(
        "ui.swap_page.QFileDialog.getOpenFileName",
        lambda *args, **kwargs: (str(custom_cover), ""),
    )
    win.swap_page._on_choose_cover_image()
    assert win.swap_page._custom_addonimage_path == custom_cover
    assert "my_cover.png" in win.swap_page.cover_status_label.text()
    assert win.swap_page.reset_cover_btn.isEnabled()

    win.swap_page._on_reset_cover_image()
    assert win.swap_page._custom_addonimage_path is None
    assert win.swap_page.cover_status_label.text() == "Original from mod"

    origin_stage = tmp_path / "cover_origin"
    pack_stage = tmp_path / "cover_pack"
    staging_game = tmp_path / "cover_game"
    (origin_stage / "models" / "survivors").mkdir(parents=True)
    (origin_stage / "addonimage.jpg").write_bytes(b"OLD_JPG")
    (staging_game / "models" / "survivors").mkdir(parents=True)
    for ext in (".mdl", ".vvd", ".dx90.vtx"):
        (staging_game / "models" / "survivors" / f"survivor_coach{ext}").write_bytes(b"BIN")
    cover_engine = SwapEngine(env_status=env, kit_dir=tmp_path / "kit")
    cover_engine._assemble_pack_directory(
        request=SwapJobRequest(
            source_path=origin_stage,
            origin=SurvivorId.NICK,
            destinations=[SurvivorId.COACH],
            output_name_template="out-{survivor}",
            metadata=ModMetadata(title="Test"),
            output_dir=tmp_path,
            include_arms=False,
            include_vgui=False,
            custom_addonimage_path=custom_cover,
        ),
        origin_spec=SurvivorRegistry.get(SurvivorId.NICK),
        dest_spec=SurvivorRegistry.get(SurvivorId.COACH),
        origin_mod_dir=origin_stage,
        staging_game=staging_game,
        pack_dir=pack_stage,
        has_physics=False,
    )
    assert not (pack_stage / "addonimage.jpg").exists()
    assert (pack_stage / "addonimage.png").read_bytes() == png_bytes

    conflict_item = AddonConflict(
        target_survivor=SurvivorId.NICK,
        new_vpk_name="new_nick.vpk",
        existing_addon=entries[0],
    )
    conflict_dlg = AddonConflictDialog([conflict_item], i18n=win.i18n, parent=win)
    assert not conflict_dlg.yesButton.icon().isNull()
    assert not conflict_dlg.cancelButton.icon().isNull()
    assert conflict_dlg.validate() is True
    assert conflict_dlg.choice == "disable_and_install"
    conflict_dlg._choose_install_anyway()
    assert conflict_dlg.choice == "install_anyway"
    conflict_dlg.reject()
    assert conflict_dlg.choice == "cancel"

    new_vpk = tmp_path / "new_nick.vpk"
    new_vpk.write_bytes(b"NEW_VPK")
    win.swap_page._last_results = [
        SwapTargetResult(destination=SurvivorId.NICK, success=True, vpk_path=new_vpk)
    ]

    class FakeDisableConflictDlg:
        def __init__(self, *args, **kwargs):
            self.choice = "disable_and_install"

        def exec(self) -> int:
            return 1

    success_msgs: list[str] = []
    monkeypatch.setattr("ui.swap_page.AddonConflictDialog", FakeDisableConflictDlg)
    monkeypatch.setattr("ui.swap_page.InfoBar.success", lambda *args, **kwargs: success_msgs.append(str(args[1])))

    win.swap_page._on_install_last_results()
    assert (addons_dir / "new_nick.vpk").exists()
    states = AddonsScanner.load_addonlist_states(addons_dir)
    assert states["old_nick.vpk"] is False
    assert states["new_nick.vpk"] is True
    assert len(success_msgs) == 1

    from ui.error_dialog import ErrorDetailsDialog

    assert not win.swap_page.progress_card.toggle_log_btn.icon().isNull()
    assert win.swap_page.progress_card.toggle_log_btn.text() == "Show Log"
    win.swap_page.progress_card.toggle_log_btn.click()
    assert win.swap_page.progress_card.toggle_log_btn.text() == "Hide Log"
    assert not win.swap_page.progress_card.toggle_log_btn.icon().isNull()

    assert not win.swap_page.progress_card.copy_log_btn.isEnabled()
    assert win.swap_page.progress_card.copy_log_btn.cursor().shape() == Qt.CursorShape.ArrowCursor
    win.swap_page.progress_card.append_log("StudioMDL test output line")
    assert win.swap_page.progress_card.copy_log_btn.isEnabled()
    assert win.swap_page.progress_card.copy_log_btn.cursor().shape() == Qt.CursorShape.PointingHandCursor
    win.swap_page.progress_card.copy_log_btn.click()
    assert "StudioMDL test output line" in QApplication.clipboard().text()
    assert win.swap_page.progress_card.copy_log_btn.text() == "Copied!"

    err_dlg = ErrorDetailsDialog(
        title="Conversion Failed",
        summary="studiomdl failed",
        details="studiomdl failed\nLine 2 detail",
        i18n=win.i18n,
        parent=win,
    )
    assert not err_dlg.cancelButton.icon().isNull()
    assert err_dlg.details_view.toPlainText() == "studiomdl failed\nLine 2 detail"
    err_dlg.copy_btn.click()
    assert QApplication.clipboard().text() == "studiomdl failed\nLine 2 detail"
    assert err_dlg.copy_btn.text() == "Copied!"
    err_dlg.close()

    shown_errors: list[tuple[str, str]] = []

    def fake_err_exec(dlg_self) -> int:
        shown_errors.append((dlg_self.summary_label.text(), dlg_self.full_error_text()))
        dlg_self.reject()
        return 0

    monkeypatch.setattr(ErrorDetailsDialog, "exec", fake_err_exec)
    win.swap_page._on_worker_finished(
        [
            SwapTargetResult(
                destination=SurvivorId.NICK,
                success=False,
                error_message="studiomdl exited 1\ndetails",
                logs=["line A", "line B"],
            )
        ]
    )
    assert len(shown_errors) == 1
    assert shown_errors[0][0] == "studiomdl exited 1"
    assert "line B" in shown_errors[0][1]

    win.swap_page._on_worker_failed("Critical crash\nTraceback line")
    assert len(shown_errors) == 2
    assert shown_errors[1][0] == "Critical crash"
    win.close()


def _make_synthetic_vtf(width: int, height: int, fmt: int, payload: bytes, mipmaps: int = 1) -> bytes:
    import struct

    hdr = bytearray(80)
    hdr[0:4] = b"VTF\x00"
    struct.pack_into("<III", hdr, 4, 7, 2, 80)
    struct.pack_into("<HHIIH", hdr, 16, width, height, 0, 1, 0)
    struct.pack_into("<iBiBB", hdr, 52, fmt, mipmaps, -1, 0, 0)
    struct.pack_into("<H", hdr, 63, 1)
    return bytes(hdr) + payload


def test_vtf_decoder_and_vgui_preview(tmp_path: Path, monkeypatch) -> None:
    os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")
    from PySide6.QtWidgets import QApplication
    from core.vtf_decoder import decode_vtf_to_rgba, extract_vgui_previews
    from ui.widgets import ImageZoomDialog, VguiPreviewStrip

    app = QApplication.instance() or QApplication([])
    assert app is not None

    rgba_payload = bytes([255, 0, 0, 255] * 16)
    info_r, w, h, out_r, err_r = decode_vtf_to_rgba(_make_synthetic_vtf(4, 4, 0, rgba_payload))
    assert err_r == "" and info_r is not None and (w, h) == (4, 4)
    assert out_r[:4] == b"\xff\x00\x00\xff"

    bgra_payload = bytes([10, 20, 30, 200] * 16)
    info_b, _, _, out_b, err_b = decode_vtf_to_rgba(_make_synthetic_vtf(4, 4, 12, bgra_payload))
    assert err_b == "" and info_b is not None
    assert out_b[:4] == bytes([30, 20, 10, 200])

    dxt1_block = b"\x00\xf8\xe0\x07" + b"\x00\x00\x00\x00"
    info_d1, _, _, out_d1, err_d1 = decode_vtf_to_rgba(_make_synthetic_vtf(4, 4, 13, dxt1_block))
    assert err_d1 == "" and info_d1 is not None and len(out_d1) == 64
    assert out_d1[0] == 255 and out_d1[2] == 0

    dxt5_block = b"\x80\x80" + b"\x00" * 6 + b"\x1f\x00\x1f\x00" + b"\x00\x00\x00\x00"
    info_d5, _, _, out_d5, err_d5 = decode_vtf_to_rgba(_make_synthetic_vtf(4, 4, 15, dxt5_block))
    assert err_d5 == "" and info_d5 is not None and len(out_d5) == 64
    assert out_d5[2] == 255 and out_d5[3] == 128

    mod_dir = tmp_path / "vgui_mod"
    vgui_dir = mod_dir / "materials" / "vgui"
    vgui_dir.mkdir(parents=True)
    (vgui_dir / "s_panel_lobby_gambler.vtf").write_bytes(_make_synthetic_vtf(4, 4, 15, dxt5_block))
    (vgui_dir / "s_panel_lobby_gambler.vmt").write_text(
        '"UnlitGeneric"\n{\n\t"$basetexture" "vgui/s_panel_lobby_gambler"\n}\n',
        encoding="utf-8",
    )
    (vgui_dir / "s_panel_gambler.vtf").write_bytes(_make_synthetic_vtf(4, 4, 12, bgra_payload))

    items = extract_vgui_previews(mod_dir, origin=SurvivorId.NICK)
    assert len(items) == 2
    assert items[0].slot_role == "lobby_icon"
    assert items[0].vmt_shader == "UnlitGeneric"
    assert items[0].vmt_basetexture == "vgui/s_panel_lobby_gambler"
    assert items[1].slot_role == "in_game_icon"

    strip = VguiPreviewStrip(LocalizationManager("pt-BR"))
    strip.set_items(items)
    assert not strip.isHidden()
    assert "2 texturas" in strip.title_lbl.text()

    from PySide6.QtGui import QPixmap

    opened_zoom: list[str] = []
    monkeypatch.setattr(ImageZoomDialog, "exec", lambda d: (opened_zoom.append(d.title_label.text()), d.reject())[1] or 0)
    strip._open_zoom(QPixmap(4, 4), items[0])
    assert len(opened_zoom) == 1 and "Ícone de Lobby" in opened_zoom[0]
    strip.close()


def test_archive_validation_drop_and_unpack(tmp_path: Path) -> None:
    import zipfile
    from core.archive_service import ArchiveSourceManager

    empty_dir = tmp_path / "empty_folder"
    empty_dir.mkdir()
    (empty_dir / "readme.txt").write_text("hi", encoding="utf-8")
    res_empty = ArchiveSourceManager.prepare_source(empty_dir)
    assert res_empty.valid is False
    assert res_empty.error_key == "err_drop_invalid_folder"

    non_surv_vpk = tmp_path / "map_only.vpk"
    src_map = tmp_path / "map_src"
    (src_map / "maps").mkdir(parents=True)
    (src_map / "maps" / "c1m1.bsp").write_bytes(b"MAP")
    import vpk as vpklib

    vpklib.new(str(src_map)).save(str(non_surv_vpk))
    res_nonsurv = ArchiveSourceManager.prepare_source(non_surv_vpk)
    assert res_nonsurv.valid is False
    assert res_nonsurv.error_key == "err_drop_not_survivor_vpk"

    nested_dir = tmp_path / "outer_mod"
    (nested_dir / "inner_skin" / "models" / "survivors").mkdir(parents=True)
    (nested_dir / "inner_skin" / "models" / "survivors" / "survivor_coach.mdl").write_bytes(b"")
    res_nested = ArchiveSourceManager.prepare_source(nested_dir)
    assert res_nested.valid is True
    assert res_nested.resolved_path == nested_dir / "inner_skin"

    zip_path = tmp_path / "skin_bundle.zip"
    with zipfile.ZipFile(zip_path, "w") as zf:
        zf.writestr("models/survivors/survivor_namvet.mdl", b"MDL")
    res_zip = ArchiveSourceManager.prepare_source(zip_path)
    try:
        assert res_zip.valid is True
        assert res_zip.resolved_path is not None
        assert (res_zip.resolved_path / "models" / "survivors" / "survivor_namvet.mdl").exists()
    finally:
        if res_zip.temp_dir:
            import shutil

            shutil.rmtree(res_zip.temp_dir, ignore_errors=True)

    multi_zip = tmp_path / "multi_vpk.zip"
    vpk_a = _build_test_vpk(tmp_path / "va", tmp_path / "a.vpk", "survivor_gambler.mdl", "Nick Skin")
    vpk_b = _build_test_vpk(tmp_path / "vb", tmp_path / "b.vpk", "survivor_producer.mdl", "Rochelle Skin")
    with zipfile.ZipFile(multi_zip, "w") as zf:
        zf.write(vpk_a, arcname="nick.vpk")
        zf.write(vpk_b, arcname="rochelle.vpk")
    res_multi = ArchiveSourceManager.prepare_source(multi_zip)
    try:
        assert res_multi.valid is True
        assert len(res_multi.candidate_vpks) == 2
    finally:
        if res_multi.temp_dir:
            import shutil

            shutil.rmtree(res_multi.temp_dir, ignore_errors=True)

    txt_file = tmp_path / "notes.txt"
    txt_file.write_text("x", encoding="utf-8")
    assert ArchiveSourceManager.is_supported_drop_path(txt_file) is False
    assert ArchiveSourceManager.is_supported_drop_path(zip_path) is True
    assert ArchiveSourceManager.is_supported_drop_path(tmp_path / "missing.rar") is False


def test_addons_loadout_page_history_and_launch_l4d2(tmp_path: Path, monkeypatch) -> None:
    os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")
    from PySide6.QtWidgets import QApplication
    from core.history_manager import HistoryManager
    from ui.main_window import MainWindow

    app = QApplication.instance() or QApplication([])
    assert app is not None

    l4d2_root = tmp_path / "Left 4 Dead 2" / "left4dead2"
    addons_dir = l4d2_root / "addons"
    addons_dir.mkdir(parents=True, exist_ok=True)
    (l4d2_root / "gameinfo.txt").write_text('"GameInfo" {}', encoding="utf-8")
    vpk_nick = _build_test_vpk(tmp_path / "s_nick", addons_dir / "nick_a.vpk", "survivor_gambler.mdl", "Nick Alpha")
    _build_test_vpk(tmp_path / "s_zoey1", addons_dir / "zoey_1.vpk", "survivor_teenangst.mdl", "Zoey One")
    _build_test_vpk(tmp_path / "s_zoey2", addons_dir / "workshop" / "900.vpk", "survivor_teenangst.mdl", "Zoey Two")

    studiomdl = tmp_path / "studiomdl.exe"
    vpk_exe = tmp_path / "vpk.exe"
    decomp = tmp_path / "MdlDecompilerCli.exe"
    for t in (studiomdl, vpk_exe, decomp):
        t.write_bytes(b"")

    env = EnvironmentStatus(
        l4d2_dir=tmp_path / "Left 4 Dead 2",
        l4d2_gameinfo=l4d2_root / "gameinfo.txt",
        l4d2_addons_dir=addons_dir,
        studiomdl_path=studiomdl,
        vpk_exe_path=vpk_exe,
        decompiler_cli_path=decomp,
        l4d2_installed=True,
        authoring_tools_installed=True,
    )
    cfg_mgr = ConfigManager(config_path=tmp_path / "settings.json", project_root=tmp_path)
    cfg_mgr.save(AppConfig(first_run_completed=True, language="en-US"))

    class StaticLocator(SteamLocator):
        def inspect_environment(self, config=None) -> EnvironmentStatus:
            return env

    monkeypatch.setattr("ui.main_window.ConfigManager", lambda project_root=None: cfg_mgr)
    monkeypatch.setattr("ui.main_window.SteamLocator", lambda project_root=None: StaticLocator(tmp_path))

    opened_urls: list[str] = []
    monkeypatch.setattr("ui.addon_ui_shared.QDesktopServices.openUrl", lambda url: opened_urls.append(url.toString()) or True)

    win = MainWindow(project_root=tmp_path)
    win.show()

    win.swap_page.launch_l4d2_btn.click()
    assert opened_urls == ["steam://rungameid/550"]

    warns: list[str] = []
    monkeypatch.setattr("ui.swap_page.InfoBar.warning", lambda *a, **kw: warns.append(str(a[0])))
    bad_folder = tmp_path / "not_a_mod"
    bad_folder.mkdir()
    win.swap_page._on_source_selected(bad_folder)
    assert warns == ["Invalid Mod Source"]

    entries = AddonsScanner.scan_survivor_addons(addons_dir)
    win.addons_page.populate_entries(entries)
    assert win.addons_page.mod_table.rowCount() == 3
    assert "Active: Nick Alpha" in win.addons_page._slot_cards[SurvivorId.NICK].status_label.text()
    assert "2 active (conflict)" in win.addons_page._slot_cards[SurvivorId.ZOEY].status_label.text()
    assert "Default" in win.addons_page._slot_cards[SurvivorId.BILL].status_label.text()

    from PySide6.QtCore import QEvent, QPointF
    from PySide6.QtGui import QEnterEvent
    from ui.theme import COLORS

    card_nick = win.addons_page._slot_cards[SurvivorId.NICK]
    assert "background: transparent;" in card_nick.name_label.styleSheet()
    assert (
        COLORS.dark_text in card_nick.name_label.styleSheet()
        or COLORS.light_text in card_nick.name_label.styleSheet()
    )
    card_nick.enterEvent(QEnterEvent(QPointF(8, 8), QPointF(8, 8), QPointF(8, 8)))
    assert card_nick._hover_anim.endValue() == 1.0
    card_nick.leaveEvent(QEvent(QEvent.Type.Leave))
    assert card_nick._hover_anim.endValue() == 0.0

    win.addons_page._on_slot_card_clicked(SurvivorId.NICK)
    assert card_nick._selected is True
    assert win.addons_page.mod_table.rowCount() == 1
    win.addons_page._on_slot_card_clicked(SurvivorId.NICK)
    assert card_nick._selected is False
    assert win.addons_page.mod_table.rowCount() == 3
    win.addons_page._on_slot_card_clicked(SurvivorId.NICK)
    assert win.addons_page.mod_table.rowCount() == 1
    win.addons_page.mod_table.selectRow(0)
    win.addons_page._on_toggle_selected()
    assert AddonsScanner.load_addonlist_states(addons_dir)["nick_a.vpk"] is False
    win.addons_page._on_toggle_selected()
    assert AddonsScanner.load_addonlist_states(addons_dir)["nick_a.vpk"] is True

    monkeypatch.setattr("ui.addons_page.MessageBox.exec", lambda self_dlg: 1)
    win.addons_page._on_delete_selected()
    assert not vpk_nick.exists()

    out_vpk = tmp_path / "out_ellis.vpk"
    out_vpk.write_bytes(b"PACKED")
    win.swap_page._current_job_meta = {
        "mod_title": "Test History Skin",
        "author": "Tester",
        "source_path": str(addons_dir / "zoey_1.vpk"),
        "origin": SurvivorId.ZOEY.value,
        "destinations": [SurvivorId.ELLIS.value],
        "output_dir": str(tmp_path),
        "installed_to_addons": False,
        "custom_cover_used": False,
    }
    win.swap_page._on_worker_finished(
        [SwapTargetResult(destination=SurvivorId.ELLIS, success=True, vpk_path=out_vpk)]
    )
    hist_mgr = HistoryManager(project_root=tmp_path)
    assert len(hist_mgr.load()) == 1
    assert win.history_page.history_table.rowCount() == 1
    assert win.history_page.history_table.columnCount() == 5
    from ui.addon_ui_shared import CenteredIconHeaderView

    assert isinstance(win.addons_page.mod_table.horizontalHeader(), CenteredIconHeaderView)
    assert isinstance(win.history_page.history_table.horizontalHeader(), CenteredIconHeaderView)
    assert all(not win.addons_page.mod_table.horizontalHeaderItem(c).icon().isNull() for c in range(5))
    assert all(not win.history_page.history_table.horizontalHeaderItem(c).icon().isNull() for c in range(5))
    assert win.history_page.history_table.cellWidget(0, 1) is not None
    assert win.history_page.history_table.item(0, 2).text() == "Test History Skin"

    win.history_page._on_install_outputs()
    assert (addons_dir / "out_ellis.vpk").exists()

    reopened: list[Path] = []
    win.history_page.reopenSourceRequested.connect(lambda p: reopened.append(p))
    win.history_page._on_reopen_source()
    assert reopened == [addons_dir / "zoey_1.vpk"]

    win.history_page._on_remove_selected()
    assert len(hist_mgr.load()) == 0
    win.close()


def test_smart_placeholders_filename_metadata_and_swap_preview(tmp_path: Path) -> None:
    os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")
    from PySide6.QtWidgets import QApplication
    from core.history_manager import HistoryManager
    from ui.swap_page import SwapPage

    app = QApplication.instance() or QApplication([])
    assert app is not None

    zoey = SurvivorRegistry.get(SurvivorId.ZOEY)
    ellis = SurvivorRegistry.get(SurvivorId.ELLIS)

    rendered = SwapEngine.render_placeholders(
        "{orig_title}_{origin}_to_{survivor}_{generation}_{origin_generation}_{survivor_id}",
        zoey,
        ellis,
        orig_title="Emma Frost",
    )
    assert rendered == "Emma Frost_Zoey_to_Ellis_L4D2_L4D1_survivor_mechanic"

    out_name = SwapEngine._format_output_name(
        "{orig_title}_{origin}_{survivor}",
        zoey,
        ellis,
        multi_target=True,
        title="Emma Frost",
    )
    assert out_name == "Emma Frost_zoey_ellis"

    meta = SwapEngine._build_target_metadata(
        ModMetadata(
            title="{orig_title} ({survivor} - {generation})",
            description="Converted from {origin} ({origin_generation}) to {survivor}",
            original_title="Emma Frost",
        ),
        zoey,
        ellis,
    )
    assert meta.title == "Emma Frost (Ellis - L4D2)"
    assert meta.description == "Converted from Zoey (L4D1) to Ellis"

    cfg_mgr = ConfigManager(config_path=tmp_path / "settings.json", project_root=tmp_path)
    cfg = AppConfig(first_run_completed=True, language="en-US")
    cfg_mgr.save(cfg)
    page = SwapPage(
        config_mgr=cfg_mgr,
        get_config_fn=lambda: cfg,
        get_env_fn=lambda: EnvironmentStatus(),
        i18n=LocalizationManager("en-US"),
        history_mgr=HistoryManager(project_root=tmp_path),
    )
    page.origin_combo.setCurrentIndex(4)
    page.dest_picker._buttons[SurvivorId.NICK].setChecked(True)
    page.output_name_edit.setText("{orig_title}-{survivor}")
    page.addon_title_edit.setText("{orig_title} ({generation})")
    preview_txt = page.tags_preview_label.text()
    assert "My Mod-nick.vpk" in preview_txt
    assert "My Mod (L4D2)" in preview_txt

    from qfluentwidgets import Theme, setTheme
    from ui.widgets import (
        HandIconWidget,
        _HAND_PALETTES,
        _l4d1_hand_silhouette,
        _l4d2_hand_silhouette,
    )

    hand_icons = page.dest_picker.findChildren(HandIconWidget)
    assert len(hand_icons) == 2
    assert [icon._generation for icon in hand_icons] == ["L4D1", "L4D2"]
    assert _HAND_PALETTES["L4D1"] != _HAND_PALETTES["L4D2"]
    assert _l4d1_hand_silhouette() != _l4d2_hand_silhouette()
    try:
        for theme in (Theme.DARK, Theme.LIGHT):
            setTheme(theme)
            assert all(not icon.grab().isNull() for icon in hand_icons)
    finally:
        setTheme(Theme.DARK)
    assert page.dest_picker._buttons[SurvivorId.ZOEY]._gender == "female"
    assert page.dest_picker._buttons[SurvivorId.ROCHELLE]._gender == "female"
    assert page.dest_picker._buttons[SurvivorId.BILL]._gender == "male"
    assert page.dest_picker._buttons[SurvivorId.NICK]._gender == "male"
    page.close()


def test_addons_browser_multi_select_mode(tmp_path: Path) -> None:
    os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")
    from PySide6.QtCore import QItemSelectionModel
    from PySide6.QtWidgets import QApplication, QWidget
    from ui.addons_browser_dialog import AddonsBrowserDialog

    app = QApplication.instance() or QApplication([])
    assert app is not None

    addons_dir = tmp_path / "addons"
    addons_dir.mkdir()
    v1 = _build_test_vpk(tmp_path / "m1", addons_dir / "zoey_m.vpk", "survivor_teenangst.mdl", "Zoey Mod")
    v2 = _build_test_vpk(tmp_path / "m2", addons_dir / "nick_m.vpk", "survivor_gambler.mdl", "Nick Mod")

    entries = [
        InstalledAddonEntry(
            vpk_path=v1,
            title="Zoey Mod",
            author="A",
            origin=SurvivorId.ZOEY,
            replaced_survivors=(SurvivorId.ZOEY,),
            source_kind="addons",
            enabled_in_game=True,
            file_size_bytes=100,
        ),
        InstalledAddonEntry(
            vpk_path=v2,
            title="Nick Mod",
            author="B",
            origin=SurvivorId.NICK,
            replaced_survivors=(SurvivorId.NICK,),
            source_kind="addons",
            enabled_in_game=True,
            file_size_bytes=100,
        ),
    ]
    host = QWidget()
    host.resize(960, 720)
    dlg = AddonsBrowserDialog(
        addons_dir=addons_dir,
        i18n=LocalizationManager("en-US"),
        parent=host,
        auto_scan=False,
        multi_select=True,
    )
    dlg.populate_entries(entries)
    sel_model = dlg.mod_table.selectionModel()
    idx0 = dlg.mod_table.model().index(0, 1)
    idx1 = dlg.mod_table.model().index(1, 1)
    sel_model.select(idx0, QItemSelectionModel.SelectionFlag.Select | QItemSelectionModel.SelectionFlag.Rows)
    sel_model.select(idx1, QItemSelectionModel.SelectionFlag.Select | QItemSelectionModel.SelectionFlag.Rows)
    assert dlg.validate() is True
    picked = dlg.selected_entries()
    assert len(picked) == 2
    assert {p.vpk_path for p in picked} == {v1, v2}
    dlg.close()


def test_batch_queue_global_override_conversion_history_and_cancel(tmp_path: Path, monkeypatch) -> None:
    os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")
    import time
    import zipfile
    from PySide6.QtWidgets import QApplication
    from core.history_manager import HistoryManager
    from ui.main_window import MainWindow

    app = QApplication.instance() or QApplication([])
    assert app is not None

    l4d2_root = tmp_path / "Left 4 Dead 2" / "left4dead2"
    addons_dir = l4d2_root / "addons"
    addons_dir.mkdir(parents=True, exist_ok=True)
    (l4d2_root / "gameinfo.txt").write_text('"GameInfo" {}', encoding="utf-8")

    studiomdl = tmp_path / "studiomdl.exe"
    vpk_exe = tmp_path / "vpk.exe"
    decomp = tmp_path / "MdlDecompilerCli.exe"
    for tool in (studiomdl, vpk_exe, decomp):
        tool.write_bytes(b"")

    env = EnvironmentStatus(
        l4d2_dir=tmp_path / "Left 4 Dead 2",
        l4d2_gameinfo=l4d2_root / "gameinfo.txt",
        l4d2_addons_dir=addons_dir,
        studiomdl_path=studiomdl,
        vpk_exe_path=vpk_exe,
        decompiler_cli_path=decomp,
        l4d2_installed=True,
        authoring_tools_installed=True,
    )
    cfg_mgr = ConfigManager(config_path=tmp_path / "settings.json", project_root=tmp_path)
    cfg_mgr.save(AppConfig(first_run_completed=True, output_dir=str(tmp_path / "out"), language="en-US"))

    class StaticLocator(SteamLocator):
        def inspect_environment(self, config=None) -> EnvironmentStatus:
            return env

    monkeypatch.setattr("ui.main_window.ConfigManager", lambda project_root=None: cfg_mgr)
    monkeypatch.setattr("ui.main_window.SteamLocator", lambda project_root=None: StaticLocator(tmp_path))
    monkeypatch.setattr("ui.batch_page.InfoBar.success", lambda *a, **kw: None)
    monkeypatch.setattr("ui.batch_page.InfoBar.warning", lambda *a, **kw: None)

    v_zoey = _build_test_vpk(tmp_path / "vz", tmp_path / "zoey_pack.vpk", "survivor_teenangst.mdl", "Zoey Pack")
    v_bill = _build_test_vpk(tmp_path / "vb", tmp_path / "bill_pack.vpk", "survivor_namvet.mdl", "Bill Pack")
    pack_zip = tmp_path / "bundle.zip"
    with zipfile.ZipFile(pack_zip, "w") as zf:
        zf.write(v_zoey, arcname="zoey_pack.vpk")
        zf.write(v_bill, arcname="bill_pack.vpk")

    win = MainWindow(project_root=tmp_path)
    win._wizard_timer.stop()
    win.show()

    assert win.batch_page.add_sources([pack_zip]) == 2
    assert win.batch_page.queue_table.rowCount() == 2

    win.batch_page._global_buttons[SurvivorId.ELLIS].setChecked(True)
    win.batch_page._global_buttons[SurvivorId.COACH].setChecked(True)
    win.batch_page.global_title_edit.setText("{orig_title} - {survivor}")
    win.batch_page.apply_global_defaults_to_all()

    win.batch_page.queue_table.selectRow(1)
    win.batch_page.use_global_dests_chk.setChecked(False)
    for sid, btn in win.batch_page._item_dest_buttons.items():
        if btn.isEnabled():
            btn.setChecked(sid == SurvivorId.LOUIS)
    win.batch_page.item_title_edit.setText("Custom Louis ({generation})")
    win.batch_page.item_author_edit.setText("CustomAuthor")

    recorded_requests: list[SwapJobRequest] = []

    def fake_run_job(self_eng, request: SwapJobRequest, progress_cb=None, keep_temp_on_error=False, cancel_cb=None):
        recorded_requests.append(request)
        out = []
        for dest in request.destinations:
            p = request.output_dir / f"{request.source_path.stem}_{dest.value}.vpk"
            p.parent.mkdir(parents=True, exist_ok=True)
            p.write_bytes(b"VPK")
            out.append(SwapTargetResult(destination=dest, success=True, vpk_path=p))
        return out

    monkeypatch.setattr("ui.batch_page.SwapEngine.run_job", fake_run_job)
    monkeypatch.setattr("ui.batch_page.ConversionConfirmDialog.exec", lambda self: False)
    win.batch_page._on_start_batch()
    app.processEvents()
    assert recorded_requests == []
    assert win.batch_page._worker_thread is None

    monkeypatch.setattr("ui.batch_page.ConversionConfirmDialog.exec", lambda self: True)
    win.batch_page._on_start_batch()

    deadline = time.time() + 10.0
    while win.batch_page._worker_thread is not None and time.time() < deadline:
        app.processEvents()
        time.sleep(0.01)
    app.processEvents()

    assert len(recorded_requests) == 2
    assert recorded_requests[0].destinations == [SurvivorId.COACH, SurvivorId.ELLIS] or set(recorded_requests[0].destinations) == {SurvivorId.ELLIS, SurvivorId.COACH}
    assert recorded_requests[1].destinations == [SurvivorId.LOUIS]
    assert recorded_requests[1].metadata.author == "CustomAuthor"
    assert recorded_requests[1].metadata.title == "Custom Louis ({generation})"
    assert all(it.status == "done" for it in win.batch_page._items)

    hist = HistoryManager(project_root=tmp_path).load()
    assert len(hist) == 2

    cancel_calls = []

    def fake_cancel_run_job(self_eng, request: SwapJobRequest, progress_cb=None, keep_temp_on_error=False, cancel_cb=None):
        cancel_calls.append(request.source_path.name)
        win.batch_page._on_cancel_batch()
        assert cancel_cb is not None and cancel_cb() is True
        return [SwapTargetResult(destination=d, success=False, cancelled=True) for d in request.destinations]

    monkeypatch.setattr("ui.batch_page.SwapEngine.run_job", fake_cancel_run_job)
    win.batch_page._on_start_batch()
    deadline = time.time() + 10.0
    while win.batch_page._worker_thread is not None and time.time() < deadline:
        app.processEvents()
        time.sleep(0.01)
    app.processEvents()

    assert len(cancel_calls) == 1
    assert win.batch_page._items[0].status == "cancelled"
    assert win.batch_page.convert_btn.isEnabled() is True
    win.close()


def test_origin_sanitization_mismatch_alerts_light_models_and_workshop_thumb(tmp_path: Path, monkeypatch) -> None:
    os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")
    from PySide6.QtWidgets import QApplication
    from ui.main_window import MainWindow

    app = QApplication.instance() or QApplication([])
    assert app is not None

    nick = SurvivorRegistry.get(SurvivorId.NICK)
    coach = SurvivorRegistry.get(SurvivorId.COACH)
    zoey = SurvivorRegistry.get(SurvivorId.ZOEY)
    francis = SurvivorRegistry.get(SurvivorId.FRANCIS)
    louis = SurvivorRegistry.get(SurvivorId.LOUIS)

    assert SwapEngine.clean_origin_from_text("doaxvv-shizuku-Black-Curiosity(nick) (Nick)", nick) == "doaxvv-shizuku-Black-Curiosity"
    assert SwapEngine.clean_origin_from_text("CJ (Coach)", coach) == "CJ"
    assert SwapEngine.clean_origin_from_text("Claire Redfield RE Revelations 2 ( Francis )", francis) == "Claire Redfield RE Revelations 2"
    assert SwapEngine.clean_origin_from_text("Dexter Morgan as Louis", louis) == "Dexter Morgan"
    assert SwapEngine.clean_origin_from_text("Nick => Mafia Leon", nick) == "Mafia Leon"

    sanitized_meta = SwapEngine._build_target_metadata(
        ModMetadata(
            title="{orig_title} ({survivor})",
            original_title="doaxvv-shizuku-Black-Curiosity(nick) (Nick)",
        ),
        nick,
        coach,
        sanitize_origin=True,
    )
    assert sanitized_meta.title == "doaxvv-shizuku-Black-Curiosity (Coach)"

    unsanitized_meta = SwapEngine._build_target_metadata(
        ModMetadata(
            title="{orig_title} ({survivor})",
            original_title="doaxvv-shizuku-Black-Curiosity(nick) (Nick)",
        ),
        nick,
        coach,
        sanitize_origin=False,
    )
    assert unsanitized_meta.title == "doaxvv-shizuku-Black-Curiosity(nick) (Nick) (Coach)"

    sanitized_file = SwapEngine._format_output_name(
        "{orig_title}-{survivor}",
        nick,
        coach,
        title="doaxvv-shizuku-Black-Curiosity(nick) (Nick)",
        sanitize_origin=True,
    )
    assert sanitized_file == "doaxvv-shizuku-Black-Curiosity-coach"

    l4d2_root = tmp_path / "Left 4 Dead 2" / "left4dead2"
    addons_dir = l4d2_root / "addons"
    workshop_dir = addons_dir / "workshop"
    workshop_dir.mkdir(parents=True, exist_ok=True)
    (l4d2_root / "gameinfo.txt").write_text('"GameInfo" {}', encoding="utf-8")

    ws_vpk = workshop_dir / "2927771290.vpk"
    ws_raw_dir = tmp_path / "ws_noinfo" / "models" / "survivors"
    ws_raw_dir.mkdir(parents=True, exist_ok=True)
    (ws_raw_dir / "survivor_mechanic.mdl").write_bytes(b"MDL")
    vpk.new(str(tmp_path / "ws_noinfo")).save(str(ws_vpk))
    ws_thumb = workshop_dir / "2927771290.jpg"
    ws_thumb.write_bytes(b"FAKEJPEGDATA")
    assert AddonsScanner.read_addon_preview_image(ws_vpk) == b"FAKEJPEGDATA"
    entries = AddonsScanner.scan_survivor_addons(addons_dir)
    assert len(entries) == 1
    assert entries[0].title == "2927771290"
    assert entries[0].preview_bytes == b"FAKEJPEGDATA"

    light_src = tmp_path / "light_mod"
    (light_src / "models" / "survivors").mkdir(parents=True, exist_ok=True)
    (light_src / "models" / "survivors" / "survivor_teenangst.mdl").write_bytes(b"MDL")
    (light_src / "models" / "survivors" / "survivor_teenangst_light.mdl").write_bytes(b"LIGHTMDL")
    (light_src / "addoninfo.txt").write_text('"AddonInfo"\n{\n    addontitle "Ashley 2B (Zoey)"\n}\n', encoding="utf-8")
    light_vpk = tmp_path / "light_test.vpk"
    vpk.new(str(light_src)).save(str(light_vpk))

    inspected = VpkService().inspect_source(light_vpk)
    assert inspected.detected_origin == SurvivorId.ZOEY
    assert inspected.has_light_models is True
    assert inspected.light_models == ["models/survivors/survivor_teenangst_light.mdl"]

    studiomdl = tmp_path / "studiomdl.exe"
    vpk_exe = tmp_path / "vpk.exe"
    decomp = tmp_path / "MdlDecompilerCli.exe"
    for tool in (studiomdl, vpk_exe, decomp):
        tool.write_bytes(b"")

    env = EnvironmentStatus(
        l4d2_dir=tmp_path / "Left 4 Dead 2",
        l4d2_gameinfo=l4d2_root / "gameinfo.txt",
        l4d2_addons_dir=addons_dir,
        studiomdl_path=studiomdl,
        vpk_exe_path=vpk_exe,
        decompiler_cli_path=decomp,
        l4d2_installed=True,
        authoring_tools_installed=True,
    )
    cfg_mgr = ConfigManager(config_path=tmp_path / "settings.json", project_root=tmp_path)
    cfg_mgr.save(AppConfig(first_run_completed=True, output_dir=str(tmp_path / "out"), language="en-US"))

    class StaticLocator(SteamLocator):
        def inspect_environment(self, config=None) -> EnvironmentStatus:
            return env

    popups: list[str] = []
    monkeypatch.setattr("ui.main_window.ConfigManager", lambda project_root=None: cfg_mgr)
    monkeypatch.setattr("ui.main_window.SteamLocator", lambda project_root=None: StaticLocator(tmp_path))
    monkeypatch.setattr("ui.swap_page.InfoBar.warning", lambda title, msg, **kw: popups.append(msg))
    monkeypatch.setattr("ui.batch_page.InfoBar.warning", lambda title, msg, **kw: popups.append(msg))

    win = MainWindow(project_root=tmp_path)
    win._wizard_timer.stop()
    win.show()

    assert len(win._nav_convert_group.treeChildren) == 2
    assert win.swap_page.help_arms.toolTip() != ""
    assert win.swap_page.help_sanitize_origin.toolTip() != ""

    win.swap_page._on_source_selected(light_vpk)
    assert win.swap_page.light_warning_banner.isHidden() is False
    assert win.swap_page.origin_warning_banner.isHidden() is True
    assert win.swap_page.weapons_option_row.isHidden() is True

    popups.clear()
    win.swap_page.origin_combo.setCurrentIndex(1)
    assert win.swap_page.origin_warning_banner.isHidden() is False
    assert len(popups) == 1

    win.batch_page.add_sources([light_vpk])
    win.batch_page.queue_table.selectRow(0)
    assert win.batch_page.global_weapons_row.isHidden() is True
    assert win.batch_page.item_weapons_row.isHidden() is True
    assert win.batch_page.item_light_warning.isHidden() is False
    assert win.batch_page.item_origin_warning.isHidden() is True
    popups.clear()
    win.batch_page.item_origin_combo.setCurrentIndex(1)
    assert win.batch_page.item_origin_warning.isHidden() is False
    assert "Bill (" in win.batch_page.queue_table.item(0, 2).text()
    assert len(popups) == 1

    weap_src = tmp_path / "with_weapon"
    (weap_src / "models" / "survivors").mkdir(parents=True, exist_ok=True)
    (weap_src / "models" / "survivors" / "survivor_gambler.mdl").write_bytes(b"MDL")
    (weap_src / "models" / "weapons" / "melee").mkdir(parents=True, exist_ok=True)
    (weap_src / "models" / "weapons" / "melee" / "v_katana.mdl").write_bytes(b"WEAP")
    weap_vpk = tmp_path / "with_weapon.vpk"
    vpk.new(str(weap_src)).save(str(weap_vpk))

    win.swap_page._on_source_selected(weap_vpk)
    assert win.swap_page.weapons_option_row.isHidden() is True
    assert win.swap_page.options_group.assets_card.isVisible()
    assert win.swap_page.options_group.output_card.isVisible()

    win.swap_page.dest_picker._buttons[SurvivorId.ELLIS].setChecked(True)
    win.swap_page.dest_picker._buttons[SurvivorId.COACH].setChecked(True)
    win.swap_page.dest_picker._buttons[SurvivorId.ZOEY].setChecked(True)
    win.swap_page.output_name_edit.setText("{orig_title}-{survivor}")
    win.swap_page.addon_title_edit.setText("{orig_title} ({survivor})")
    multi_preview = win.swap_page.tags_preview_label.text()
    assert "Preview (3 files):" in multi_preview
    assert "Zoey:" in multi_preview
    assert "Coach:" in multi_preview
    assert "Ellis:" in multi_preview

    for d in (SurvivorId.BILL, SurvivorId.LOUIS, SurvivorId.FRANCIS, SurvivorId.ROCHELLE):
        win.swap_page.dest_picker._buttons[d].setChecked(True)
    seven_preview = win.swap_page.tags_preview_label.text()
    assert "Preview (7 files):" in seven_preview
    assert "+3 more" in seven_preview
    assert "Ellis:" in win.swap_page.tags_preview_label.toolTip()

    win.swap_page.progress_card.update_progress(50, "Halfway")
    win.swap_page.clear_swap_btn.click()
    assert win.swap_page._detected_info is None
    assert win.swap_page.origin_combo.currentIndex() == 0
    assert win.swap_page.dest_picker.selected_survivors() == []
    assert win.swap_page.output_name_edit.text() == ""
    assert win.swap_page.addon_title_edit.text() == ""
    assert win.swap_page.weapons_option_row.isHidden() is True
    assert win.swap_page.progress_card.progress_bar.value() == 0
    assert win.swap_page.progress_card.status_label.text() == "Ready."
    assert "Preview (sample" in win.swap_page.tags_preview_label.text()
    assert "no target selected" in win.swap_page.tags_preview_label.text()

    win.batch_page.add_sources([weap_vpk])
    win.batch_page.queue_table.selectRow(1)
    assert win.batch_page.global_weapons_row.isHidden() is True
    assert win.batch_page.item_weapons_row.isHidden() is True
    assert win.batch_page.global_options_group.assets_card.isHidden() is False
    assert win.batch_page.global_options_group.output_card.isHidden() is False
    assert win.batch_page.item_options_group.assets_card.isHidden() is False
    assert win.batch_page.item_options_group.output_card.isHidden() is False
    win.close()


def test_table_thumbnail_click_opens_zoom_without_blocking_empty_row_selection(
    tmp_path: Path, monkeypatch
) -> None:
    os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")
    from PySide6.QtCore import QBuffer, QIODevice, Qt
    from PySide6.QtGui import QColor, QImage
    from PySide6.QtTest import QTest
    from PySide6.QtWidgets import QApplication, QLabel, QVBoxLayout, QWidget

    from ui.addon_ui_shared import create_styled_mod_table, populate_addon_table
    from ui.widgets import ClickableImageLabel, ImageZoomDialog

    app = QApplication.instance() or QApplication([])
    i18n = LocalizationManager("en-US")

    img = QImage(64, 48, QImage.Format.Format_RGBA8888)
    img.fill(QColor(220, 140, 40))
    buf = QBuffer()
    buf.open(QIODevice.OpenModeFlag.WriteOnly)
    img.save(buf, "PNG")
    png_bytes = bytes(buf.data())

    vpk0 = tmp_path / "no_img.vpk"
    vpk1 = tmp_path / "with_img.vpk"
    vpk0.write_bytes(b"")
    vpk1.write_bytes(b"")

    entries = [
        InstalledAddonEntry(
            vpk_path=vpk0,
            title="No Image Mod",
            author="Tester",
            origin=SurvivorId.ZOEY,
            source_kind="addons",
            enabled_in_game=True,
        ),
        InstalledAddonEntry(
            vpk_path=vpk1,
            title="Clickable Zoom Mod",
            author="Tester",
            origin=SurvivorId.NICK,
            source_kind="workshop",
            enabled_in_game=True,
            preview_bytes=png_bytes,
        ),
    ]

    host = QWidget()
    host.resize(820, 420)
    lay = QVBoxLayout(host)
    table = create_styled_mod_table(host, ["Preview", "Folder", "Survivor", "Mod", "Status"], 300)
    lay.addWidget(table)
    populate_addon_table(table, entries, i18n, lambda e: e.preview_bytes)
    host.show()
    app.processEvents()

    opened_modals: list[tuple[str, bool]] = []

    def fake_zoom_exec(dlg_self: ImageZoomDialog) -> int:
        opened_modals.append(
            (dlg_self.title_label.text(), not dlg_self.zoom_image_label.pixmap().isNull())
        )
        dlg_self.reject()
        return 0

    monkeypatch.setattr(ImageZoomDialog, "exec", fake_zoom_exec)

    table.selectRow(1)
    app.processEvents()

    empty_cell = table.cellWidget(0, 0)
    assert empty_cell is not None
    assert empty_cell.findChild(ClickableImageLabel) is None
    empty_lbl = empty_cell.findChild(QLabel)
    assert empty_lbl is not None
    assert empty_cell.rect().contains(empty_lbl.geometry())
    empty_center = empty_cell.mapTo(table.viewport(), empty_cell.rect().center())
    assert table.viewport().childAt(empty_center) is None
    QTest.mouseClick(table.viewport(), Qt.MouseButton.LeftButton, pos=empty_center)
    app.processEvents()
    assert table.currentRow() == 0

    img_cell = table.cellWidget(1, 0)
    assert img_cell is not None
    thumb_lbl = img_cell.findChild(ClickableImageLabel)
    assert thumb_lbl is not None
    assert img_cell.rect().contains(thumb_lbl.geometry())
    assert thumb_lbl.x() >= 6
    assert img_cell.width() - (thumb_lbl.x() + thumb_lbl.width()) >= 6
    assert thumb_lbl.cursor().shape() == Qt.CursorShape.PointingHandCursor
    assert thumb_lbl.toolTip() == i18n.tr("addons_dlg_zoom_tip")

    badges = thumb_lbl.findChildren(QLabel)
    assert len(badges) == 1
    zoom_badge = badges[0]

    vp_thumb_center = thumb_lbl.mapTo(table.viewport(), thumb_lbl.rect().center())
    vp_badge_center = thumb_lbl.mapTo(table.viewport(), zoom_badge.geometry().center())
    assert table.viewport().childAt(vp_thumb_center) is thumb_lbl
    assert table.viewport().childAt(vp_badge_center) is thumb_lbl

    QTest.mouseClick(thumb_lbl, Qt.MouseButton.LeftButton, pos=thumb_lbl.rect().center())
    QTest.mouseClick(thumb_lbl, Qt.MouseButton.LeftButton, pos=zoom_badge.geometry().center())
    app.processEvents()

    assert opened_modals == [
        ("Clickable Zoom Mod", True),
        ("Clickable Zoom Mod", True),
    ]
    assert table.currentRow() == 0
    host.close()


def test_batch_locked_dest_states_and_global_item_previews(
    tmp_path: Path, monkeypatch
) -> None:
    os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")
    from PySide6.QtWidgets import QApplication
    from core.history_manager import HistoryManager
    from ui.batch_page import BatchSwapPage

    app = QApplication.instance() or QApplication([])
    assert app is not None

    cfg_mgr = ConfigManager(config_path=tmp_path / "settings.json", project_root=tmp_path)
    cfg = AppConfig(first_run_completed=True, language="en-US")
    cfg_mgr.save(cfg)
    i18n = LocalizationManager("en-US")

    monkeypatch.setattr("ui.batch_page.InfoBar.warning", lambda *a, **kw: None)

    nick_dir = tmp_path / "nick_src"
    (nick_dir / "models" / "survivors").mkdir(parents=True, exist_ok=True)
    (nick_dir / "models" / "survivors" / "survivor_gambler.mdl").write_bytes(b"MDL")
    nick_vpk = tmp_path / "shizuku_nick.vpk"
    vpk.new(str(nick_dir)).save(str(nick_vpk))

    page = BatchSwapPage(
        config_mgr=cfg_mgr,
        history_mgr=HistoryManager(project_root=tmp_path),
        get_config_fn=lambda: cfg,
        get_env_fn=lambda: EnvironmentStatus(),
        i18n=i18n,
    )

    assert "no target selected" in page.global_preview_label.text()

    assert page.add_sources([nick_vpk]) == 1
    page.queue_table.selectRow(0)
    app.processEvents()

    assert "no target selected" in page.item_preview_label.text()
    for sid, btn in page._item_dest_buttons.items():
        assert btn.isEnabled() is False
        assert btn.isChecked() is False
        if sid == SurvivorId.NICK:
            assert btn._is_origin is True
            assert "ORIGIN" in btn.toolTip()
        else:
            assert btn._is_origin is False
            assert btn.toolTip() == ""

    chosen = (
        SurvivorId.BILL,
        SurvivorId.ZOEY,
        SurvivorId.LOUIS,
        SurvivorId.FRANCIS,
        SurvivorId.ELLIS,
    )
    for sid in chosen:
        page._global_buttons[sid].setChecked(True)
    app.processEvents()

    for sid, btn in page._item_dest_buttons.items():
        assert btn.isEnabled() is False
        if sid == SurvivorId.NICK:
            assert btn._is_origin is True
            assert btn.isChecked() is False
        elif sid in chosen:
            assert btn._is_origin is False
            assert btn.isChecked() is True
            assert btn._check_t == 1.0
        else:
            assert btn._is_origin is False
            assert btn.isChecked() is False

    assert "Preview (5 files):" in page.global_preview_label.text()
    assert "+1 more" in page.global_preview_label.text()
    assert "Ellis:" in page.global_preview_label.toolTip()
    assert "Preview (5 files):" in page.item_preview_label.text()
    assert "+1 more" in page.item_preview_label.text()
    assert "Ellis:" in page.item_preview_label.toolTip()

    page.use_global_dests_chk.setChecked(False)
    app.processEvents()
    for sid, btn in page._item_dest_buttons.items():
        if sid == SurvivorId.NICK:
            assert btn.isEnabled() is False
            assert btn._is_origin is True
        else:
            assert btn.isEnabled() is True
            assert btn._is_origin is False

    from ui.widgets import wrap_tooltip_text

    assert page.help_apply_all.text() == "?"
    assert page.help_apply_all.toolTip() == wrap_tooltip_text(i18n.tr("batch_help_apply_all"))
    assert page.item_help_global_dests.text() == "?"
    assert page.item_help_global_dests.toolTip() == wrap_tooltip_text(i18n.tr("batch_help_use_global_dests"))
    assert page.item_help_global_opts.text() == "?"
    assert page.item_help_global_opts.toolTip() == wrap_tooltip_text(i18n.tr("batch_help_use_global_opts"))
    from ui.addon_ui_shared import CenteredIconHeaderView

    assert isinstance(page.queue_table.horizontalHeader(), CenteredIconHeaderView)
    assert all(not page.queue_table.horizontalHeaderItem(c).icon().isNull() for c in range(5))
    page.close()

    from ui.settings_page import SettingsPage

    settings_page = SettingsPage(
        config_mgr=cfg_mgr,
        steam_locator=SteamLocator(project_root=tmp_path),
        get_config_fn=lambda: cfg,
        get_env_fn=lambda: EnvironmentStatus(),
        i18n=i18n,
    )
    assert settings_page.help_auto_install.text() == "?"
    assert settings_page.help_auto_install.toolTip() == wrap_tooltip_text(i18n.tr("help_install"))
    assert settings_page.help_keep_temp.text() == "?"
    assert settings_page.help_keep_temp.toolTip() == wrap_tooltip_text(i18n.tr("help_keep_temp"))
    settings_page.close()


def test_centered_icon_header_view_sizing_and_paint(tmp_path: Path) -> None:
    os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")
    from PySide6.QtWidgets import QApplication, QVBoxLayout, QWidget
    from qfluentwidgets import FluentIcon, Theme, setTheme

    from ui.addon_ui_shared import (
        ArchiveVpkPickerDialog,
        CenteredIconHeaderView,
        create_styled_mod_table,
        set_table_headers_with_icons,
    )

    app = QApplication.instance() or QApplication([])
    assert app is not None

    src_dir = tmp_path / "zoey_src"
    (src_dir / "models" / "survivors").mkdir(parents=True, exist_ok=True)
    (src_dir / "models" / "survivors" / "survivor_teenangst.mdl").write_bytes(b"MDL")
    sample_vpk = tmp_path / "zoey_pack.vpk"
    vpk.new(str(src_dir)).save(str(sample_vpk))

    i18n = LocalizationManager("pt-BR")
    host = QWidget()
    layout = QVBoxLayout(host)
    table = create_styled_mod_table(host, ["", "", "", "", ""], 220)
    layout.addWidget(table)

    headers = [
        (FluentIcon.PHOTO, "Prévia"),
        (FluentIcon.FOLDER, "Pasta"),
        (FluentIcon.PEOPLE, "Sobrevivente"),
        (FluentIcon.TAG, "Mod"),
        (FluentIcon.INFO, "Status"),
    ]
    header = table.horizontalHeader()
    assert isinstance(header, CenteredIconHeaderView)

    try:
        for theme in (Theme.DARK, Theme.LIGHT):
            setTheme(theme)
            set_table_headers_with_icons(table, headers)
            host.resize(820, 260)
            host.show()
            app.processEvents()
            pixmap = table.grab()
            assert not pixmap.isNull()

            fm = header._header_font_metrics()
            for col, (_, label) in enumerate(headers):
                expected_min = 14 + 6 + fm.horizontalAdvance(label) + CenteredIconHeaderView._HINT_HORIZONTAL_PADDING
                assert header.sectionSizeFromContents(col).width() >= expected_min

        picker = ArchiveVpkPickerDialog("pack.zip", [sample_vpk], i18n=i18n, parent=host)
        assert isinstance(picker.mod_table.horizontalHeader(), CenteredIconHeaderView)
        assert all(not picker.mod_table.horizontalHeaderItem(c).icon().isNull() for c in range(5))
        picker.close()
    finally:
        setTheme(Theme.DARK)
        host.close()


def test_conversion_confirm_dialog_navigation_gender_icons_and_swap_hook(
    tmp_path: Path, monkeypatch
) -> None:
    os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")
    from PySide6.QtCore import Qt
    from PySide6.QtGui import QImage
    from PySide6.QtWidgets import QApplication, QLabel, QWidget
    from qfluentwidgets import Theme, setTheme

    from core.history_manager import HistoryManager
    from ui.conversion_confirm_dialog import (
        ConversionConfirmDialog,
        ConversionConfirmEntry,
        _PersonGlyphBadge,
    )
    from ui.swap_page import SwapPage

    app = QApplication.instance() or QApplication([])
    assert app is not None

    cover_img = QImage(64, 40, QImage.Format.Format_ARGB32)
    cover_img.fill(0xFF335577)
    cover_path = tmp_path / "cover.png"
    cover_img.save(str(cover_path), "PNG")
    cover_bytes = cover_path.read_bytes()

    entries = [
        ConversionConfirmEntry(
            title="Zoey Tactical",
            source_filename="zoey_tactical.vpk",
            author="Echo",
            version="1.2",
            origin=SurvivorId.ZOEY,
            destinations=[SurvivorId.ROCHELLE],
            output_files=["zoey_tactical_rochelle.vpk"],
            output_dir=str(tmp_path / "out"),
            cover_bytes=cover_bytes,
            include_arms=True,
            include_vgui=True,
            include_weapons=False,
            sanitize_origin=True,
            install_to_addons=True,
        ),
        ConversionConfirmEntry(
            title="Shizuku Formal",
            source_filename="shizuku_nick.vpk",
            author="Kura",
            version="1.4",
            origin=SurvivorId.NICK,
            destinations=[SurvivorId.ELLIS, SurvivorId.ROCHELLE],
            output_files=["shizuku_ellis.vpk", "shizuku_rochelle.vpk"],
            output_dir=str(tmp_path / "out"),
            cover_bytes=None,
            include_arms=True,
            include_vgui=False,
            include_weapons=None,
            sanitize_origin=True,
            install_to_addons=False,
        ),
    ]

    i18n_pt = LocalizationManager("pt-BR")
    host = QWidget()
    host.resize(960, 720)
    host.show()

    try:
        single_dlg = ConversionConfirmDialog([entries[0]], i18n=i18n_pt, parent=host)
        assert single_dlg.nav_bar.isHidden() is True
        assert single_dlg.yesButton.text() == "Iniciar conversão"
        assert "1 VPK" in single_dlg.totals_pill.text()
        glyphs = single_dlg.findChildren(_PersonGlyphBadge)
        assert len(glyphs) == 2
        assert all(g._female is True for g in glyphs)
        pill_texts = [lbl.text() for lbl in single_dlg.route_box.findChildren(QLabel)]
        assert not any("♂" in txt or "♀" in txt for txt in pill_texts)
        single_dlg.close()

        for theme in (Theme.DARK, Theme.LIGHT):
            setTheme(theme)
            multi_dlg = ConversionConfirmDialog(entries, i18n=i18n_pt, parent=host)
            assert multi_dlg.nav_bar.isHidden() is False
            assert multi_dlg.prev_btn.isEnabled() is False
            assert multi_dlg.next_btn.isEnabled() is True
            assert multi_dlg.pager_label.text() == "Conversão 1 de 2"
            assert multi_dlg.mod_title_label.text() == "Zoey Tactical"
            assert not multi_dlg.cover_label.pixmap().isNull()

            multi_dlg.next_btn.click()
            app.processEvents()
            assert multi_dlg.current_index == 1
            assert multi_dlg.prev_btn.isEnabled() is True
            assert multi_dlg.next_btn.isEnabled() is False
            assert multi_dlg.pager_label.text() == "Conversão 2 de 2"
            assert multi_dlg.mod_title_label.text() == "Shizuku Formal"
            assert "desativada" in multi_dlg.note_text.text()
            glyphs_2 = [g for g in multi_dlg.route_box.findChildren(_PersonGlyphBadge) if g.isVisibleTo(multi_dlg)]
            assert [g._female for g in glyphs_2] == [False, False, True]

            multi_dlg.show()
            app.processEvents()
            assert not multi_dlg.grab().isNull()

            multi_dlg.prev_btn.click()
            app.processEvents()
            assert multi_dlg.current_index == 0
            multi_dlg.close()

        cfg_mgr = ConfigManager(config_path=tmp_path / "settings.json", project_root=tmp_path)
        cfg = AppConfig(first_run_completed=True, language="en-US")
        cfg_mgr.save(cfg)
        l4d2_root = tmp_path / "Left 4 Dead 2" / "left4dead2"
        addons_dir = l4d2_root / "addons"
        addons_dir.mkdir(parents=True, exist_ok=True)
        gameinfo = l4d2_root / "gameinfo.txt"
        gameinfo.write_text('"GameInfo" {}', encoding="utf-8")
        studiomdl = tmp_path / "studiomdl.exe"
        vpk_exe = tmp_path / "vpk.exe"
        decomp = tmp_path / "MdlDecompilerCli.exe"
        for tool in (studiomdl, vpk_exe, decomp):
            tool.write_bytes(b"")
        env = EnvironmentStatus(
            l4d2_dir=tmp_path / "Left 4 Dead 2",
            l4d2_gameinfo=gameinfo,
            l4d2_addons_dir=addons_dir,
            studiomdl_path=studiomdl,
            vpk_exe_path=vpk_exe,
            decompiler_cli_path=decomp,
            l4d2_installed=True,
            authoring_tools_installed=True,
        )
        src_dir = tmp_path / "src_nick"
        (src_dir / "models" / "survivors").mkdir(parents=True, exist_ok=True)
        (src_dir / "models" / "survivors" / "survivor_gambler.mdl").write_bytes(b"MDL")
        src_vpk = tmp_path / "nick_sample.vpk"
        vpk.new(str(src_dir)).save(str(src_vpk))

        swap_page = SwapPage(
            config_mgr=cfg_mgr,
            get_config_fn=lambda: cfg,
            get_env_fn=lambda: env,
            i18n=LocalizationManager("en-US"),
            history_mgr=HistoryManager(project_root=tmp_path),
        )
        swap_page._on_source_selected(src_vpk)
        swap_page.dest_picker._buttons[SurvivorId.ELLIS].setChecked(True)

        captured_entries: list[list[ConversionConfirmEntry]] = []

        def reject_exec(self_dlg) -> bool:
            captured_entries.append(list(self_dlg._entries))
            return False

        monkeypatch.setattr("ui.swap_page.ConversionConfirmDialog.exec", reject_exec)
        swap_page._on_start_conversion()
        assert len(captured_entries) == 1
        assert len(captured_entries[0]) == 1
        assert captured_entries[0][0].origin == SurvivorId.NICK
        assert captured_entries[0][0].destinations == [SurvivorId.ELLIS]
        assert captured_entries[0][0].output_files == ["nick_sample.vpk"]
        assert swap_page._worker_thread is None

        swap_page.dest_picker._buttons[SurvivorId.COACH].setChecked(True)
        swap_page._on_start_conversion()
        assert len(captured_entries) == 2
        assert set(captured_entries[1][0].destinations) == {SurvivorId.ELLIS, SurvivorId.COACH}
        assert set(captured_entries[1][0].output_files) == {"ellis_sample.vpk", "coach_sample.vpk"}
        assert swap_page._worker_thread is None
        swap_page.close()
    finally:
        setTheme(Theme.DARK)
        host.close()
