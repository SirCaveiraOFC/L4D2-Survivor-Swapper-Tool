from __future__ import annotations

import os
import sys
from pathlib import Path
from typing import Optional

from PySide6.QtCore import QTimer
from PySide6.QtGui import QCloseEvent, QGuiApplication, QIcon, QShowEvent
from PySide6.QtWidgets import QApplication
from qfluentwidgets import (
    FluentIcon,
    FluentWindow,
    InfoBadge,
    InfoBadgePosition,
    NavigationDisplayMode,
    NavigationItemPosition,
)

from core.app_meta import APP_META
from core.config_manager import ConfigManager
from core.history_manager import HistoryManager
from core.i18n import LocalizationManager
from core.models import AppConfig, EnvironmentStatus
from core.steam_locator import SteamLocator
from ui.addons_page import AddonsLoadoutPage
from ui.batch_page import BatchSwapPage
from ui.download_page import WorkshopDownloadPage
from ui.environment_page import EnvironmentPage
from ui.history_page import HistoryPage
from ui.settings_page import SettingsPage
from ui.setup_wizard import SetupWizardDialog
from ui.swap_page import SwapPage
from ui.theme import L4d2ThemeManager
from ui.updates_page import UpdatesPage


class MainWindow(FluentWindow):
    """Main FluentWindow application shell for L4D2 Survivor Swapper Tool."""

    def __init__(self, project_root: Optional[Path] = None) -> None:
        super().__init__()
        self.project_root = project_root or Path(__file__).resolve().parent.parent
        self.config_mgr = ConfigManager(project_root=self.project_root)
        self.history_mgr = HistoryManager(project_root=self.project_root)
        self.steam_locator = SteamLocator(project_root=self.project_root)

        self.config: AppConfig = self.config_mgr.load()
        self.env_status: EnvironmentStatus = self.steam_locator.inspect_environment(self.config)
        self._sync_detected_paths_into_config()

        self.i18n = LocalizationManager(self.config.language)
        self._native_icon_handles: list[int] = []
        self._app_icon_path = self.project_root / "ui" / "app_icon.ico"
        self._apply_window_icon()
        L4d2ThemeManager.apply_window_theme(self, self.config.theme)

        self.resize(1120, 800)
        self.setMinimumSize(860, 680)

        self.swap_page = SwapPage(
            config_mgr=self.config_mgr,
            get_config_fn=lambda: self.config,
            get_env_fn=lambda: self.env_status,
            i18n=self.i18n,
            history_mgr=self.history_mgr,
            parent=self,
        )
        self.batch_page = BatchSwapPage(
            config_mgr=self.config_mgr,
            history_mgr=self.history_mgr,
            get_config_fn=lambda: self.config,
            get_env_fn=lambda: self.env_status,
            i18n=self.i18n,
            parent=self,
        )
        self.addons_page = AddonsLoadoutPage(
            get_env_fn=lambda: self.env_status,
            i18n=self.i18n,
            parent=self,
        )
        self.download_page = WorkshopDownloadPage(
            config_mgr=self.config_mgr,
            get_config_fn=lambda: self.config,
            get_env_fn=lambda: self.env_status,
            i18n=self.i18n,
            parent=self,
        )
        self.history_page = HistoryPage(
            history_mgr=self.history_mgr,
            get_env_fn=lambda: self.env_status,
            i18n=self.i18n,
            parent=self,
        )
        self.environment_page = EnvironmentPage(
            config_mgr=self.config_mgr,
            steam_locator=self.steam_locator,
            get_config_fn=lambda: self.config,
            get_env_fn=lambda: self.env_status,
            i18n=self.i18n,
            parent=self,
        )
        self.settings_page = SettingsPage(
            config_mgr=self.config_mgr,
            steam_locator=self.steam_locator,
            get_config_fn=lambda: self.config,
            get_env_fn=lambda: self.env_status,
            i18n=self.i18n,
            parent=self,
        )
        self.updates_page = UpdatesPage(
            config_mgr=self.config_mgr,
            get_config_fn=lambda: self.config,
            project_root=self.project_root,
            i18n=self.i18n,
            parent=self,
        )

        self.navigationInterface.setExpandWidth(230)
        self._nav_convert_group = self.navigationInterface.addItem(
            routeKey="convert_group",
            icon=FluentIcon.SYNC,
            text=self.i18n.tr("nav_swap"),
            selectable=False,
            position=NavigationItemPosition.TOP,
            tooltip=self.i18n.tr("nav_swap"),
        )
        self._nav_convert_group.setRememberExpandState(True)
        self.stackedWidget.addWidget(self.swap_page)
        self.stackedWidget.addWidget(self.batch_page)
        self._nav_swap = self.navigationInterface.addItem(
            routeKey=self.swap_page.objectName(),
            icon=FluentIcon.DOCUMENT,
            text=self.i18n.tr("nav_swap_single"),
            onClick=lambda: self.switchTo(self.swap_page),
            position=NavigationItemPosition.TOP,
            tooltip=self.i18n.tr("nav_swap_single"),
            parentRouteKey="convert_group",
        )
        self._nav_batch = self.navigationInterface.addItem(
            routeKey=self.batch_page.objectName(),
            icon=FluentIcon.LIBRARY,
            text=self.i18n.tr("nav_batch"),
            onClick=lambda: self.switchTo(self.batch_page),
            position=NavigationItemPosition.TOP,
            tooltip=self.i18n.tr("nav_batch"),
            parentRouteKey="convert_group",
        )
        self.navigationInterface.displayModeChanged.connect(self._on_nav_display_mode_changed)
        self.switchTo(self.swap_page)
        self._nav_addons = self.addSubInterface(
            self.addons_page,
            FluentIcon.GAME,
            self.i18n.tr("nav_addons"),
            NavigationItemPosition.TOP,
        )
        self._nav_download = self.addSubInterface(
            self.download_page,
            FluentIcon.DOWNLOAD,
            self.i18n.tr("nav_download"),
            NavigationItemPosition.TOP,
        )
        self._nav_history = self.addSubInterface(
            self.history_page,
            FluentIcon.HISTORY,
            self.i18n.tr("nav_history"),
            NavigationItemPosition.TOP,
        )
        self._nav_env = self.addSubInterface(
            self.environment_page,
            FluentIcon.DEVELOPER_TOOLS,
            self.i18n.tr("nav_env"),
            NavigationItemPosition.TOP,
        )
        self._nav_updates = self.addSubInterface(
            self.updates_page,
            FluentIcon.UPDATE,
            self.i18n.tr("nav_updates"),
            NavigationItemPosition.BOTTOM,
        )
        self._updates_badge: Optional[InfoBadge] = None
        self._nav_settings = self.addSubInterface(
            self.settings_page,
            FluentIcon.SETTING,
            self.i18n.tr("nav_settings"),
            NavigationItemPosition.BOTTOM,
        )

        self.swap_page.conversionRecorded.connect(self.history_page.refresh_view)
        self.swap_page.addonsChanged.connect(self._on_addons_changed)
        self.batch_page.conversionRecorded.connect(self.history_page.refresh_view)
        self.batch_page.addonsChanged.connect(self._on_addons_changed)
        self.addons_page.loadModRequested.connect(self._open_source_in_swapper)
        self.download_page.sendToSwapRequested.connect(self._open_source_in_swapper)
        self.download_page.sendToBatchRequested.connect(self._open_sources_in_batch)
        self.download_page.addonsChanged.connect(self._on_addons_changed)
        self.history_page.reopenSourceRequested.connect(self._open_source_in_swapper)
        self.history_page.addonsChanged.connect(self._on_addons_changed)
        self.stackedWidget.currentChanged.connect(self._on_tab_changed)

        self.environment_page.environmentUpdated.connect(self.refresh_environment)
        self.environment_page.openWizardRequested.connect(self.open_setup_wizard)
        self.settings_page.environmentUpdated.connect(self.refresh_environment)
        self.settings_page.openWizardRequested.connect(self.open_setup_wizard)
        self.settings_page.themeChanged.connect(lambda pref: self.apply_theme_preference(pref, persist=True))
        self.settings_page.languageChanged.connect(lambda pref: self.apply_language_preference(pref, persist=True))
        self.updates_page.updateAvailabilityChanged.connect(self._on_update_availability_changed)
        self.updates_page.relaunchRequested.connect(self.close)

        self._connect_system_theme_listener()
        self.retranslate_ui()
        L4d2ThemeManager.apply_pointing_hand_cursors(self)
        L4d2ThemeManager.install_window_repaint_guard(self)

        self._wizard_timer = QTimer(self)
        self._wizard_timer.setSingleShot(True)
        self._wizard_timer.timeout.connect(self.open_setup_wizard)
        if not self.config.first_run_completed or not self.env_status.is_ready_for_swap:
            self._wizard_timer.start(200)

        self._update_check_timer = QTimer(self)
        self._update_check_timer.setSingleShot(True)
        self._update_check_timer.timeout.connect(self.updates_page.start_background_check_if_enabled)
        self._update_check_timer.start(1200)

    def _connect_system_theme_listener(self) -> None:
        app = QGuiApplication.instance()
        if app is None:
            return
        try:
            QGuiApplication.styleHints().colorSchemeChanged.connect(self._on_system_color_scheme_changed)
        except Exception:
            pass

    def _on_system_color_scheme_changed(self, _scheme) -> None:
        if (self.config.theme or "Dark").strip().lower() in ("system", "auto"):
            L4d2ThemeManager.apply_window_theme(self, "System")
            self.settings_page.retranslate_ui(self.i18n)

    def apply_theme_preference(self, preference: str, persist: bool = False) -> None:
        self.config.theme = preference
        if persist:
            self.config_mgr.save(self.config)
        L4d2ThemeManager.apply_window_theme(self, preference)
        self.swap_page.retranslate_ui(self.i18n)
        self.batch_page.retranslate_ui(self.i18n)
        self.addons_page.retranslate_ui(self.i18n)
        self.download_page.retranslate_ui(self.i18n)
        self.history_page.retranslate_ui(self.i18n)
        self.updates_page.retranslate_ui(self.i18n)
        L4d2ThemeManager.refresh_window_tree(self, relayout=True)

    def apply_language_preference(self, preference: str, persist: bool = False) -> None:
        self.config.language = preference
        if persist:
            self.config_mgr.save(self.config)
        self.i18n.set_preference(preference)
        self.retranslate_ui()

    def retranslate_ui(self) -> None:
        self.setWindowTitle(APP_META.window_title)
        self._nav_convert_group.setText(self.i18n.tr("nav_swap"))
        self._nav_convert_group.setToolTip(self.i18n.tr("nav_swap"))
        self._nav_swap.setText(self.i18n.tr("nav_swap_single"))
        self._nav_swap.setToolTip(self.i18n.tr("nav_swap_single"))
        self._nav_batch.setText(self.i18n.tr("nav_batch"))
        self._nav_batch.setToolTip(self.i18n.tr("nav_batch"))
        self._nav_addons.setText(self.i18n.tr("nav_addons"))
        self._nav_addons.setToolTip(self.i18n.tr("nav_addons"))
        self._nav_download.setText(self.i18n.tr("nav_download"))
        self._nav_download.setToolTip(self.i18n.tr("nav_download"))
        self._nav_history.setText(self.i18n.tr("nav_history"))
        self._nav_history.setToolTip(self.i18n.tr("nav_history"))
        self._nav_env.setText(self.i18n.tr("nav_env"))
        self._nav_env.setToolTip(self.i18n.tr("nav_env"))
        self._nav_updates.setText(self.i18n.tr("nav_updates"))
        self._nav_updates.setToolTip(self.i18n.tr("nav_updates"))
        self._nav_settings.setText(self.i18n.tr("nav_settings"))
        self._nav_settings.setToolTip(self.i18n.tr("nav_settings"))
        self.swap_page.retranslate_ui(self.i18n)
        self.batch_page.retranslate_ui(self.i18n)
        self.addons_page.retranslate_ui(self.i18n)
        self.download_page.retranslate_ui(self.i18n)
        self.history_page.retranslate_ui(self.i18n)
        self.environment_page.retranslate_ui(self.i18n)
        self.updates_page.retranslate_ui(self.i18n)
        self.settings_page.retranslate_ui(self.i18n)
        L4d2ThemeManager.apply_label_colors(self)
        L4d2ThemeManager.apply_pointing_hand_cursors(self)

    def _on_update_availability_changed(self, available: bool, version_tag: str) -> None:
        if available:
            if self._updates_badge is None:
                badge_parent = self._nav_updates.parentWidget() or self.navigationInterface.panel
                self._updates_badge = InfoBadge.warning(
                    "1",
                    parent=badge_parent,
                    target=self._nav_updates,
                    position=InfoBadgePosition.NAVIGATION_ITEM,
                )
            self._updates_badge.show()
            if version_tag:
                self._nav_updates.setToolTip(f"{self.i18n.tr('nav_updates')} ({version_tag})")
        else:
            if self._updates_badge is not None:
                self._updates_badge.hide()
                self._updates_badge.setParent(None)
                self._updates_badge.deleteLater()
                self._updates_badge = None
            self._nav_updates.setToolTip(self.i18n.tr("nav_updates"))

    def _on_nav_display_mode_changed(self, mode: NavigationDisplayMode) -> None:
        if mode == NavigationDisplayMode.COMPACT:
            self._nav_convert_group.setExpanded(False, ani=False)
        else:
            self._nav_convert_group.setExpanded(True, ani=False)

    def _on_tab_changed(self, _index: int) -> None:
        current = self.stackedWidget.currentWidget()
        if current is self.addons_page:
            self.addons_page.refresh_view()
        elif current is self.download_page:
            self.download_page.refresh_library()
        elif current is self.history_page:
            self.history_page.refresh_view()

    def _on_addons_changed(self) -> None:
        if self.stackedWidget.currentWidget() is self.addons_page:
            self.addons_page.refresh_view()

    def _open_source_in_swapper(self, source_path: Path) -> None:
        self.switchTo(self.swap_page)
        self.swap_page._on_source_selected(source_path)

    def _open_sources_in_batch(self, source_paths: list[Path]) -> None:
        self.switchTo(self.batch_page)
        self.batch_page.add_sources(source_paths)

    def refresh_environment(self) -> None:
        self.env_status = self.steam_locator.inspect_environment(self.config)
        self._sync_detected_paths_into_config()
        self.environment_page.refresh_view()
        self.settings_page.load_from_state()
        if self.stackedWidget.currentWidget() is self.addons_page:
            self.addons_page.refresh_view()
        elif self.stackedWidget.currentWidget() is self.download_page:
            self.download_page.refresh_library()

    def open_setup_wizard(self) -> None:
        dialog = SetupWizardDialog(
            config_mgr=self.config_mgr,
            steam_locator=self.steam_locator,
            config=self.config,
            i18n=self.i18n,
            parent=self,
        )
        dialog.languageChanged.connect(lambda pref: self.apply_language_preference(pref, persist=True))
        dialog.exec()
        self.refresh_environment()
        self.settings_page.load_from_state()

    def _apply_window_icon(self) -> None:
        if not self._app_icon_path.is_file():
            return
        icon = QIcon(str(self._app_icon_path))
        if icon.isNull():
            return
        app = QApplication.instance()
        if app is not None:
            app.setWindowIcon(icon)
        self.setWindowIcon(icon)
        title_bar = getattr(self, "titleBar", None)
        if title_bar is not None and hasattr(title_bar, "setIcon"):
            title_bar.setIcon(icon)

    def _apply_native_win32_icons(self) -> None:
        if sys.platform != "win32" or not self._app_icon_path.is_file():
            return
        app = QGuiApplication.instance()
        if app is None or app.platformName().strip().lower() not in ("windows", "direct2d"):
            return
        try:
            import ctypes
            from ctypes import wintypes

            user32 = ctypes.windll.user32
            user32.LoadImageW.argtypes = [
                wintypes.HINSTANCE,
                wintypes.LPCWSTR,
                wintypes.UINT,
                ctypes.c_int,
                ctypes.c_int,
                wintypes.UINT,
            ]
            user32.LoadImageW.restype = wintypes.HANDLE
            user32.SendMessageW.argtypes = [wintypes.HWND, wintypes.UINT, wintypes.WPARAM, wintypes.LPARAM]
            user32.SendMessageW.restype = ctypes.c_ssize_t

            hwnd = int(self.winId())
            if not hwnd:
                return
            if not self._native_icon_handles:
                path_str = str(self._app_icon_path)
                small_h = user32.LoadImageW(None, path_str, 1, 16, 16, 0x0010)
                big_h = user32.LoadImageW(None, path_str, 1, 256, 256, 0x0010)
                if small_h:
                    self._native_icon_handles.append(int(small_h))
                if big_h:
                    self._native_icon_handles.append(int(big_h))
            if self._native_icon_handles:
                user32.SendMessageW(hwnd, 0x0080, 0, self._native_icon_handles[0])
                user32.SendMessageW(hwnd, 0x0080, 1, self._native_icon_handles[-1])
        except Exception:
            pass

    def _release_native_win32_icons(self) -> None:
        if sys.platform != "win32" or not self._native_icon_handles:
            return
        try:
            import ctypes
            from ctypes import wintypes

            user32 = ctypes.windll.user32
            user32.DestroyIcon.argtypes = [wintypes.HICON]
            user32.DestroyIcon.restype = wintypes.BOOL
            for hicon in self._native_icon_handles:
                if hicon:
                    user32.DestroyIcon(hicon)
        except Exception:
            pass
        self._native_icon_handles.clear()

    def showEvent(self, event: QShowEvent) -> None:
        if hasattr(self, "setMicaEffectEnabled"):
            self.setMicaEffectEnabled(False)
        super().showEvent(event)
        self._apply_window_icon()
        self._apply_native_win32_icons()
        L4d2ThemeManager.refresh_window_tree(self, relayout=True)

    def closeEvent(self, event: QCloseEvent) -> None:
        self._wizard_timer.stop()
        self._update_check_timer.stop()
        self.swap_page.shutdown_worker()
        self.batch_page.shutdown_worker()
        self.download_page.shutdown_worker()
        self.addons_page.shutdown_scan()
        self.updates_page.shutdown_worker()
        self._release_native_win32_icons()
        super().closeEvent(event)

    def _sync_detected_paths_into_config(self) -> None:
        changed = False
        pairs = [
            ("l4d2_dir", self.env_status.l4d2_dir),
            ("studiomdl_executable", self.env_status.studiomdl_path),
            ("vpk_executable", self.env_status.vpk_exe_path),
        ]
        for attr, detected in pairs:
            current = getattr(self.config, attr, "")
            is_missing = bool(current) and not Path(current).exists()
            if (not current or is_missing) and detected is not None:
                setattr(self.config, attr, str(detected))
                changed = True
            elif is_missing and detected is None:
                setattr(self.config, attr, "")
                changed = True
        if changed:
            self.config_mgr.save(self.config)


def _set_windows_app_user_model_id() -> None:
    if sys.platform != "win32":
        return
    if os.environ.get("QT_QPA_PLATFORM", "").strip().lower() == "offscreen":
        return
    try:
        import ctypes

        ctypes.windll.shell32.SetCurrentProcessExplicitAppUserModelID(
            "SrCaveira.L4D2SurvivorSwapperTool.App"
        )
    except Exception:
        pass


def launch_gui(project_root: Optional[Path] = None) -> int:
    _set_windows_app_user_model_id()
    app = QApplication.instance() or QApplication([])
    root = project_root or Path(__file__).resolve().parent.parent
    app_icon = root / "ui" / "app_icon.ico"
    if app_icon.is_file():
        app.setWindowIcon(QIcon(str(app_icon)))
    window = MainWindow(project_root=root)
    window.showMaximized()
    return app.exec()
