from __future__ import annotations

import ast
import io
import json
import os
import subprocess
import sys
import urllib.error
import zipfile
from pathlib import Path

import pytest

from core.addons_scanner import AddonsScanner
from core.app_meta import APP_META
from core.archive_service import ArchiveSourceManager
from core.config_manager import ConfigManager
from core.i18n import TRANSLATIONS, LocalizationManager
from core.mdl_toolchain import run_subprocess_cancellable
from core.models import EnvironmentStatus, SwapCancelledError
from core.updater import (
    UpdateCheckResult,
    UpdateError,
    UpdateFileChange,
    apply_staged_update,
    check_for_updates,
    extract_app_meta_version,
    git_blob_sha1,
    is_protected_rel_path,
    normalize_github_repo,
    parse_version_tuple,
    stage_update_from_zip,
)
from core.vpk_service import VpkService


class _FakeHttpResp:
    def __init__(self, payload: bytes, status: int = 200, content_length: int | None = None) -> None:
        self._buf = io.BytesIO(payload)
        self.status = status
        self.headers = {"Content-Length": str(content_length if content_length is not None else len(payload))}

    def read(self, n: int = -1) -> bytes:
        return self._buf.read(n)

    def __enter__(self):
        return self

    def __exit__(self, exc_type, exc, tb):
        return False


def _build_github_archive_zip(top_folder: str, files: dict[str, bytes]) -> bytes:
    buf = io.BytesIO()
    with zipfile.ZipFile(buf, "w", compression=zipfile.ZIP_DEFLATED) as zf:
        for rel, data in files.items():
            zf.writestr(f"{top_folder}/{rel}", data)
    return buf.getvalue()


def test_path_traversal_prefix_bypass_blocked(tmp_path: Path) -> None:
    dest_dir = tmp_path / "extract"
    dest_dir.mkdir()
    sibling_dir = tmp_path / "extract_evil"
    sibling_dir.mkdir()

    zip_path = tmp_path / "prefix_escape.zip"
    with zipfile.ZipFile(zip_path, "w") as zf:
        zf.writestr("../extract_evil/pwned.txt", b"evil")

    err = ArchiveSourceManager._extract_archive(zip_path, dest_dir)
    assert err == "Unsafe archive path traversal detected"
    assert not (sibling_dir / "pwned.txt").exists()

    svc = VpkService()

    class _FakeEntry:
        def save(self, target: str) -> None:
            Path(target).write_bytes(b"evil")

    class _FakePak(dict):
        def __enter__(self):
            return self

        def __exit__(self, exc_type, exc, tb):
            return False

    fake_pak = _FakePak({"../extract_evil/vpk_pwned.txt": _FakeEntry()})
    svc._open_vpk = staticmethod(lambda _p: fake_pak)
    with pytest.raises(ValueError, match="Unsafe path traversal"):
        svc.extract_vpk(tmp_path / "fake.vpk", dest_dir)
    assert not (sibling_dir / "vpk_pwned.txt").exists()


def test_pack_folder_preserves_existing_vpk_when_replace_fails(tmp_path: Path, monkeypatch) -> None:
    source_dir = tmp_path / "work" / "pkg"
    source_dir.mkdir(parents=True)
    (source_dir / "addoninfo.txt").write_text('"AddonInfo" {}', encoding="utf-8")
    vpk_exe = tmp_path / "vpk.exe"
    vpk_exe.write_bytes(b"MZ")
    out_vpk = tmp_path / "out" / "existing.vpk"
    out_vpk.parent.mkdir(parents=True)
    out_vpk.write_bytes(b"ORIGINAL_DATA")

    def fake_run(cmd, cwd=None, cancel_cb=None, timeout=240.0):
        produced = source_dir.parent / f"{source_dir.name}.vpk"
        produced.write_bytes(b"NEW_DATA")
        return 0, "ok", ""

    monkeypatch.setattr("core.vpk_service.run_subprocess_cancellable", fake_run)
    monkeypatch.setattr(
        "core.vpk_service.os.replace",
        lambda _s, _d: (_ for _ in ()).throw(PermissionError("locked by game")),
    )

    with pytest.raises(PermissionError):
        VpkService().pack_folder_to_vpk(source_dir, out_vpk, vpk_exe)

    assert out_vpk.read_bytes() == b"ORIGINAL_DATA"


def test_subprocess_cancellable_aborts_immediately() -> None:
    checks = {"count": 0}

    def cancel_cb() -> bool:
        checks["count"] += 1
        return checks["count"] >= 2

    with pytest.raises(SwapCancelledError):
        run_subprocess_cancellable(
            [sys.executable, "-c", "import time; time.sleep(10)"],
            cancel_cb=cancel_cb,
            timeout=15.0,
        )


