from __future__ import annotations

import os
from typing import Optional

from PySide6.QtCore import QUrl, Qt, Signal
from PySide6.QtGui import QDesktopServices
from PySide6.QtWidgets import QGridLayout, QHBoxLayout, QSizePolicy, QVBoxLayout, QWidget
from qfluentwidgets import (
    BodyLabel,
    CaptionLabel,
    CardWidget,
    FluentIcon,
    IconWidget,
    InfoBadge,
    InfoBar,
    InfoBarPosition,
    InfoLevel,
    PrimaryPushButton,
    PushButton,
    ScrollArea,
    StrongBodyLabel,
    SubtitleLabel,
)

from core.config_manager import ConfigManager
from core.crowbar_settings import CrowbarSettingsManager
from core.i18n import LocalizationManager
from core.models import AppConfig, EnvironmentStatus
from core.steam_locator import SteamLocator
from ui.theme import L4d2ThemeManager
from ui.widgets import create_icon_row


class EnvironmentPage(ScrollArea):
    """Dedicated visual diagnostics page for L4D2, Authoring Tools, Decompiler CLI, and Crowbar XML."""

    environmentUpdated = Signal()
    openWizardRequested = Signal()

    def __init__(
        self,
        config_mgr: ConfigManager,
        steam_locator: SteamLocator,
        get_config_fn,
        get_env_fn,
        i18n: Optional[LocalizationManager] = None,
        parent: Optional[QWidget] = None,
    ) -> None:
        super().__init__(parent)
        self.setObjectName("environmentPage")
        self.config_mgr = config_mgr
        self.steam_locator = steam_locator
        self._get_config = get_config_fn
        self._get_env = get_env_fn
        self._i18n = i18n or LocalizationManager("en-US")

        self.view = QWidget(self)
        self.setWidget(self.view)
        self.setWidgetResizable(True)
        self.enableTransparentBackground()

        layout = QVBoxLayout(self.view)
        layout.setContentsMargins(28, 24, 28, 28)
        layout.setSpacing(16)

        self.page_title = SubtitleLabel("", self.view)
        self.page_subtitle = BodyLabel("", self.view)
        self.page_subtitle.setWordWrap(True)
        self.page_subtitle.setSizePolicy(QSizePolicy.Policy.Ignored, QSizePolicy.Policy.Preferred)
        layout.addLayout(create_icon_row(FluentIcon.DEVELOPER_TOOLS, self.page_title, self.view))
        layout.addWidget(self.page_subtitle)

        cards_grid = QGridLayout()
        cards_grid.setSpacing(14)

        self.l4d2_card, self.l4d2_title, self.l4d2_badge, self.l4d2_detail = self._make_status_card(FluentIcon.GAME)
        self.tools_card, self.tools_title, self.tools_badge, self.tools_detail = self._make_status_card(
            FluentIcon.DEVELOPER_TOOLS
        )
        self.decomp_card, self.decomp_title, self.decomp_badge, self.decomp_detail = self._make_status_card(
            FluentIcon.COMMAND_PROMPT
        )
        self.crowbar_card, self.crowbar_title, self.crowbar_badge, self.crowbar_detail = self._make_status_card(
            FluentIcon.CODE
        )

        cards_grid.addWidget(self.l4d2_card, 0, 0)
        cards_grid.addWidget(self.tools_card, 0, 1)
        cards_grid.addWidget(self.decomp_card, 1, 0)
        cards_grid.addWidget(self.crowbar_card, 1, 1)
        cards_grid.setColumnStretch(0, 1)
        cards_grid.setColumnStretch(1, 1)
        layout.addLayout(cards_grid)

        action_grid = QGridLayout()
        action_grid.setSpacing(10)
        self.recheck_btn = PrimaryPushButton(FluentIcon.SEARCH, "", self.view)
        self.wizard_btn = PushButton(FluentIcon.DEVELOPER_TOOLS, "", self.view)
        self.sync_crowbar_btn = PushButton(FluentIcon.SYNC, "", self.view)
        self.open_addons_btn = PushButton(FluentIcon.FOLDER, "", self.view)

        for idx, btn in enumerate((self.recheck_btn, self.wizard_btn, self.sync_crowbar_btn, self.open_addons_btn)):
            btn.setCursor(Qt.CursorShape.PointingHandCursor)
            action_grid.addWidget(btn, idx // 2, idx % 2)
        action_grid.setColumnStretch(2, 1)
        layout.addLayout(action_grid)
        layout.addStretch(1)

        self.recheck_btn.clicked.connect(self._on_autodetect)
        self.wizard_btn.clicked.connect(self.openWizardRequested.emit)
        self.sync_crowbar_btn.clicked.connect(self._on_sync_crowbar)
        self.open_addons_btn.clicked.connect(self._on_open_addons)

        self.retranslate_ui(self._i18n)
        self.refresh_view()

    def _make_status_card(self, icon: FluentIcon) -> tuple[CardWidget, StrongBodyLabel, InfoBadge, CaptionLabel]:
        card = CardWidget(self.view)
        vbox = QVBoxLayout(card)
        vbox.setContentsMargins(18, 16, 18, 16)
        vbox.setSpacing(8)

        header = QHBoxLayout()
        header.setSpacing(8)
        icon_widget = IconWidget(icon, card)
        icon_widget.setFixedSize(16, 16)
        title = StrongBodyLabel("", card)
        badge = InfoBadge("", card, level=InfoLevel.INFOAMTION)
        header.addWidget(icon_widget, 0, Qt.AlignmentFlag.AlignVCenter)
        header.addWidget(title)
        header.addStretch(1)
        header.addWidget(badge)
        vbox.addLayout(header)

        detail = CaptionLabel("", card)
        detail.setWordWrap(True)
        detail.setSizePolicy(QSizePolicy.Policy.Ignored, QSizePolicy.Policy.MinimumExpanding)
        vbox.addWidget(detail)
        vbox.addStretch(1)
        return card, title, badge, detail

    def retranslate_ui(self, i18n: LocalizationManager) -> None:
        self._i18n = i18n
        self.page_title.setText(i18n.tr("env_page_title"))
        self.page_subtitle.setText(i18n.tr("env_page_subtitle"))

        self.l4d2_title.setText(i18n.tr("env_card_l4d2_title"))
        self.tools_title.setText(i18n.tr("env_card_tools_title"))
        self.decomp_title.setText(i18n.tr("env_card_decomp_title"))
        self.crowbar_title.setText(i18n.tr("env_card_crowbar_title"))

        self.recheck_btn.setText(i18n.tr("btn_autodetect"))
        self.wizard_btn.setText(i18n.tr("btn_run_wizard"))
        self.sync_crowbar_btn.setText(i18n.tr("btn_sync_crowbar"))
        self.open_addons_btn.setText(i18n.tr("env_open_addons"))

        self.refresh_view()
        L4d2ThemeManager.apply_pointing_hand_cursors(self)

    def refresh_view(self) -> None:
        env: EnvironmentStatus = self._get_env()

        if env.l4d2_installed and env.l4d2_dir:
            self._set_badge(self.l4d2_badge, self._i18n.tr("badge_detected"), InfoLevel.SUCCESS)
            self.l4d2_detail.setText(self._i18n.tr("env_path_label", path=env.l4d2_dir))
        else:
            self._set_badge(self.l4d2_badge, self._i18n.tr("badge_missing"), InfoLevel.ERROR)
            self.l4d2_detail.setText(self._i18n.tr("env_missing_label"))

        if env.studiomdl_path and env.vpk_exe_path:
            self._set_badge(self.tools_badge, self._i18n.tr("badge_ready"), InfoLevel.SUCCESS)
            self.tools_detail.setText(
                self._i18n.tr(
                    "env_tools_detail",
                    studiomdl=env.studiomdl_path,
                    vpk=env.vpk_exe_path,
                )
            )
        else:
            self._set_badge(self.tools_badge, self._i18n.tr("badge_action_needed"), InfoLevel.ERROR)
            self.tools_detail.setText(self._i18n.tr("env_missing_label"))

        if env.decompiler_cli_path and env.decompiler_cli_path.exists():
            self._set_badge(self.decomp_badge, self._i18n.tr("badge_ready"), InfoLevel.SUCCESS)
            self.decomp_detail.setText(self._i18n.tr("env_decomp_detail", path=env.decompiler_cli_path))
        else:
            self._set_badge(self.decomp_badge, self._i18n.tr("badge_missing"), InfoLevel.ERROR)
            self.decomp_detail.setText(self._i18n.tr("env_missing_label"))

        if env.crowbar_settings_valid:
            self._set_badge(self.crowbar_badge, self._i18n.tr("badge_configured"), InfoLevel.SUCCESS)
            self.crowbar_detail.setText(
                self._i18n.tr("env_crowbar_valid_detail", path=env.crowbar_settings_path)
            )
        else:
            self._set_badge(self.crowbar_badge, self._i18n.tr("badge_needs_sync"), InfoLevel.WARNING)
            issue = env.crowbar_issues[0] if env.crowbar_issues else "Crowbar Settings.xml"
            self.crowbar_detail.setText(
                self._i18n.tr("env_crowbar_invalid_detail", path=env.crowbar_settings_path, issue=issue)
            )

        self.open_addons_btn.setEnabled(env.l4d2_addons_dir is not None)
        L4d2ThemeManager.apply_pointing_hand_cursors(self)

    @staticmethod
    def _set_badge(badge: InfoBadge, text: str, level: InfoLevel) -> None:
        badge.setText(text)
        badge.setLevel(level)

    def _on_autodetect(self) -> None:
        cfg: AppConfig = self._get_config()
        cfg.l4d2_dir = ""
        cfg.studiomdl_executable = ""
        cfg.vpk_executable = ""
        self.environmentUpdated.emit()
        self.refresh_view()
        InfoBar.success(
            self._i18n.tr("info_autodetect_title"),
            self._i18n.tr("info_autodetect_msg"),
            parent=self.window(),
            position=InfoBarPosition.TOP,
        )

    def _on_sync_crowbar(self) -> None:
        env: EnvironmentStatus = self._get_env()
        try:
            CrowbarSettingsManager().apply(l4d2_dir=env.l4d2_dir, create_backup=True)
            self.environmentUpdated.emit()
            self.refresh_view()
            InfoBar.success(
                self._i18n.tr("info_crowbar_synced_title"),
                self._i18n.tr("info_crowbar_synced_msg"),
                parent=self.window(),
                position=InfoBarPosition.TOP,
            )
        except Exception as exc:
            InfoBar.error(
                self._i18n.tr("info_sync_err_title"),
                str(exc),
                parent=self.window(),
                position=InfoBarPosition.TOP,
            )

    def _on_open_addons(self) -> None:
        addons_dir = self._get_env().l4d2_addons_dir
        if addons_dir is None:
            InfoBar.warning(
                self._i18n.tr("info_addons_missing_title"),
                self._i18n.tr("info_addons_missing_msg"),
                parent=self.window(),
                position=InfoBarPosition.TOP,
            )
            return
        addons_dir.mkdir(parents=True, exist_ok=True)
        try:
            os.startfile(str(addons_dir))
        except OSError:
            QDesktopServices.openUrl(QUrl.fromLocalFile(str(addons_dir)))
