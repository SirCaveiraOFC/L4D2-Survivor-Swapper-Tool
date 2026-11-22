from __future__ import annotations

import json
import os
from pathlib import Path
import threading

import pytest
import vpk

from core.addons_scanner import AddonsScanner
from core.config_manager import ConfigManager
from core.history_manager import HistoryManager
from core.i18n import TRANSLATIONS, LocalizationManager
from core.models import AppConfig, EnvironmentStatus, SurvivorId
from core.steam_bbcode import extract_steam_summary, steam_bbcode_to_html
from core.workshop_downloader import (
    L4D2_APP_ID,
    WorkshopDownloadResult,
    WorkshopError,
    WorkshopItemDetails,
    build_safe_vpk_filename,
    download_vpk,
    extract_workshop_item_id,
    extract_workshop_item_ids,
    fetch_items_details,
    parse_published_file_details,
    parse_workshop_web_stats,
)


def _make_sample_vpk(tmp_path: Path, name: str = "sample.vpk", survivor_mdl: str = "survivor_gambler.mdl") -> bytes:
    src_dir = tmp_path / f"vpk_src_{name}"
    (src_dir / "models" / "survivors").mkdir(parents=True, exist_ok=True)
    (src_dir / "models" / "survivors" / survivor_mdl).write_bytes(b"IDST")
    (src_dir / "addoninfo.txt").write_text(
        '"AddonInfo"\n{\n  addontitle "Test Workshop Mod"\n  addonauthor "Tester"\n}\n',
        encoding="utf-8",
    )
    out_vpk = tmp_path / name
    vpk.new(str(src_dir)).save(str(out_vpk))
    return out_vpk.read_bytes()


def _make_fake_png() -> bytes:
    os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")
    from PySide6.QtCore import QBuffer, QIODevice
    from PySide6.QtGui import QImage
    from PySide6.QtWidgets import QApplication

    _ = QApplication.instance() or QApplication([])
    img = QImage(96, 60, QImage.Format.Format_ARGB32)
    img.fill(0xFF2E6B3E)
    buf = QBuffer()
    buf.open(QIODevice.OpenModeFlag.WriteOnly)
    img.save(buf, "PNG")
    return bytes(buf.data())


class _FakeHttpResponse:
    def __init__(self, body: bytes, status: int = 200, chunk_size: int = 4096) -> None:
        self._body = body
        self._pos = 0
        self._chunk_size = chunk_size
        self.status = status
        self.headers = {"Content-Length": str(len(body))}

    def read(self, amt: int = -1) -> bytes:
        if self._pos >= len(self._body):
            return b""
        if amt is None or amt < 0:
            chunk = self._body[self._pos :]
            self._pos = len(self._body)
            return chunk
        end = min(len(self._body), self._pos + min(amt, self._chunk_size))
        chunk = self._body[self._pos : end]
        self._pos = end
        return chunk

    def __enter__(self) -> _FakeHttpResponse:
        return self

    def __exit__(self, exc_type, exc, tb) -> bool:
        return False


def test_extract_workshop_item_ids_and_safe_filename() -> None:
    raw = (
        "https://steamcommunity.com/sharedfiles/filedetails/?id=2999473278\n"
        "https://steamcommunity.com/workshop/filedetails/?id=3843777163&searchtext=zoey\n"
        "steam://openurl/https://steamcommunity.com/sharedfiles/filedetails/?id=2999473278\n"
        "CommunityFilePage/112233445, 998877665"
    )
    assert extract_workshop_item_ids(raw) == [
        "2999473278",
        "3843777163",
        "112233445",
        "998877665",
    ]
    assert extract_workshop_item_id("3123456789") == "3123456789"
    with pytest.raises(WorkshopError) as exc_info:
        extract_workshop_item_id("not a steam workshop link")
    assert exc_info.value.key == "dl_err_invalid_id"

    assert build_safe_vpk_filename("3843777163", "myl4d2addons/root.vpk", "Title") == "3843777163_root.vpk"
    assert build_safe_vpk_filename("2999473278", "", "Zoey: Dark? Suit") == "2999473278_Zoey_ Dark_ Suit.vpk"
    assert build_safe_vpk_filename("2999473278", "2999473278_custom.vpk") == "2999473278_custom.vpk"


def test_parse_published_file_details_validates_result_and_app_id() -> None:
    payload = {
        "response": {
            "publishedfiledetails": [
                {
                    "publishedfileid": "2999473278",
                    "result": 1,
                    "consumer_app_id": L4D2_APP_ID,
                    "title": "Zoey Casual Pack",
                    "description": "[b]Nice mod[/b] on [url=https://example.com]Steam[/url]",
                    "filename": "myl4d2addons/zoey_casual.vpk",
                    "file_size": 123456,
                    "time_updated": 1700000000,
                    "file_url": "https://cdn.example/zoey.vpk",
                    "preview_url": "https://cdn.example/zoey.jpg",
                    "tags": [{"tag": "Survivors"}, {"tag": "Zoey"}],
                    "creator": "76561198000000001",
                }
            ]
        }
    }
    parsed = parse_published_file_details(payload)
    assert len(parsed) == 1
    assert parsed[0].published_file_id == "2999473278"
    assert parsed[0].consumer_app_id == 550
    assert parsed[0].tags == ("Survivors", "Zoey")

    wrong_app = {
        "response": {
            "publishedfiledetails": [
                {
                    "publishedfileid": "123456789",
                    "result": 1,
                    "consumer_app_id": 440,
                }
            ]
        }
    }
    with pytest.raises(WorkshopError) as err_app:
        parse_published_file_details(wrong_app)
    assert err_app.value.key == "dl_err_wrong_app"

    not_found = {
        "response": {
            "publishedfiledetails": [
                {
                    "publishedfileid": "123456789",
                    "result": 9,
                    "consumer_app_id": 0,
                }
            ]
        }
    }
    with pytest.raises(WorkshopError) as err_nf:
        parse_published_file_details(not_found)
    assert err_nf.value.key == "dl_err_not_found"