def test_addons_scanner_respects_cancel_cb(tmp_path: Path) -> None:
    addons = tmp_path / "addons"
    addons.mkdir()
    (addons / "mod1.vpk").write_bytes(b"x")
    (addons / "mod2.vpk").write_bytes(b"x")

    res = AddonsScanner.scan_survivor_addons(addons, include_workshop=False, cancel_cb=lambda: True)
    assert res == []


def test_all_i18n_keys_resolve_and_updates_labels_translated() -> None:
    assert TRANSLATIONS["en-US"]["nav_updates"] == "Updates"
    assert TRANSLATIONS["en-US"]["upd_page_title"] == "Updates"
    assert TRANSLATIONS["pt-BR"]["nav_updates"] == "Atualizações"
    assert TRANSLATIONS["pt-BR"]["upd_page_title"] == "Atualizações"
    assert TRANSLATIONS["es-ES"]["nav_updates"] == "Actualizaciones"
    assert TRANSLATIONS["es-ES"]["upd_page_title"] == "Actualizaciones"

    root = Path(__file__).resolve().parent.parent
    checked = 0
    for py_file in list((root / "core").glob("*.py")) + list((root / "ui").glob("*.py")) + [root / "app.py"]:
        tree = ast.parse(py_file.read_text(encoding="utf-8"), filename=str(py_file))
        for node in ast.walk(tree):
            if (
                isinstance(node, ast.Call)
                and isinstance(node.func, ast.Attribute)
                and node.func.attr == "tr"
                and node.args
                and isinstance(node.args[0], ast.Constant)
                and isinstance(node.args[0].value, str)
            ):
                key = node.args[0].value
                checked += 1
                for lang in ("en-US", "pt-BR", "es-ES"):
                    assert key in TRANSLATIONS[lang], f"Missing {key!r} in {lang} ({py_file.name}:{node.lineno})"
    assert checked > 500


def test_updater_helpers_and_user_file_protection() -> None:
    assert APP_META.github_repo == "SirCaveiraOFC/L4D2-Survivor-Swapper-Tool"
    assert normalize_github_repo("SrCaveira/L4D2-Survivor-Swapper") == "SrCaveira/L4D2-Survivor-Swapper"
    assert (
        normalize_github_repo("https://github.com/SrCaveira/L4D2-Survivor-Swapper.git/")
        == "SrCaveira/L4D2-Survivor-Swapper"
    )
    with pytest.raises(UpdateError):
        normalize_github_repo("not_a_repo")

    assert parse_version_tuple("v2.3.1") == (2, 3, 1)
    assert parse_version_tuple("2.4") == (2, 4, 0)
    assert extract_app_meta_version("major: int = 2\nminor: int = 5\npatch: int = 3\n") == (2, 5, 3)

    data = b"print('ok')\n"
    assert len(git_blob_sha1(data)) == 40

    assert is_protected_rel_path("settings.json")
    assert is_protected_rel_path("conversion_history.json")
    assert is_protected_rel_path("Swapped_Survivors/my_skin.vpk")
    assert is_protected_rel_path("Workshop_Downloads/123.vpk")
    assert is_protected_rel_path(".git/config")
    assert is_protected_rel_path("custom_out/skin.vpk", extra_protected_roots=("custom_out",))
    assert not is_protected_rel_path("ui/updates_page.py")
    assert not is_protected_rel_path("core/new_feature/helper.py")


