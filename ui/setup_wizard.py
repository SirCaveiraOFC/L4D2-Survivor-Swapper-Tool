from __future__ import annotations

from pathlib import Path
from typing import Optional

from PySide6.QtCore import QUrl, Signal
from PySide6.QtGui import QDesktopServices
from PySide6.QtWidgets import QFileDialog, QHBoxLayout, QVBoxLayout, QWidget
from qfluentwidgets import (
    BodyLabel,
    CaptionLabel,
    CardWidget,
    ComboBox,
    FluentIcon,
    IconWidget,
    InfoBadge,
    InfoBar,
    InfoBarPosition,
    InfoLevel,
    MessageBoxBase,
    PrimaryPushButton,
    PushButton,
    StrongBodyLabel,
    SubtitleLabel,
)

from core.config_manager import ConfigManager
from core.crowbar_settings import CrowbarSettingsManager
from core.i18n import SUPPORTED_LANGUAGES, LocalizationManager
from core.models import AppConfig, EnvironmentStatus
from core.steam_locator import SteamLocator
from ui.theme import L4d2ThemeManager
from ui.widgets import create_icon_row


class SetupWizardDialog(MessageBoxBase):
    """First-run wizard verifying L4D2, Authoring Tools, Crowbar settings, and language."""

    languageChanged = Signal(str)

    def __init__(
        self,
        config_mgr: ConfigManager,
        steam_locator: SteamLocator,
        config: AppConfig,
        i18n: Optional[LocalizationManager] = None,
        parent: Optional[QWidget] = None,
    ) -> None:
        super().__init__(parent)
        self.config_mgr = config_mgr
        self.steam_locator = steam_locator
        self.config = config
        self._i18n = i18n or LocalizationManager(config.language)
        self.env_status: EnvironmentStatus = self.steam_locator.inspect_environment(self.config)

        self.widget.setMinimumWidth(680)

        self.title_label = SubtitleLabel("", self.widget)
        self.subtitle_label = BodyLabel("", self.widget)
        self.subtitle_label.setWordWrap(True)

        lang_row = QHBoxLayout()
        self.lang_label = CaptionLabel("", self.widget)
        self.lang_combo = ComboBox(self.widget)
        self.lang_combo.addItem("", userData="auto")
        for code, display in SUPPORTED_LANGUAGES.items():
            self.lang_combo.addItem(display, userData=code)
        lang_idx = self.lang_combo.findData(self.config.language)
        self.lang_combo.setCurrentIndex(lang_idx if lang_idx >= 0 else 0)
        lang_row.addWidget(self.lang_label)
        lang_row.addWidget(self.lang_combo)
        lang_row.addStretch(1)

        self.viewLayout.addLayout(
            create_icon_row(FluentIcon.DEVELOPER_TOOLS, self.title_label, self.widget, size=20, spacing=10)
        )
        self.viewLayout.addWidget(self.subtitle_label)
        self.viewLayout.addLayout(lang_row)

        self.l4d2_card = CardWidget(self.widget)
        l4d2_lay = QVBoxLayout(self.l4d2_card)
        l4d2_row = QHBoxLayout()
        l4d2_row.setSpacing(8)
        l4d2_icon = IconWidget(FluentIcon.GAME, self.l4d2_card)
        l4d2_icon.setFixedSize(16, 16)
        self.l4d2_badge = InfoBadge("", self.l4d2_card, level=InfoLevel.INFOAMTION)
        self.l4d2_title_label = StrongBodyLabel("", self.l4d2_card)
        l4d2_row.addWidget(l4d2_icon)
        l4d2_row.addWidget(self.l4d2_title_label)
        l4d2_row.addStretch(1)
        l4d2_row.addWidget(self.l4d2_badge)
        l4d2_lay.addLayout(l4d2_row)
        self.l4d2_path_label = CaptionLabel("", self.l4d2_card)
        self.l4d2_path_label.setWordWrap(True)
        l4d2_lay.addWidget(self.l4d2_path_label)
        l4d2_btns = QHBoxLayout()
        self.browse_l4d2_btn = PushButton(FluentIcon.FOLDER, "", self.l4d2_card)
        l4d2_btns.addWidget(self.browse_l4d2_btn)
        l4d2_btns.addStretch(1)
        l4d2_lay.addLayout(l4d2_btns)
        self.viewLayout.addWidget(self.l4d2_card)

        self.tools_card = CardWidget(self.widget)
        tools_lay = QVBoxLayout(self.tools_card)
        tools_row = QHBoxLayout()
        tools_row.setSpacing(8)
        tools_icon = IconWidget(FluentIcon.DEVELOPER_TOOLS, self.tools_card)
        tools_icon.setFixedSize(16, 16)
        self.tools_badge = InfoBadge("", self.tools_card, level=InfoLevel.INFOAMTION)
        self.tools_title_label = StrongBodyLabel("", self.tools_card)
        tools_row.addWidget(tools_icon)
        tools_row.addWidget(self.tools_title_label)
        tools_row.addStretch(1)
        tools_row.addWidget(self.tools_badge)
        tools_lay.addLayout(tools_row)
        self.tools_detail_label = CaptionLabel("", self.tools_card)
        self.tools_detail_label.setWordWrap(True)
        tools_lay.addWidget(self.tools_detail_label)
        tools_btns = QHBoxLayout()
        self.install_tools_btn = PrimaryPushButton(FluentIcon.DOWNLOAD, "", self.tools_card)
        self.recheck_btn = PushButton(FluentIcon.SYNC, "", self.tools_card)
        tools_btns.addWidget(self.install_tools_btn)
        tools_btns.addWidget(self.recheck_btn)
        tools_btns.addStretch(1)
        tools_lay.addLayout(tools_btns)
        self.viewLayout.addWidget(self.tools_card)

        self.crowbar_card = CardWidget(self.widget)
        cb_lay = QVBoxLayout(self.crowbar_card)
        cb_row = QHBoxLayout()
        cb_row.setSpacing(8)
        cb_icon = IconWidget(FluentIcon.CODE, self.crowbar_card)
        cb_icon.setFixedSize(16, 16)
        self.crowbar_badge = InfoBadge("", self.crowbar_card, level=InfoLevel.INFOAMTION)
        self.crowbar_title_label = StrongBodyLabel("", self.crowbar_card)
        cb_row.addWidget(cb_icon)
        cb_row.addWidget(self.crowbar_title_label)
        cb_row.addStretch(1)
        cb_row.addWidget(self.crowbar_badge)
        cb_lay.addLayout(cb_row)
        self.crowbar_detail_label = CaptionLabel("", self.crowbar_card)
        self.crowbar_detail_label.setWordWrap(True)
        cb_lay.addWidget(self.crowbar_detail_label)
        cb_btns = QHBoxLayout()
        self.sync_crowbar_btn = PushButton(FluentIcon.SETTING, "", self.crowbar_card)
        cb_btns.addWidget(self.sync_crowbar_btn)
        cb_btns.addStretch(1)
        cb_lay.addLayout(cb_btns)
        self.viewLayout.addWidget(self.crowbar_card)

        self.browse_l4d2_btn.clicked.connect(self._on_browse_l4d2)
        self.install_tools_btn.clicked.connect(self._on_install_authoring_tools)
        self.recheck_btn.clicked.connect(self.refresh_status)
        self.sync_crowbar_btn.clicked.connect(self._on_sync_crowbar)
        self.lang_combo.currentIndexChanged.connect(self._on_language_selected)
        self.accepted.connect(self._on_finish)

        self.retranslate_ui(self._i18n)
        self.refresh_status()

    def retranslate_ui(self, i18n: LocalizationManager) -> None:
        self._i18n = i18n
        self.yesButton.setText(i18n.tr("wizard_finish"))
        self.cancelButton.setText(i18n.tr("wizard_close"))
        self.title_label.setText(i18n.tr("wizard_title"))
        self.subtitle_label.setText(i18n.tr("wizard_subtitle"))
        self.lang_label.setText(i18n.tr("wizard_lang_label"))

        detected_lang = LocalizationManager.detect_system_language()
        detected_name = SUPPORTED_LANGUAGES.get(detected_lang, detected_lang)
        self.lang_combo.blockSignals(True)
        self.lang_combo.setItemText(0, i18n.tr("lang_auto", resolved=detected_name))
        self.lang_combo.blockSignals(False)

        self.l4d2_title_label.setText(i18n.tr("wizard_card1_title"))
        self.browse_l4d2_btn.setText(i18n.tr("wizard_browse_l4d2"))
        self.tools_title_label.setText(i18n.tr("wizard_card2_title"))
        self.install_tools_btn.setText(i18n.tr("wizard_install_tools"))
        self.recheck_btn.setText(i18n.tr("wizard_recheck"))
        self.crowbar_title_label.setText(i18n.tr("wizard_card3_title"))
        self.sync_crowbar_btn.setText(i18n.tr("wizard_sync_crowbar"))
        L4d2ThemeManager.apply_pointing_hand_cursors(self)
        L4d2ThemeManager.enable_card_hover(self.widget)

    def _on_language_selected(self) -> None:
        selected = str(self.lang_combo.currentData() or "auto")
        self.config.language = selected
        self._i18n.set_preference(selected)
        self.retranslate_ui(self._i18n)
        self.refresh_status()
        self.languageChanged.emit(selected)

    def refresh_status(self) -> None:
        self.env_status = self.steam_locator.inspect_environment(self.config)
        st = self.env_status

        if st.l4d2_installed and st.l4d2_dir:
            self._set_badge(self.l4d2_badge, self._i18n.tr("badge_detected"), InfoLevel.SUCCESS)
            self.l4d2_path_label.setText(self._i18n.tr("wizard_found_at", path=st.l4d2_dir))
            self.config.l4d2_dir = str(st.l4d2_dir)
        else:
            self._set_badge(self.l4d2_badge, self._i18n.tr("badge_missing"), InfoLevel.ERROR)
            self.l4d2_path_label.setText(self._i18n.tr("wizard_l4d2_missing"))

        if st.studiomdl_path and st.vpk_exe_path and st.decompiler_cli_path:
            self._set_badge(self.tools_badge, self._i18n.tr("badge_ready"), InfoLevel.SUCCESS)
            self.tools_detail_label.setText(
                f"studiomdl.exe: {st.studiomdl_path}\n"
                f"vpk.exe: {st.vpk_exe_path}\n"
                f"Decompiler CLI: {st.decompiler_cli_path}"
            )
            self.config.studiomdl_executable = str(st.studiomdl_path)
            self.config.vpk_executable = str(st.vpk_exe_path)
            self.install_tools_btn.setVisible(False)
        else:
            self._set_badge(self.tools_badge, self._i18n.tr("badge_action_needed"), InfoLevel.ERROR)
            missing = []
            if not st.studiomdl_path:
                missing.append("studiomdl.exe")
            if not st.vpk_exe_path:
                missing.append("vpk.exe")
            if not st.decompiler_cli_path:
                missing.append("MdlDecompilerCli.exe")
            self.tools_detail_label.setText(
                self._i18n.tr("wizard_tools_missing", missing=", ".join(missing))
            )
            self.install_tools_btn.setVisible(True)

        if st.crowbar_settings_valid:
            self._set_badge(self.crowbar_badge, self._i18n.tr("badge_configured"), InfoLevel.SUCCESS)
            self.crowbar_detail_label.setText(
                self._i18n.tr("wizard_crowbar_verified", path=st.crowbar_settings_path)
            )
        else:
            self._set_badge(self.crowbar_badge, self._i18n.tr("badge_needs_sync"), InfoLevel.WARNING)
            summary = st.crowbar_issues[0] if st.crowbar_issues else "Crowbar Settings.xml"
            self.crowbar_detail_label.setText(
                self._i18n.tr("wizard_crowbar_note", path=st.crowbar_settings_path, issue=summary)
            )

        self.yesButton.setEnabled(st.is_ready_for_swap)

    @staticmethod
    def _set_badge(badge: InfoBadge, text: str, level: InfoLevel) -> None:
        badge.setText(text)
        badge.setLevel(level)

    def _on_browse_l4d2(self) -> None:
        folder = QFileDialog.getExistingDirectory(self, self._i18n.tr("wizard_dlg_l4d2_title"))
        if folder:
            chosen = Path(folder)
            if not (chosen / "left4dead2" / "gameinfo.txt").exists():
                InfoBar.warning(
                    self._i18n.tr("wizard_invalid_l4d2_title"),
                    self._i18n.tr("wizard_invalid_l4d2_msg"),
                    parent=self.window(),
                    position=InfoBarPosition.TOP,
                )
                return
            self.config.l4d2_dir = str(chosen)
            self.refresh_status()

    def _on_install_authoring_tools(self) -> None:
        QDesktopServices.openUrl(QUrl(f"steam://install/{SteamLocator.AUTHORING_TOOLS_APP_ID}"))

    def _on_sync_crowbar(self) -> None:
        mgr = CrowbarSettingsManager()
        try:
            mgr.apply(l4d2_dir=self.env_status.l4d2_dir, create_backup=True)
            InfoBar.success(
                self._i18n.tr("wizard_crowbar_ok_title"),
                self._i18n.tr("wizard_crowbar_ok_msg"),
                parent=self.window(),
                position=InfoBarPosition.TOP,
            )
            self.refresh_status()
        except Exception as exc:
            InfoBar.error(
                self._i18n.tr("wizard_crowbar_fail_title"),
                str(exc),
                parent=self.window(),
                position=InfoBarPosition.TOP,
            )

    def _on_finish(self) -> None:
        self.config.first_run_completed = True
        self.config_mgr.save(self.config)