def test_fetch_and_download_vpk_streaming_cache_cancel_and_local_fallback(
    tmp_path: Path, monkeypatch
) -> None:
    vpk_bytes = _make_sample_vpk(tmp_path, "src_workshop.vpk")
    png_bytes = _make_fake_png()
    dl_dir = tmp_path / "Workshop_Downloads"

    api_payload = {
        "response": {
            "publishedfiledetails": [
                {
                    "publishedfileid": "3843777163",
                    "result": 1,
                    "consumer_app_id": 550,
                    "title": "Root Pack",
                    "description": "[h1]Hello[/h1] L4D2",
                    "filename": "myl4d2addons/root.vpk",
                    "file_size": len(vpk_bytes),
                    "time_updated": 1710000000,
                    "file_url": "https://cdn.example/3843777163.vpk",
                    "preview_url": "https://cdn.example/3843777163.png",
                    "tags": [{"tag": "Survivors"}],
                    "creator": "76561198000000002",
                }
            ]
        }
    }

    calls: list[str] = []

    def fake_urlopen(req, timeout=15.0):
        url = req.full_url if hasattr(req, "full_url") else str(req)
        calls.append(url)
        if "GetPublishedFileDetails" in url:
            return _FakeHttpResponse(json.dumps(api_payload).encode("utf-8"))
        if url.endswith(".vpk"):
            return _FakeHttpResponse(vpk_bytes, chunk_size=32)
        if url.endswith(".png"):
            return _FakeHttpResponse(png_bytes)
        raise AssertionError(f"Unexpected URL: {url}")

    monkeypatch.setattr("core.workshop_downloader.urllib.request.urlopen", fake_urlopen)

    items = fetch_items_details(["3843777163"])
    assert len(items) == 1
    progress_updates: list[tuple[int, int]] = []
    res = download_vpk(
        details=items[0],
        target_dir=dl_dir,
        progress_cb=lambda done, total: progress_updates.append((done, total)),
    )
    assert res.vpk_path == dl_dir / "3843777163_root.vpk"
    assert res.vpk_path.read_bytes() == vpk_bytes
    assert res.preview_bytes == png_bytes
    assert res.already_cached is False
    assert progress_updates and progress_updates[-1][0] == len(vpk_bytes)
    assert not list(dl_dir.glob("*.part"))

    calls.clear()
    res_cached = download_vpk(details=items[0], target_dir=dl_dir, overwrite=False)
    assert res_cached.already_cached is True
    assert not any(u.endswith(".vpk") for u in calls)

    cancel_ev = threading.Event()
    cancel_ev.set()
    with pytest.raises(WorkshopError) as err_cancel:
        download_vpk(details=items[0], target_dir=dl_dir, overwrite=True, cancel_event=cancel_ev)
    assert err_cancel.value.key == "dl_err_cancelled"
    assert not list(dl_dir.glob("*.part"))

    bad_details = WorkshopItemDetails(
        published_file_id="777888999",
        result=1,
        consumer_app_id=550,
        title="Bad Payload",
        description="",
        filename="bad.vpk",
        file_size=12,
        time_updated=0,
        file_url="https://cdn.example/bad.vpk",
        preview_url="",
        tags=(),
    )

    def fake_bad_vpk(req, timeout=15.0):
        return _FakeHttpResponse(b"<html>not a vpk</html>")

    monkeypatch.setattr("core.workshop_downloader.urllib.request.urlopen", fake_bad_vpk)
    with pytest.raises(WorkshopError) as err_magic:
        download_vpk(details=bad_details, target_dir=dl_dir, overwrite=True)
    assert err_magic.value.key == "dl_err_not_vpk"
    assert not list(dl_dir.glob("*.part"))

    no_url_details = WorkshopItemDetails(
        published_file_id="555444333",
        result=1,
        consumer_app_id=550,
        title="Local Fallback",
        description="",
        filename="",
        file_size=len(vpk_bytes),
        time_updated=0,
        file_url="",
        preview_url="",
        tags=(),
    )
    addons_dir = tmp_path / "l4d2" / "left4dead2" / "addons"
    local_ws_vpk = addons_dir / "workshop" / "555444333.vpk"
    local_ws_vpk.parent.mkdir(parents=True, exist_ok=True)
    local_ws_vpk.write_bytes(vpk_bytes)

    local_res = download_vpk(details=no_url_details, target_dir=dl_dir, addons_dir=addons_dir)
    assert local_res.from_local_workshop is True
    assert local_res.vpk_path == local_ws_vpk

    with pytest.raises(WorkshopError) as err_no_url:
        download_vpk(details=no_url_details, target_dir=dl_dir, addons_dir=None)
    assert err_no_url.value.key == "dl_err_no_file_url"


def test_download_translations_and_settings_persist_workshop_dir(tmp_path: Path) -> None:
    for lang in ("en-US", "pt-BR", "es-ES"):
        assert TRANSLATIONS[lang]["nav_download"] == "Download"

    cfg_mgr = ConfigManager(project_root=tmp_path)
    cfg = AppConfig()
    assert cfg.workshop_download_dir == "Workshop_Downloads"
    cfg.workshop_download_dir = "Custom_WS"
    cfg_mgr.save(cfg)
    reloaded = cfg_mgr.load()
    assert reloaded.workshop_download_dir == "Custom_WS"