def test_updater_check_stage_diff_and_apply_preserves_user_data(tmp_path: Path, monkeypatch) -> None:
    project_root = tmp_path / "app_root"
    (project_root / "core").mkdir(parents=True)
    (project_root / "ui").mkdir(parents=True)
    (project_root / "Swapped_Survivors").mkdir(parents=True)
    (project_root / "Workshop_Downloads").mkdir(parents=True)

    (project_root / "settings.json").write_text('{"theme":"Dark"}', encoding="utf-8")
    (project_root / "conversion_history.json").write_text("[]", encoding="utf-8")
    (project_root / "Swapped_Survivors" / "keep_me.vpk").write_bytes(b"KEEP_OUTPUT")
    (project_root / "Workshop_Downloads" / "keep_ws.vpk").write_bytes(b"KEEP_WS")
    (project_root / "app.py").write_bytes(b"old app\n")
    (project_root / "core" / "unchanged.py").write_bytes(b"same\n")
    (project_root / "core" / "obsolete_mod.py").write_bytes(b"to remove\n")

    new_app = b"new app\n"
    new_helper = b"def helper():\n    return 42\n"
    new_meta = b"major: int = 2\nminor: int = 1\npatch: int = 0\n"
    unchanged_bytes = b"same\n"

    release_payload = json.dumps(
        {
            "tag_name": "v2.1.0",
            "name": "v2.1.0 Update",
            "body": "- Added new submodule\n- Fixed bug",
            "published_at": "2026-11-22T03:00:00Z",
            "html_url": "https://github.com/SrCaveira/Swapper/releases/tag/v2.1.0",
        }
    ).encode("utf-8")

    tree_payload = json.dumps(
        {
            "tree": [
                {"type": "blob", "path": "app.py", "sha": git_blob_sha1(new_app), "size": len(new_app)},
                {"type": "blob", "path": "core/app_meta.py", "sha": git_blob_sha1(new_meta), "size": len(new_meta)},
                {"type": "blob", "path": "core/unchanged.py", "sha": git_blob_sha1(unchanged_bytes), "size": len(unchanged_bytes)},
                {"type": "blob", "path": "core/new_pkg/helper.py", "sha": git_blob_sha1(new_helper), "size": len(new_helper)},
            ]
        }
    ).encode("utf-8")

    archive_zip = _build_github_archive_zip(
        "Swapper-2.1.0",
        {
            "app.py": new_app,
            "core/app_meta.py": new_meta,
            "core/unchanged.py": unchanged_bytes,
            "core/new_pkg/helper.py": new_helper,
            "settings.json": b'{"theme":"SHOULD_NEVER_OVERWRITE"}',
        },
    )

    def fake_urlopen(req, timeout=10.0):
        url = req.full_url if hasattr(req, "full_url") else str(req)
        if "/releases/latest" in url:
            return _FakeHttpResp(release_payload)
        if "raw.githubusercontent.com" in url:
            raise urllib.error.HTTPError(url, 404, "Not Found", {}, None)
        if "/git/trees/" in url:
            return _FakeHttpResp(tree_payload)
        if url.endswith(".zip"):
            return _FakeHttpResp(archive_zip)
        raise AssertionError(f"Unexpected URL: {url}")

    monkeypatch.setattr("core.updater.urllib.request.urlopen", fake_urlopen)

    check = check_for_updates(
        repo="https://github.com/SrCaveira/Swapper",
        current_version="2.0.0",
        project_root=project_root,
    )
    assert check.has_update is True
    assert check.latest_version == "2.1.0"
    assert check.source_kind == "release"
    change_map = {c.rel_path: c.change_type for c in check.preview_changes}
    assert change_map == {
        "app.py": "modified",
        "core/app_meta.py": "added",
        "core/new_pkg/helper.py": "added",
        "core/obsolete_mod.py": "removed",
    }

    plan = stage_update_from_zip(
        zip_url=check.zip_url,
        repo=check.repo,
        target_version="2.1.0",
        project_root=project_root,
    )
    assert {c.rel_path for c in plan.changes} == set(change_map.keys())

    res = apply_staged_update(plan=plan, project_root=project_root, install_requirements=False)
    assert res.applied_count == 3
    assert res.removed_count == 1
    assert res.deferred_count == 0
    assert (project_root / "app.py").read_bytes() == new_app
    assert (project_root / "core" / "new_pkg" / "helper.py").read_bytes() == new_helper
    assert not (project_root / "core" / "obsolete_mod.py").exists()
    assert (project_root / "settings.json").read_text(encoding="utf-8") == '{"theme":"Dark"}'
    assert (project_root / "Swapped_Survivors" / "keep_me.vpk").read_bytes() == b"KEEP_OUTPUT"
    assert (project_root / "Workshop_Downloads" / "keep_ws.vpk").read_bytes() == b"KEEP_WS"
    assert (project_root / ".update_manifest.json").is_file()


