from __future__ import annotations

from typing import Optional

from PySide6.QtCore import Qt, Signal
from PySide6.QtWidgets import QFileDialog, QFormLayout, QHBoxLayout, QVBoxLayout, QWidget
from qfluentwidgets import (
    BodyLabel,
    CaptionLabel,
    ComboBox,
    FluentIcon,
    HeaderCardWidget,
    InfoBadge,
    InfoBar,
    InfoBarPosition,
    InfoLevel,
    LineEdit,
    PrimaryPushButton,
    PushButton,
    ScrollArea,
    StrongBodyLabel,
    SubtitleLabel,
)

from core.app_meta import APP_META
from core.config_manager import ConfigManager
from core.i18n import SUPPORTED_LANGUAGES, LocalizationManager
from core.models import AppConfig, EnvironmentStatus
from core.steam_locator import SteamLocator
from ui.theme import L4d2ThemeManager
from ui.widgets import (
    add_card_header_icon,
    create_icon_row,
    create_switch_with_help,
    update_switch_help,
)


class SettingsPage(ScrollArea):
    """Settings, theme/language selection, and About Application details."""

    environmentUpdated = Signal()
    openWizardRequested = Signal()
    themeChanged = Signal(str)
    languageChanged = Signal(str)

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
        self.setObjectName("settingsPage")
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
        layout.addLayout(create_icon_row(FluentIcon.SETTING, self.page_title, self.view))

        self.paths_card = HeaderCardWidget(self.view)
        add_card_header_icon(self.paths_card, FluentIcon.FOLDER)
        paths_inner = QWidget(self.paths_card)
        form = QFormLayout(paths_inner)
        form.setSpacing(10)

        self._form_labels: dict[str, BodyLabel] = {}
        self._browse_buttons: list[PushButton] = []

        self.l4d2_edit = self._path_row(form, "lbl_l4d2_dir", is_dir=True)
        self.studiomdl_edit = self._path_row(form, "lbl_studiomdl", is_dir=False, exe_filter="studiomdl.exe")
        self.vpk_edit = self._path_row(form, "lbl_vpk_exe", is_dir=False, exe_filter="vpk.exe")
        self.output_edit = self._path_row(form, "lbl_output_dir", is_dir=True)
        self.workshop_dir_edit = self._path_row(form, "lbl_workshop_download_dir", is_dir=True)
        self.kit_edit = self._path_row(form, "lbl_kit_dir", is_dir=True)

        self.paths_card.viewLayout.addWidget(paths_inner)
        layout.addWidget(self.paths_card)

        self.pref_card = HeaderCardWidget(self.view)
        add_card_header_icon(self.pref_card, FluentIcon.PALETTE)
        pref_inner = QWidget(self.pref_card)
        pref_form = QFormLayout(pref_inner)
        pref_form.setSpacing(10)

        auto_install_row, self.auto_install_switch, self.help_auto_install = create_switch_with_help(
            "", False, "", pref_inner
        )
        keep_temp_row, self.keep_temp_switch, self.help_keep_temp = create_switch_with_help(
            "", False, "", pref_inner
        )

        self.theme_combo = ComboBox(pref_inner)
        self.theme_combo.addItem("", userData="System")
        self.theme_combo.addItem("", userData="Dark")
        self.theme_combo.addItem("", userData="Light")

        self.language_combo = ComboBox(pref_inner)
        self.language_combo.addItem("", userData="auto")
        for code, display in SUPPORTED_LANGUAGES.items():
            self.language_combo.addItem(display, userData=code)

        self.lbl_auto_install = BodyLabel("", pref_inner)
        self.lbl_debug_mode = BodyLabel("", pref_inner)
        self.lbl_appearance = BodyLabel("", pref_inner)
        self.lbl_language = BodyLabel("", pref_inner)

        pref_form.addRow(self.lbl_auto_install, auto_install_row)
        pref_form.addRow(self.lbl_debug_mode, keep_temp_row)
        pref_form.addRow(self.lbl_appearance, self.theme_combo)
        pref_form.addRow(self.lbl_language, self.language_combo)

        self.pref_card.viewLayout.addWidget(pref_inner)
        layout.addWidget(self.pref_card)

        btn_row = QHBoxLayout()
        self.save_btn = PrimaryPushButton(FluentIcon.SAVE, "", self.view)
        self.save_btn.setCursor(Qt.CursorShape.PointingHandCursor)
        btn_row.addWidget(self.save_btn)
        btn_row.addStretch(1)
        layout.addLayout(btn_row)

        self.about_card = HeaderCardWidget(self.view)
        add_card_header_icon(self.about_card, FluentIcon.INFO)
        about_inner = QWidget(self.about_card)
        about_form = QFormLayout(about_inner)
        about_form.setSpacing(8)

        self.lbl_about_app = BodyLabel("", about_inner)
        self.lbl_about_ver = BodyLabel("", about_inner)
        self.lbl_about_dev = BodyLabel("", about_inner)
        self.lbl_about_lic = BodyLabel("", about_inner)
        self.lbl_about_pipe = BodyLabel("", about_inner)
        self.lbl_about_cred = BodyLabel("", about_inner)

        ver_row = QWidget(about_inner)
        ver_lay = QHBoxLayout(ver_row)
        ver_lay.setContentsMargins(0, 0, 0, 0)
        ver_badge = InfoBadge(APP_META.version, ver_row, level=InfoLevel.SUCCESS)
        ver_lay.addWidget(ver_badge)
        ver_lay.addStretch(1)

        about_form.addRow(self.lbl_about_app, StrongBodyLabel(APP_META.name, about_inner))
        about_form.addRow(self.lbl_about_ver, ver_row)
        about_form.addRow(self.lbl_about_dev, StrongBodyLabel(APP_META.developer, about_inner))
        about_form.addRow(self.lbl_about_lic, BodyLabel(APP_META.license_name, about_inner))
        about_form.addRow(self.lbl_about_pipe, CaptionLabel(APP_META.toolchain_summary, about_inner))
        credits_lbl = CaptionLabel("\n".join(APP_META.credits), about_inner)
        credits_lbl.setWordWrap(True)
        about_form.addRow(self.lbl_about_cred, credits_lbl)

        self.about_card.viewLayout.addWidget(about_inner)
        layout.addWidget(self.about_card)
        layout.addStretch(1)

        self.save_btn.clicked.connect(self._on_save)
        self.theme_combo.currentIndexChanged.connect(self._on_theme_combo_changed)
        self.language_combo.currentIndexChanged.connect(self._on_language_combo_changed)

        self.retranslate_ui(self._i18n)
        self.load_from_state()

    def _path_row(
        self,
        form: QFormLayout,
        label_key: str,
        is_dir: bool,
        exe_filter: str = "",
    ) -> LineEdit:
        row_widget = QWidget(self.view)
        row = QHBoxLayout(row_widget)
        row.setContentsMargins(0, 0, 0, 0)
        edit = LineEdit(row_widget)
        btn = PushButton("", row_widget)
        btn.setCursor(Qt.CursorShape.PointingHandCursor)
        self._browse_buttons.append(btn)
        row.addWidget(edit, 1)
        row.addWidget(btn)

        lbl = BodyLabel("", self.view)
        self._form_labels[label_key] = lbl
        form.addRow(lbl, row_widget)

        def browse() -> None:
            field_title = lbl.text().rstrip(":")
            if is_dir:
                chosen = QFileDialog.getExistingDirectory(
                    self,
                    self._i18n.tr("dlg_select_prefix", label=field_title),
                )
            else:
                chosen, _ = QFileDialog.getOpenFileName(
                    self,
                    self._i18n.tr("dlg_select_prefix", label=field_title),
                    "",
                    self._i18n.tr("dlg_exe_filter", exe=exe_filter),
                )
            if chosen:
                edit.setText(chosen)

        btn.clicked.connect(browse)
        return edit

    def retranslate_ui(self, i18n: LocalizationManager) -> None:
        self._i18n = i18n
        self.page_title.setText(i18n.tr("settings_title"))
        self.paths_card.setTitle(i18n.tr("paths_card_title"))
        for key, lbl in self._form_labels.items():
            lbl.setText(i18n.tr(key))
        for btn in self._browse_buttons:
            btn.setText(i18n.tr("btn_browse"))

        self.pref_card.setTitle(i18n.tr("pref_card_title"))
        update_switch_help(
            self.auto_install_switch,
            self.help_auto_install,
            i18n.tr("switch_auto_install"),
            i18n.tr("help_install"),
        )
        update_switch_help(
            self.keep_temp_switch,
            self.help_keep_temp,
            i18n.tr("switch_keep_temp"),
            i18n.tr("help_keep_temp"),
        )
        self.lbl_auto_install.setText(i18n.tr("lbl_auto_install"))
        self.lbl_debug_mode.setText(i18n.tr("lbl_debug_mode"))
        self.lbl_appearance.setText(i18n.tr("lbl_appearance"))
        self.lbl_language.setText(i18n.tr("lbl_language"))

        detected_theme = L4d2ThemeManager.detect_system_theme()
        resolved_theme_label = i18n.tr("theme_dark" if detected_theme == "Dark" else "theme_light")
        self.theme_combo.blockSignals(True)
        self.theme_combo.setItemText(0, i18n.tr("theme_system", resolved=resolved_theme_label))
        self.theme_combo.setItemText(1, i18n.tr("theme_dark"))
        self.theme_combo.setItemText(2, i18n.tr("theme_light"))
        self.theme_combo.blockSignals(False)

        detected_lang = LocalizationManager.detect_system_language()
        detected_lang_name = SUPPORTED_LANGUAGES.get(detected_lang, detected_lang)
        self.language_combo.blockSignals(True)
        self.language_combo.setItemText(0, i18n.tr("lang_auto", resolved=detected_lang_name))
        self.language_combo.blockSignals(False)

        self.save_btn.setText(i18n.tr("btn_save"))

        self.about_card.setTitle(i18n.tr("about_card_title"))
        self.lbl_about_app.setText(i18n.tr("about_app_label"))
        self.lbl_about_ver.setText(i18n.tr("about_version_label"))
        self.lbl_about_dev.setText(i18n.tr("about_developer_label"))
        self.lbl_about_lic.setText(i18n.tr("about_license_label"))
        self.lbl_about_pipe.setText(i18n.tr("about_pipeline_label"))
        self.lbl_about_cred.setText(i18n.tr("about_credits_label"))

        L4d2ThemeManager.apply_pointing_hand_cursors(self)

    def load_from_state(self) -> None:
        cfg: AppConfig = self._get_config()
        env: EnvironmentStatus = self._get_env()

        self.l4d2_edit.setText(cfg.l4d2_dir or (str(env.l4d2_dir) if env.l4d2_dir else ""))
        self.studiomdl_edit.setText(cfg.studiomdl_executable or (str(env.studiomdl_path) if env.studiomdl_path else ""))
        self.vpk_edit.setText(cfg.vpk_executable or (str(env.vpk_exe_path) if env.vpk_exe_path else ""))
        self.output_edit.setText(cfg.output_dir)
        self.workshop_dir_edit.setText(cfg.workshop_download_dir)
        self.kit_edit.setText(cfg.kit_dir)

        self.auto_install_switch.setChecked(cfg.auto_install_to_addons)
        self.keep_temp_switch.setChecked(cfg.keep_temp_on_error)

        self.theme_combo.blockSignals(True)
        theme_idx = self.theme_combo.findData(cfg.theme)
        if theme_idx < 0:
            theme_idx = self.theme_combo.findData("Dark")
        self.theme_combo.setCurrentIndex(theme_idx if theme_idx >= 0 else 1)
        self.theme_combo.blockSignals(False)

        self.language_combo.blockSignals(True)
        lang_idx = self.language_combo.findData(cfg.language)
        self.language_combo.setCurrentIndex(lang_idx if lang_idx >= 0 else 0)
        self.language_combo.blockSignals(False)

    def _on_theme_combo_changed(self) -> None:
        selected = self.theme_combo.currentData()
        if selected:
            self.themeChanged.emit(str(selected))

    def _on_language_combo_changed(self) -> None:
        selected = self.language_combo.currentData()
        if selected:
            self.languageChanged.emit(str(selected))

    def _on_save(self) -> None:
        cfg: AppConfig = self._get_config()
        cfg.l4d2_dir = self.l4d2_edit.text().strip()
        cfg.studiomdl_executable = self.studiomdl_edit.text().strip()
        cfg.vpk_executable = self.vpk_edit.text().strip()
        cfg.output_dir = self.output_edit.text().strip() or "Swapped_Survivors"
        cfg.workshop_download_dir = self.workshop_dir_edit.text().strip() or "Workshop_Downloads"
        cfg.kit_dir = self.kit_edit.text().strip() or "HUNK'S_SURVIVOR_SWAP_KIT"
        cfg.auto_install_to_addons = self.auto_install_switch.isChecked()
        cfg.keep_temp_on_error = self.keep_temp_switch.isChecked()
        cfg.theme = str(self.theme_combo.currentData() or "Dark")
        cfg.language = str(self.language_combo.currentData() or "auto")

        self.config_mgr.save(cfg)
        self.themeChanged.emit(cfg.theme)
        self.languageChanged.emit(cfg.language)
        self.environmentUpdated.emit()
        self.load_from_state()
        InfoBar.success(
            self._i18n.tr("info_saved_title"),
            self._i18n.tr("info_saved_msg"),
            parent=self.window(),
            position=InfoBarPosition.TOP,
        )