def test_download_page_url_dialogs_and_main_window_integration(tmp_path: Path, monkeypatch) -> None:
    os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")
    from PySide6.QtWidgets import QApplication, QWidget
    from qfluentwidgets import Theme, setTheme

    from ui.batch_page import BatchSwapPage
    from ui.download_page import WorkshopDownloadPage
    from ui.main_window import MainWindow
    from ui.swap_page import SwapPage
    from ui.workshop_download_dialog import WorkshopUrlDialog

    app = QApplication.instance() or QApplication([])
    assert app is not None

    vpk_bytes = _make_sample_vpk(tmp_path, "nick_ws.vpk", survivor_mdl="survivor_gambler.mdl")
    png_bytes = _make_fake_png()
    ws_dir = tmp_path / "Workshop_Downloads"
    ws_dir.mkdir(parents=True, exist_ok=True)
    cached_vpk = ws_dir / "2999473278_nick_suit.vpk"
    cached_vpk.write_bytes(vpk_bytes)

    addons_dir = tmp_path / "l4d2" / "left4dead2" / "addons"
    addons_dir.mkdir(parents=True, exist_ok=True)
    gameinfo = tmp_path / "l4d2" / "left4dead2" / "gameinfo.txt"
    gameinfo.write_text('"GameInfo" {}', encoding="utf-8")
    for tool_name in ("studiomdl.exe", "vpk.exe", "MdlDecompilerCli.exe"):
        (tmp_path / tool_name).write_bytes(b"")

    cfg_mgr = ConfigManager(project_root=tmp_path)
    cfg = AppConfig(
        l4d2_dir=str(tmp_path / "l4d2"),
        studiomdl_executable=str(tmp_path / "studiomdl.exe"),
        vpk_executable=str(tmp_path / "vpk.exe"),
        workshop_download_dir="Workshop_Downloads",
        language="pt-BR",
        first_run_completed=True,
    )
    cfg_mgr.save(cfg)

    env = EnvironmentStatus(
        l4d2_dir=tmp_path / "l4d2",
        l4d2_gameinfo=gameinfo,
        l4d2_addons_dir=addons_dir,
        studiomdl_path=tmp_path / "studiomdl.exe",
        vpk_exe_path=tmp_path / "vpk.exe",
        decompiler_cli_path=tmp_path / "MdlDecompilerCli.exe",
        l4d2_installed=True,
        authoring_tools_installed=True,
    )

    page = WorkshopDownloadPage(
        config_mgr=cfg_mgr,
        get_config_fn=lambda: cfg,
        get_env_fn=lambda: env,
        i18n=LocalizationManager("pt-BR"),
    )
    try:
        assert page.library_table.rowCount() == 1
        assert page.library_table.item(0, 1).text() == "2999473278"
        assert page.library_table.item(0, 2).text() == "Nick"

        details = WorkshopItemDetails(
            published_file_id="2999473278",
            result=1,
            consumer_app_id=550,
            title="Nick Dapper Suit",
            description="[b]Clean tactical suit[/b]",
            filename="myl4d2addons/nick_suit.vpk",
            file_size=len(vpk_bytes),
            time_updated=1715000000,
            file_url="https://cdn.example/2999473278.vpk",
            preview_url="https://cdn.example/2999473278.png",
            tags=("Survivors", "Nick"),
        )
        page._on_download_completed(
            [
                WorkshopDownloadResult(
                    details=details,
                    vpk_path=cached_vpk,
                    preview_bytes=png_bytes,
                )
            ]
        )
        assert page.item_title_label.text() == "Nick Dapper Suit"
        assert "Clean tactical suit" in page.item_desc_label.text()
        assert page.send_swap_btn.isEnabled()
        assert page.send_batch_btn.isEnabled()
        assert page.install_addons_btn.isEnabled()
        assert page.open_steam_btn.isEnabled()
        assert page.cover_zoom_btn.isVisibleTo(page.details_card) or page._active_cover_pixmap is not None

        page._on_install_to_addons()
        assert (addons_dir / cached_vpk.name).is_file()

        swap_emitted: list[Path] = []
        batch_emitted: list[list[Path]] = []
        page.sendToSwapRequested.connect(swap_emitted.append)
        page.sendToBatchRequested.connect(batch_emitted.append)
        page._on_send_to_swap()
        page._on_send_to_batch()
        assert swap_emitted == [cached_vpk]
        assert batch_emitted == [[cached_vpk]]
    finally:
        page.shutdown_worker()
        page.close()
        page.deleteLater()
        app.processEvents()

    host = QWidget()
    host.resize(960, 720)
    dlg_single = WorkshopUrlDialog(
        download_dir=ws_dir,
        allow_multiple=False,
        i18n=LocalizationManager("en-US"),
        parent=host,
    )
    dlg_multi = WorkshopUrlDialog(
        download_dir=ws_dir,
        allow_multiple=True,
        i18n=LocalizationManager("pt-BR"),
        parent=host,
    )
    try:
        dlg_single.url_input.setText("https://steamcommunity.com/sharedfiles/filedetails/?id=2999473278")
        assert dlg_single._parse_ids() == ["2999473278"]
        dlg_multi.url_input.setPlainText("2999473278\n3843777163")
        assert dlg_multi._parse_ids() == ["2999473278", "3843777163"]
    finally:
        dlg_single.close()
        dlg_multi.close()
        host.close()
        dlg_single.deleteLater()
        dlg_multi.deleteLater()
        host.deleteLater()
        app.processEvents()

    swap_page = SwapPage(
        config_mgr=cfg_mgr,
        get_config_fn=lambda: cfg,
        get_env_fn=lambda: env,
        i18n=LocalizationManager("en-US"),
        history_mgr=HistoryManager(project_root=tmp_path),
    )
    batch_page = BatchSwapPage(
        config_mgr=cfg_mgr,
        history_mgr=HistoryManager(project_root=tmp_path),
        get_config_fn=lambda: cfg,
        get_env_fn=lambda: env,
        i18n=LocalizationManager("en-US"),
    )
    try:
        monkeypatch.setattr("ui.swap_page.WorkshopUrlDialog.exec", lambda self_d: True)
        monkeypatch.setattr("ui.swap_page.WorkshopUrlDialog.downloaded_paths", lambda self_d: [cached_vpk])
        url_btn_clicked: list[bool] = []
        swap_page.drop_card.workshopUrlRequested.connect(lambda: url_btn_clicked.append(True))
        swap_page.drop_card.link_workshop_btn.click()
        assert url_btn_clicked == [True]
        assert swap_page._detected_info is not None
        assert swap_page._detected_info.detected_origin == SurvivorId.NICK

        monkeypatch.setattr("ui.batch_page.WorkshopUrlDialog.exec", lambda self_d: True)
        monkeypatch.setattr("ui.batch_page.WorkshopUrlDialog.downloaded_paths", lambda self_d: [cached_vpk])
        batch_page._on_download_workshop_urls()
        assert len(batch_page._items) == 1
        assert batch_page._items[0].source_path == cached_vpk
        batch_page._set_busy(True)
        assert not batch_page.add_url_btn.isEnabled()
        batch_page._set_busy(False)
        assert batch_page.add_url_btn.isEnabled()
    finally:
        swap_page.close()
        batch_page.close()
        swap_page.deleteLater()
        batch_page.deleteLater()
        app.processEvents()

    win = MainWindow(project_root=tmp_path)
    win._wizard_timer.stop()
    try:
        assert win.settings_page.workshop_dir_edit.text() == "Workshop_Downloads"
        assert "lbl_workshop_download_dir" in win.settings_page._form_labels
        for lang in ("en-US", "pt-BR", "es-ES"):
            win.apply_language_preference(lang, persist=False)
            assert win._nav_download.text() == "Download"
        win.download_page.sendToBatchRequested.emit([cached_vpk])
        assert len(win.batch_page._items) == 1
        for theme_pref in ("Dark", "Light"):
            win.apply_theme_preference(theme_pref, persist=False)
            win.switchTo(win.download_page)
            win.show()
            app.processEvents()
            snap = win.grab()
            assert not snap.isNull()
    finally:
        setTheme(Theme.DARK)
        win.close()
        win.deleteLater()
        app.processEvents()