def test_updates_page_and_main_window_ui(tmp_path: Path, monkeypatch) -> None:
    os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")
    from PySide6.QtWidgets import QApplication, QToolButton
    from qfluentwidgets import isDarkTheme
    from ui.addon_ui_shared import CenteredIconHeaderView
    from ui.theme import COLORS

    app = QApplication.instance() or QApplication([])
    cfg_mgr = ConfigManager(config_path=tmp_path / "settings.json", project_root=tmp_path)
    cfg = cfg_mgr.load()
    assert cfg.theme == "Dark"
    cfg.first_run_completed = True
    cfg.github_repo = "SrCaveira/Swapper"
    cfg_mgr.save(cfg)

    class _DummyLocator:
        def __init__(self, project_root=None) -> None:
            self.project_root = project_root

        def inspect_environment(self, _cfg) -> EnvironmentStatus:
            return EnvironmentStatus(crowbar_settings_path=tmp_path / "Crowbar Settings.xml")

    monkeypatch.setattr("ui.main_window.ConfigManager", lambda project_root=None: cfg_mgr)
    monkeypatch.setattr("ui.main_window.SteamLocator", _DummyLocator)

    from ui.main_window import MainWindow

    win = MainWindow(project_root=tmp_path)
    try:
        win._wizard_timer.stop()
        win._update_check_timer.stop()
        win.show()
        app.processEvents()
        assert isDarkTheme() is True
        assert isinstance(win.updates_page.files_table.horizontalHeader(), CenteredIconHeaderView)
        assert win._updates_badge is None

        win.apply_language_preference("en-US")
        assert win._nav_updates.text() == "Updates"
        assert win.updates_page.page_title.text() == "Updates"

        win.apply_language_preference("pt-BR")
        assert win._nav_updates.text() == "Atualizações"
        assert win.updates_page.page_title.text() == "Atualizações"

        win.apply_language_preference("es-ES")
        assert win._nav_updates.text() == "Actualizaciones"
        assert win.updates_page.page_title.text() == "Actualizaciones"

        win.apply_theme_preference("Light")
        assert isDarkTheme() is False
        assert COLORS.light_card_alt in win.history_page.outputs_list.styleSheet()
        assert COLORS.dark_card_alt not in win.history_page.outputs_list.styleSheet()
        assert isinstance(win.history_page.detail_zoom_btn, QToolButton)
        assert "QToolButton" in win.history_page.detail_zoom_btn.styleSheet()

        win.apply_theme_preference("Dark")
        assert isDarkTheme() is True
        assert COLORS.dark_card_alt in win.history_page.outputs_list.styleSheet()

        sample_result = UpdateCheckResult(
            repo="SrCaveira/Swapper",
            branch="main",
            current_version=APP_META.version,
            latest_version="2.1.0",
            has_update=True,
            source_kind="release",
            release_tag="v2.1.0",
            release_title="v2.1.0",
            release_notes="- Improved updater",
            preview_changes=[
                UpdateFileChange("core/new_file.py", "added", 120),
                UpdateFileChange("app.py", "modified", 950),
                UpdateFileChange("core/old.py", "removed", 0),
            ],
        )
        win.updates_page._on_check_completed(sample_result, False)
        app.processEvents()
        assert win._updates_badge is not None
        assert win._updates_badge.isVisible() is True
        assert win.updates_page.update_btn.isEnabled() is True
        assert win.updates_page.files_table.rowCount() == 3

        up_to_date = UpdateCheckResult(
            repo="SrCaveira/Swapper",
            branch="main",
            current_version=APP_META.version,
            latest_version=APP_META.version,
            has_update=False,
            source_kind="release",
        )
        win.updates_page._on_check_completed(up_to_date, False)
        app.processEvents()
        assert win._updates_badge is None
        assert f"v{APP_META.version}" in win.updates_page.status_label.text()

        older_remote = UpdateCheckResult(
            repo="SrCaveira/Swapper",
            branch="main",
            current_version=APP_META.version,
            latest_version="1.0.0",
            has_update=False,
            source_kind="release",
        )
        win.updates_page._on_check_completed(older_remote, False)
        app.processEvents()
        assert win._updates_badge is None
        assert f"v{APP_META.version}" in win.updates_page.status_label.text()
        assert "v1.0.0" in win.updates_page.status_label.text()

        from PySide6.QtCore import QAbstractAnimation, QEvent
        from PySide6.QtGui import QFocusEvent
        from PySide6.QtTest import QTest
        from ui.theme import _InputFocusOverlay

        for page_widget, target_input in (
            (win.swap_page, win.swap_page.output_name_edit),
            (win.download_page, win.download_page.url_edit),
        ):
            win.switchTo(page_widget)
            app.processEvents()
            overlay = target_input.findChild(_InputFocusOverlay, "l4d2InputFocusOverlay")
            assert overlay is not None
            assert overlay.isVisible() is False
            if hasattr(target_input, "focusedBorderColor"):
                assert target_input.focusedBorderColor().alpha() == 0
            if hasattr(target_input, "layer"):
                assert target_input.layer.isVisible() is False

            QApplication.sendEvent(target_input, QFocusEvent(QEvent.Type.FocusIn))
            app.processEvents()
            assert overlay.isVisible() is True
            assert overlay._anim.state() == QAbstractAnimation.State.Running
            QTest.qWait(260)
            app.processEvents()
            assert overlay._focus_t >= 0.95

            QApplication.sendEvent(target_input, QFocusEvent(QEvent.Type.FocusOut))
            app.processEvents()
            assert overlay._anim.state() == QAbstractAnimation.State.Running
            QTest.qWait(200)
            app.processEvents()
            assert overlay._focus_t == pytest.approx(0.0, abs=0.01)
            assert overlay.isVisible() is False

        assert win.swap_page.progress_card.log_view.findChild(_InputFocusOverlay, "l4d2InputFocusOverlay") is None
        assert win.swap_page.progress_card.log_view.layer.isVisible() is False
    finally:
        win.close()
        win.deleteLater()
        app.processEvents()