def test_steam_bbcode_formatting_and_summary() -> None:
    sample_bb = (
        "[h1]Name: STRUGGLE TO ESCAPE (COMPLETE EDITION)[/h1]\n"
        "[h2]Description: Break free from SI pins.[/h2]\n"
        "[h3]Formatting Showcase[/h3]\n"
        "[b]Bold[/b] [u]Underline[/u] [i]Italic[/i] [strike]Strike[/strike] [spoiler]Secret[/spoiler]\n"
        "[noparse]Literal [b]tags[/b] stay raw[/noparse]\n"
        "[hr][/hr]\n"
        "[url=store.steampowered.com]Steam Store[/url]\n"
        "[img=https://cdn.example/banner.gif][/img]\n"
        "https://www.youtube.com/watch?v=tax4e4hBBZc\n"
        "https://store.steampowered.com/app/550/\n"
        "https://steamcommunity.com/sharedfiles/filedetails/?id=3042532130\n"
        "[list]\n[*]Bullet one\n[*]Bullet [b]two[/b]\n[/list]\n"
        "[olist]\n[*]First\n[*]Second\n[/olist]\n"
        "[quote=Sr.Caveira | </> Dark']Quote body[/quote]\n"
        "[code]a = 1  +  2[/code]\n"
        "[table equalcells=1]\n"
        "[tr][th]Cmd[/th][th]Desc[/th][/tr]\n"
        "[tr][td]!sts_duration [target] [si] <s>[/td][td]Value <o>[/td][/tr]\n"
        "[/table]\n"
        "[table noborder=1][tr][td]Borderless[/td][/tr][/table]\n"
    )
    rendered_placeholder, img_urls = steam_bbcode_to_html(
        sample_bb,
        is_dark=True,
        original_author_label="Escrito originalmente por",
    )
    assert img_urls == ["https://cdn.example/banner.gif"]
    assert "<h1" in rendered_placeholder
    assert "<h2" in rendered_placeholder
    assert "<h3" in rendered_placeholder
    assert "<b>Bold</b>" in rendered_placeholder
    assert "<u>Underline</u>" in rendered_placeholder
    assert "<i>Italic</i>" in rendered_placeholder
    assert "<s>Strike</s>" in rendered_placeholder
    assert "[SPOILER] Secret" in rendered_placeholder
    assert "Literal [b]tags[/b] stay raw" in rendered_placeholder
    assert "<hr " in rendered_placeholder
    assert 'href="https://store.steampowered.com"' in rendered_placeholder
    assert "YouTube: https://www.youtube.com/watch?v=tax4e4hBBZc" in rendered_placeholder
    assert "Steam Store (App 550):" in rendered_placeholder
    assert "Steam Workshop (ID 3042532130):" in rendered_placeholder
    assert "<ul " in rendered_placeholder and "<li>Bullet <b>two</b></li>" in rendered_placeholder.replace('<li style="margin: 3px 0;">', "<li>")
    assert "<ol " in rendered_placeholder and "First" in rendered_placeholder
    assert "Escrito originalmente por <b>Sr.Caveira | &lt;/&gt; Dark&#x27;</b>:" in rendered_placeholder
    assert "<pre " in rendered_placeholder and "a = 1  +  2" in rendered_placeholder
    assert "!sts_duration [target] [si] &lt;s&gt;" in rendered_placeholder
    assert "Value &lt;o&gt;" in rendered_placeholder
    assert 'border: none;' in rendered_placeholder
    assert "<img " not in rendered_placeholder
    assert "[Image]" in rendered_placeholder

    rendered_with_img, _ = steam_bbcode_to_html(
        sample_bb,
        is_dark=False,
        loaded_images={"https://cdn.example/banner.gif"},
    )
    assert '<img src="https://cdn.example/banner.gif">' in rendered_with_img

    summary = extract_steam_summary(sample_bb, title="STRUGGLE TO ESCAPE (COMPLETE EDITION)")
    assert not summary.lower().startswith("name:")
    assert "Break free from SI pins." in summary


def test_parse_workshop_web_stats_stars_and_creators() -> None:
    payload = {
        "response": {
            "publishedfiledetails": [
                {
                    "publishedfileid": "3042532130",
                    "result": 1,
                    "consumer_app_id": 550,
                    "title": "STRUGGLE TO ESCAPE",
                    "description": "Body",
                    "filename": "myl4d2addons/struggle_to_escape.vpk",
                    "file_size": 195305,
                    "time_created": 1695905078,
                    "time_updated": 1789140101,
                    "file_url": "https://cdn.example/struggle.vpk",
                    "preview_url": "https://cdn.example/struggle.gif",
                    "subscriptions": 40486,
                    "lifetime_subscriptions": 90138,
                    "favorited": 10159,
                    "lifetime_favorited": 11261,
                    "views": 104594,
                    "tags": [{"tag": "Scripts"}],
                }
            ]
        }
    }
    parsed = parse_published_file_details(payload)[0]
    assert parsed.time_created == 1695905078
    assert parsed.subscriptions == 40486
    assert parsed.lifetime_subscriptions == 90138
    assert parsed.favorited == 10159
    assert parsed.views == 104594

    fake_html = (
        '<div class="fileRatingDetails"><img src="https://community.akamai.steamstatic.com/public/images/sharedfiles/5-star_large.png?v=2" /></div>'
        '<div class="numRatings">1,727 ratings</div>'
        '<div class="friendBlockContent">\nSr.Caveira | 頭蓋骨 &lt;/&gt; Dark&#x27;<br></div>'
        '<div class="friendBlockContent">\nH.U.N.K<br></div>'
        '<div id="commentthread_PublishedFile_Public_area"><div class="friendBlockContent">CommenterIgnored</div></div>'
    )
    stats = parse_workshop_web_stats(fake_html)
    assert stats["rating_stars"] == 5
    assert stats["num_ratings"] == 1727
    assert stats["creator_name"] == "Sr.Caveira | 頭蓋骨 </> Dark', H.U.N.K"

    unrated = parse_workshop_web_stats('<img src="https://cdn.example/not-yet.png">')
    assert unrated["rating_stars"] == 0


def test_animated_gif_and_non_survivor_script_mod_in_download_page(tmp_path: Path, monkeypatch) -> None:
    os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")
    from PySide6.QtCore import QBuffer, QEvent, QPointF, Qt
    from PySide6.QtGui import QMouseEvent, QPixmap
    from PySide6.QtWidgets import QApplication, QLabel
    from qfluentwidgets import BodyLabel, InfoBar, StrongBodyLabel, Theme, setTheme

    from ui.download_page import WorkshopDownloadPage
    from ui.widgets import ImageZoomDialog, clear_preview_media
    from ui.workshop_description_dialog import WorkshopDescriptionDialog

    app = QApplication.instance() or QApplication([])
    assert app is not None

    animated_gif = (
        b"GIF89a\x02\x00\x02\x00\x80\x00\x00\x00\x00\x00\xff\xff\xff"
        b"!\xf9\x04\x04\x0a\x00\x00\x00"
        b",\x00\x00\x00\x00\x02\x00\x02\x00\x00\x02\x02\x84Q\x00"
        b"!\xf9\x04\x04\x0a\x00\x00\x00"
        b",\x00\x00\x00\x00\x02\x00\x02\x00\x00\x02\x02\x84Q\x00;"
    )

    script_src = tmp_path / "script_src"
    (script_src / "scripts" / "vscripts").mkdir(parents=True, exist_ok=True)
    (script_src / "scripts" / "vscripts" / "struggle.nut").write_text("Msg(\"ok\");", encoding="utf-8")
    (script_src / "addoninfo.txt").write_text(
        '"AddonInfo"\n{\n  addontitle "STRUGGLE TO ESCAPE"\n  addonauthor "Sr.Caveira"\n}\n',
        encoding="utf-8",
    )
    ws_dir = tmp_path / "Workshop_Downloads"
    ws_dir.mkdir(parents=True, exist_ok=True)
    script_vpk = ws_dir / "3042532130_struggle_to_escape.vpk"
    vpk.new(str(script_src)).save(str(script_vpk))

    assert AddonsScanner._inspect_vpk_fast(script_vpk, "workshop", ws_dir, {}) is None
    inspected_any = AddonsScanner._inspect_vpk_fast(
        script_vpk,
        "workshop",
        ws_dir,
        {},
        allow_non_survivor=True,
    )
    assert inspected_any is not None
    assert inspected_any.origin is None
    assert inspected_any.title == "STRUGGLE TO ESCAPE"

    addons_dir = tmp_path / "l4d2" / "left4dead2" / "addons"
    addons_dir.mkdir(parents=True, exist_ok=True)
    cfg_mgr = ConfigManager(project_root=tmp_path)
    cfg = AppConfig(workshop_download_dir="Workshop_Downloads", language="pt-BR")
    env = EnvironmentStatus(l4d2_addons_dir=addons_dir, l4d2_installed=True)

    page = WorkshopDownloadPage(
        config_mgr=cfg_mgr,
        get_config_fn=lambda: cfg,
        get_env_fn=lambda: env,
        i18n=LocalizationManager("pt-BR"),
    )
    try:
        assert page.library_table.rowCount() == 1
        assert page.library_table.item(0, 1).text() == "3042532130"
        assert page.library_table.item(0, 2).text() == "—"

        details = WorkshopItemDetails(
            published_file_id="3042532130",
            result=1,
            consumer_app_id=550,
            title="STRUGGLE TO ESCAPE (COMPLETE EDITION)",
            description="[h1]Name: STRUGGLE TO ESCAPE (COMPLETE EDITION)[/h1]\n[b]Break free[/b] [table][tr][th]Cmd[/th][/tr][tr][td]!sts[/td][/tr][/table]",
            filename="myl4d2addons/struggle_to_escape.vpk",
            file_size=script_vpk.stat().st_size,
            time_created=1695905078,
            time_updated=1789140101,
            file_url="https://cdn.example/struggle.vpk",
            preview_url="https://cdn.example/struggle.gif",
            tags=("Scripts", "Survivors"),
            subscriptions=40486,
            lifetime_subscriptions=90138,
            favorited=10159,
            views=104594,
            rating_stars=5,
            num_ratings=1727,
            creator_name="Sr.Caveira",
        )
        page._on_download_completed(
            [WorkshopDownloadResult(details=details, vpk_path=script_vpk, preview_bytes=animated_gif)]
        )
        cover_movie = getattr(page.cover_thumb, "_gif_movie", None)
        assert cover_movie is not None and cover_movie.frameCount() == 2

        stat_vals = [lbl.text() for lbl in page.stats_host.findChildren(StrongBodyLabel)]
        assert "40.486" in stat_vals
        assert "10.159" in stat_vals
        assert "104.594" in stat_vals

        meta_vals = [lbl.text() for lbl in page.meta_host.findChildren(BodyLabel)]
        assert any("Sr.Caveira" in v for v in meta_vals)

        tag_chips = [lbl.text() for lbl in page.tags_chips_host.findChildren(QLabel)]
        assert tag_chips == ["Scripts", "Survivors"]

        pill_texts = [lbl.text() for lbl in page.pills_host.findChildren(QLabel)]
        assert "Script VScript" in pill_texts
        assert "Mod Geral" not in " ".join(pill_texts)

        assert page.full_desc_btn.isVisibleTo(page.details_card) or page.full_desc_btn.text() == "Ler Descrição Completa"
        assert not page.send_swap_btn.isEnabled()
        assert not page.send_batch_btn.isEnabled()
        assert page.not_skin_badge.isVisibleTo(page.details_card) or page._is_non_survivor_vpk is True
        assert page.install_addons_btn.isEnabled()

        popup_calls: list[tuple[str, str]] = []
        monkeypatch.setattr(
            InfoBar,
            "warning",
            staticmethod(lambda title, content, **kwargs: popup_calls.append((title, content))),
        )
        badge_release = QMouseEvent(
            QEvent.Type.MouseButtonRelease,
            QPointF(4.0, 4.0),
            QPointF(4.0, 4.0),
            Qt.MouseButton.LeftButton,
            Qt.MouseButton.NoButton,
            Qt.KeyboardModifier.NoModifier,
        )
        QApplication.sendEvent(page.not_skin_badge, badge_release)
        assert len(popup_calls) == 1
        assert "models/survivors/" in popup_calls[0][1]

        from qfluentwidgets import FluentIcon, MessageBox
        from ui.theme import L4d2ThemeManager

        del_box = MessageBox("Excluir", "Confirmar?", page)
        L4d2ThemeManager.style_dialog_yes_button(del_box.yesButton, "Excluir", FluentIcon.DELETE)
        L4d2ThemeManager.style_dialog_cancel_button(del_box.cancelButton, "Cancelar", FluentIcon.CLOSE)
        L4d2ThemeManager.apply_pointing_hand_cursors(del_box)
        assert del_box.yesButton.cursor().shape() == Qt.CursorShape.PointingHandCursor
        assert del_box.cancelButton.cursor().shape() == Qt.CursorShape.PointingHandCursor
        del_box.close()
        del_box.deleteLater()

        page._on_install_to_addons()
        assert (addons_dir / script_vpk.name).is_file()

        zoom_dlg = ImageZoomDialog(
            title=details.title,
            pixmap=page._active_cover_pixmap,
            i18n=LocalizationManager("pt-BR"),
            parent=page,
            raw_bytes=animated_gif,
        )
        zoom_movie = getattr(zoom_dlg.zoom_image_label, "_gif_movie", None)
        assert zoom_movie is not None and zoom_movie.frameCount() == 2
        zoom_dlg.close()
        zoom_dlg.deleteLater()

        desc_dlg = WorkshopDescriptionDialog(
            title=details.title,
            raw_description=details.description,
            subtitle="ID 3042532130",
            steam_url=details.workshop_url,
            i18n=LocalizationManager("pt-BR"),
            parent=page,
        )
        assert "<b>Break free</b>" in desc_dlg._rendered_html
        assert "<table " in desc_dlg._rendered_html
        desc_dlg.shutdown_worker()
        desc_dlg.close()
        desc_dlg.deleteLater()

        assert AddonsScanner.detect_non_survivor_kind(None, ()) == ""
    finally:
        clear_preview_media(page.cover_thumb)
        page.shutdown_worker()
        page.close()
        page.deleteLater()
        setTheme(Theme.DARK)
        app.processEvents()


def test_localized_dates_lifetime_label_and_card_hover_coverage(tmp_path: Path) -> None:
    os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")
    from datetime import datetime
    from PySide6.QtCore import QBuffer, QEvent, QPointF, Qt
    from PySide6.QtGui import QMouseEvent, QPixmap
    from PySide6.QtWidgets import QApplication, QFrame, QLabel, QWidget
    from qfluentwidgets import BodyLabel, CaptionLabel, CardWidget, HeaderCardWidget, Theme, setTheme

    from core.history_manager import HistoryManager
    from core.models import ConversionHistoryEntry, ConversionHistoryOutput
    from core.workshop_downloader import format_timestamp
    from core.steam_locator import SteamLocator
    from ui.addon_ui_shared import AddonPreviewInspector, create_table_thumb_cell
    from ui.download_page import WorkshopDownloadPage
    from ui.environment_page import EnvironmentPage
    from ui.history_page import HistoryPage
    from ui.theme import COLORS, L4d2ThemeManager
    from ui.widgets import DropZoneCard, ImageZoomDialog, L4d2HeroBanner, clear_preview_media

    app = QApplication.instance() or QApplication([])
    assert app is not None

    epoch = 1695905078
    expected_dmy = datetime.fromtimestamp(epoch).strftime("%d/%m/%Y %H:%M")
    expected_ymd = datetime.fromtimestamp(epoch).strftime("%Y-%m-%d %H:%M")
    assert format_timestamp(epoch, "pt-BR") == expected_dmy
    assert format_timestamp(epoch, "es-ES") == expected_dmy
    assert format_timestamp(epoch, "en-US") == expected_ymd

    assert LocalizationManager("pt-BR").format_date_str("2026-09-11 12:21:05") == "11/09/2026 12:21"
    assert LocalizationManager("es-ES").format_date_str("2026-09-11 12:21:05") == "11/09/2026 12:21"
    assert LocalizationManager("en-US").format_date_str("2026-09-11 12:21:05") == "2026-09-11 12:21"

    cfg_mgr = ConfigManager(project_root=tmp_path)
    cfg = AppConfig(workshop_download_dir="Workshop_Downloads", language="pt-BR")
    env = EnvironmentStatus(l4d2_installed=False)
    setTheme(Theme.DARK)

    hist_mgr = HistoryManager(project_root=tmp_path)
    hist_mgr.save(
        [
            ConversionHistoryEntry(
                entry_id="hist-1",
                created_at="2026-09-11 12:21:05",
                mod_title="Test Mod",
                author="Sr.Caveira",
                source_path="mod.vpk",
                origin="bill",
                destinations=["coach"],
                outputs=[
                    ConversionHistoryOutput(
                        destination="coach",
                        success=True,
                        vpk_path="",
                    ),
                ],
            )
        ]
    )

    dl_page = WorkshopDownloadPage(
        config_mgr=cfg_mgr,
        get_config_fn=lambda: cfg,
        get_env_fn=lambda: env,
        i18n=LocalizationManager("pt-BR"),
    )
    hist_page = HistoryPage(
        history_mgr=hist_mgr,
        get_env_fn=lambda: env,
        i18n=LocalizationManager("pt-BR"),
    )
    env_page = EnvironmentPage(
        config_mgr=cfg_mgr,
        steam_locator=SteamLocator(),
        get_config_fn=lambda: cfg,
        get_env_fn=lambda: env,
        i18n=LocalizationManager("pt-BR"),
    )
    hero = L4d2HeroBanner(i18n=LocalizationManager("pt-BR"))
    drop_zone = DropZoneCard(i18n=LocalizationManager("pt-BR"))
    try:
        dl_page.show()
        env_page.show()
        app.processEvents()
        details = WorkshopItemDetails(
            published_file_id="3042532130",
            result=1,
            consumer_app_id=550,
            title="STRUGGLE TO ESCAPE",
            description="Break free from Special Infected pins.",
            filename="myl4d2addons/struggle_to_escape.vpk",
            file_size=195305,
            time_created=epoch,
            time_updated=1789140101,
            file_url="https://cdn.example/struggle.vpk",
            preview_url="https://cdn.example/struggle.gif",
            subscriptions=40486,
            lifetime_subscriptions=90138,
            favorited=10159,
            views=104594,
            rating_stars=5,
            num_ratings=1727,
            tags=(
                "Charger",
                "Hunter",
                "Jockey",
                "Smoker",
                "Scripts",
                "Survivors",
                "Special Infected",
                "Bill",
                "Coach",
                "Zoey",
                "Ellis",
                "Nick",
                "Rochelle",
                "Francis",
                "Louis",
            ),
            creator_name="Sr.Caveira",
        )
        dl_page.resize(1120, 820)
        dl_page._active_details = details
        dl_page._active_id = details.published_file_id
        dl_page._render_active_details()
        app.processEvents()
        assert dl_page.tags_host.height() <= 80
        L4d2ThemeManager.enable_card_hover(dl_page)
        L4d2ThemeManager.enable_card_hover(env_page)
        L4d2ThemeManager.enable_card_hover(hist_page)

        stat_captions = [lbl.text() for lbl in dl_page.stats_host.findChildren(CaptionLabel)]
        assert any("total (histórico)" in txt for txt in stat_captions)
        meta_texts_pt = [lbl.text() for lbl in dl_page.meta_host.findChildren(BodyLabel)]
        assert any(expected_dmy in txt for txt in meta_texts_pt)

        dl_page.retranslate_ui(LocalizationManager("es-ES"))
        stat_captions_es = [lbl.text() for lbl in dl_page.stats_host.findChildren(CaptionLabel)]
        assert any("total (histórico)" in txt for txt in stat_captions_es)
        meta_texts_es = [lbl.text() for lbl in dl_page.meta_host.findChildren(BodyLabel)]
        assert any(expected_dmy in txt for txt in meta_texts_es)

        dl_page.retranslate_ui(LocalizationManager("en-US"))
        stat_captions_en = [lbl.text() for lbl in dl_page.stats_host.findChildren(CaptionLabel)]
        assert any("total (lifetime)" in txt for txt in stat_captions_en)
        meta_texts_en = [lbl.text() for lbl in dl_page.meta_host.findChildren(BodyLabel)]
        assert any(expected_ymd in txt for txt in meta_texts_en)

        pills = dl_page.pills_host.findChildren(QFrame, "dlMetaPill")
        tiles = dl_page.stats_host.findChildren(QFrame, "dlStatTile")
        chips = dl_page.tags_chips_host.findChildren(QLabel, "dlTagChip")
        assert len(pills) >= 2
        assert len(tiles) >= 3
        assert len(chips) == 15
        for surface in [dl_page.desc_box, *pills, *tiles, *chips]:
            motion = next((c for c in surface.children() if c.objectName() == "l4d2SurfaceMotion"), None)
            assert motion is not None
            assert "#C98E00" not in surface.styleSheet()

        cover_motion = next(c for c in dl_page.cover_thumb.children() if c.objectName() == "l4d2SurfaceMotion")
        assert cover_motion._hover_border is not None
        assert cover_motion._hover_border.name().lower() == COLORS.amber.lower()
        QApplication.sendEvent(dl_page.cover_thumb, QEvent(QEvent.Type.Enter))
        cover_motion._hover_anim.stop()
        cover_motion._on_hover_value(1.0)
        assert "rgba(245, 183, 0, 255)" in dl_page.cover_thumb.styleSheet()
        QApplication.sendEvent(dl_page.cover_thumb, QEvent(QEvent.Type.Leave))
        cover_motion._hover_anim.stop()
        cover_motion._on_hover_value(0.0)

        tile_motion = next(c for c in tiles[0].children() if c.objectName() == "l4d2SurfaceMotion")
        QApplication.sendEvent(tiles[0], QEvent(QEvent.Type.Enter))
        assert float(tile_motion._hover_anim.endValue()) == 1.0
        press_ev = QMouseEvent(
            QEvent.Type.MouseButtonPress,
            QPointF(6.0, 6.0),
            QPointF(6.0, 6.0),
            Qt.MouseButton.LeftButton,
            Qt.MouseButton.LeftButton,
            Qt.KeyboardModifier.NoModifier,
        )
        release_ev = QMouseEvent(
            QEvent.Type.MouseButtonRelease,
            QPointF(6.0, 6.0),
            QPointF(6.0, 6.0),
            Qt.MouseButton.LeftButton,
            Qt.MouseButton.NoButton,
            Qt.KeyboardModifier.NoModifier,
        )
        QApplication.sendEvent(tiles[0], press_ev)
        assert float(tile_motion._press_anim.endValue()) == 1.0
        QApplication.sendEvent(tiles[0], release_ev)
        assert float(tile_motion._press_anim.endValue()) == 0.0
        QApplication.sendEvent(tiles[0], QEvent(QEvent.Type.Leave))
        assert float(tile_motion._hover_anim.endValue()) == 0.0

        assert hist_page.history_table.item(0, 0).text() == "11/09/2026 12:21"
        hist_page.history_table.selectRow(0)
        hist_page._on_selection_changed()
        assert "11/09/2026 12:21" in hist_page.detail_meta.text()
        hist_page.retranslate_ui(LocalizationManager("en-US"))
        assert hist_page.history_table.item(0, 0).text() == "2026-09-11 12:21"
        assert "2026-09-11 12:21" in hist_page.detail_meta.text()
        assert any(c.objectName() == "l4d2SurfaceMotion" for c in hist_page.detail_panel.children())
        assert any(c.objectName() == "l4d2SurfaceMotion" for c in hist_page.detail_thumb_label.children())

        card = dl_page.input_card
        assert isinstance(card, HeaderCardWidget)
        overlay = card.findChild(QWidget, "l4d2CardHoverOverlay")
        assert overlay is not None
        assert not overlay.isVisible()
        QApplication.sendEvent(card, QEvent(QEvent.Type.Enter))
        assert overlay.isVisible()
        assert float(overlay._hover_anim.endValue()) == 1.0
        QApplication.sendEvent(card, press_ev)
        assert float(overlay._press_anim.endValue()) == 1.0
        QApplication.sendEvent(card, release_ev)
        assert float(overlay._press_anim.endValue()) == 0.0
        QApplication.sendEvent(card, QEvent(QEvent.Type.Leave))
        assert float(overlay._hover_anim.endValue()) == 0.0

        env_overlay = env_page.l4d2_card.findChild(QWidget, "l4d2CardHoverOverlay")
        assert env_overlay is not None
        assert not env_overlay.isVisible()
        QApplication.sendEvent(env_page.l4d2_card, QEvent(QEvent.Type.Enter))
        assert env_overlay.isVisible()
        assert float(env_overlay._hover_anim.endValue()) == 1.0
        QApplication.sendEvent(env_page.l4d2_card, QEvent(QEvent.Type.Leave))
        assert float(env_overlay._hover_anim.endValue()) == 0.0

        assert hero.findChild(QWidget, "l4d2CardHoverOverlay") is None
        assert drop_zone.findChild(QWidget, "l4d2CardHoverOverlay") is None
        assert isinstance(hero, CardWidget)
        QApplication.sendEvent(hero, QEvent(QEvent.Type.Enter))
        assert hero._hovered is True
        assert float(hero._hover_anim.endValue()) == 1.0
        QApplication.sendEvent(hero, QEvent(QEvent.Type.Leave))
        assert hero._hovered is False
        assert float(hero._hover_anim.endValue()) == 0.0
        QApplication.sendEvent(drop_zone, QEvent(QEvent.Type.Enter))
        assert drop_zone._hovered is True
        assert float(drop_zone._hover_anim.endValue()) == 1.0
        QApplication.sendEvent(drop_zone, QEvent(QEvent.Type.Leave))
        assert drop_zone._hovered is False
        assert float(drop_zone._hover_anim.endValue()) == 0.0

        assert "\n" in dl_page.not_skin_badge.toolTip()
        assert all(len(line) <= 52 for line in dl_page.not_skin_badge.toolTip().splitlines())
        assert dl_page.view.minimumSizeHint().width() <= dl_page.viewport().width()

        dark_idle, dark_hover, _dark_press = L4d2ThemeManager.surface_palette(True, "neutral")
        assert dark_hover.blue() >= dark_hover.red() > dark_idle.red()
        light_idle, light_hover, _light_press = L4d2ThemeManager.surface_palette(False, "neutral")
        assert light_hover.lightness() < light_idle.lightness()

        from ui.swap_page import SwapPage

        swap_page = SwapPage(
            config_mgr=cfg_mgr,
            get_config_fn=lambda: cfg,
            get_env_fn=lambda: env,
            i18n=LocalizationManager("pt-BR"),
            history_mgr=hist_mgr,
        )
        try:
            swap_page.resize(1040, 820)
            swap_page.show()
            app.processEvents()
            badges = swap_page.findChildren(QLabel, "templateTagBadge")
            assert [b.text() for b in badges] == ["{survivor}", "{origin}", "{orig_title}", "{generation}"]
            swap_page.output_name_edit.clear()
            QApplication.sendEvent(badges[0], release_ev)
            assert swap_page.output_name_edit.text() == "{survivor}"
            assert swap_page.tags_preview_card.header_title.text() == "Prévia de saída"
            assert swap_page.tags_preview_card.rows_lay.count() == 2

            from core.models import SurvivorId as _Sid

            for dest_sid in (_Sid.ROCHELLE, _Sid.NICK, _Sid.COACH, _Sid.ELLIS, _Sid.BILL):
                swap_page.dest_picker._buttons[dest_sid].click()
                app.processEvents()
                assert swap_page.tags_preview_card.height() >= swap_page.tags_preview_card.sizeHint().height()
            QApplication.sendEvent(badges[1], release_ev)
            app.processEvents()
            assert swap_page.tags_preview_card.height() >= swap_page.tags_preview_card.sizeHint().height()

            from qfluentwidgets import TableWidget

            inspector = AddonPreviewInspector(LocalizationManager("pt-BR"))
            sample_pix = QPixmap(8, 8)
            sample_pix.fill(Qt.GlobalColor.red)
            buf = QBuffer()
            buf.open(QBuffer.OpenModeFlag.WriteOnly)
            sample_pix.save(buf, "PNG")
            sample_png = bytes(buf.data())
            buf.close()
            tbl = TableWidget()
            thumb_cell = create_table_thumb_cell(tbl, sample_png, True, "Test", LocalizationManager("pt-BR"))
            tbl_thumb = thumb_cell.findChild(QLabel, "tableThumbLabel")
            zoom_dlg = ImageZoomDialog("Zoom", pixmap=sample_pix, i18n=LocalizationManager("pt-BR"), parent=swap_page)
            try:
                assert tbl_thumb is not None
                for img_lbl in (
                    hist_page.detail_thumb_label,
                    swap_page.cover_thumb_label,
                    inspector.preview_image_label,
                    tbl_thumb,
                    zoom_dlg.zoom_image_label,
                ):
                    img_motion = next(
                        (c for c in img_lbl.children() if c.objectName() == "l4d2SurfaceMotion"),
                        None,
                    )
                    assert img_motion is not None
                    assert img_motion._hover_border is not None
                    assert img_motion._hover_border.name().lower() == COLORS.amber.lower()
                    QApplication.sendEvent(img_lbl, QEvent(QEvent.Type.Enter))
                    img_motion._hover_anim.stop()
                    img_motion._on_hover_value(1.0)
                    assert "rgba(245, 183, 0, 255)" in img_lbl.styleSheet()
                    QApplication.sendEvent(img_lbl, QEvent(QEvent.Type.Leave))
                    img_motion._hover_anim.stop()
                    img_motion._on_hover_value(0.0)
            finally:
                zoom_dlg.close()
                zoom_dlg.deleteLater()
                tbl.close()
                tbl.deleteLater()
                inspector.close()
                inspector.deleteLater()
        finally:
            swap_page.close()
            swap_page.deleteLater()
    finally:
        clear_preview_media(dl_page.cover_thumb)
        dl_page.shutdown_worker()
        dl_page.close()
        dl_page.deleteLater()
        env_page.close()
        env_page.deleteLater()
        hist_page.close()
        hist_page.deleteLater()
        hero.close()
        hero.deleteLater()
        drop_zone.close()
        drop_zone.deleteLater()
        setTheme(Theme.DARK)
        app.processEvents()


def test_window_resize_and_screen_repaint_guard(tmp_path: Path) -> None:
    os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")
    from PySide6.QtCore import QEvent, QObject, QPoint, Qt
    from PySide6.QtTest import QTest
    from PySide6.QtWidgets import QApplication, QWidget
    from qfluentwidgets import Theme, setTheme

    from ui.main_window import MainWindow

    app = QApplication.instance() or QApplication([])
    assert app is not None

    cfg_mgr = ConfigManager(project_root=tmp_path)
    cfg = AppConfig(first_run_completed=True, language="pt-BR", theme="Dark")
    cfg_mgr.save(cfg)

    win = MainWindow(project_root=tmp_path)
    win._wizard_timer.stop()
    try:
        win.show()
        app.processEvents()

        assert win.isMicaEffectEnabled() is False
        guard = win.findChild(QObject, "l4d2WindowRepaintFilter")
        assert guard is not None

        overlays = win.findChildren(QWidget, "l4d2CardHoverOverlay")
        assert overlays
        assert all(not ov.testAttribute(Qt.WidgetAttribute.WA_TranslucentBackground) for ov in overlays)

        sp = win.swap_page
        for w, h in ((1120, 800), (860, 680), (1380, 900)):
            win.resize(w, h)
            app.processEvents()
            guard._flush_settled()
            app.processEvents()
            assert sp.meta_card.width() <= sp.viewport().width()
            assert sp.dest_picker.width() <= sp.viewport().width()
            assert win.titleBar.x() + win.titleBar.width() <= win.width()
            close_btn = win.titleBar.closeBtn
            close_center = close_btn.mapTo(win, close_btn.rect().center())
            assert win.rect().contains(close_center)
            assert win.childAt(close_center) is close_btn
            assert sp.addon_version_edit.y() > sp.output_name_edit.y() + sp.output_name_edit.height()
            assert not sp.addon_version_edit.geometry().intersects(sp.output_name_edit.geometry())
            assert sp.tags_preview_card.height() >= 62
            assert win.stackedWidget.currentWidget().pos() == QPoint(0, 0)
            for ov in sp.findChildren(QWidget, "l4d2CardHoverOverlay"):
                parent = ov.parentWidget()
                if parent is not None:
                    assert ov.geometry() == parent.rect()

        for tab in (win.download_page, win.addons_page, win.history_page, win.batch_page):
            win.switchTo(tab)
            app.processEvents()
            guard._flush_settled()
            app.processEvents()

        QApplication.sendEvent(win, QEvent(QEvent.Type.WindowActivate))
        assert guard._immediate_timer.isActive() or not guard._refreshing
        QTest.mouseClick(win.titleBar.closeBtn, Qt.MouseButton.LeftButton)
        app.processEvents()
        assert not win.isVisible()
    finally:
        win.close()
        win.deleteLater()
        setTheme(Theme.DARK)
        app.processEvents()
