from __future__ import annotations

import os
import shutil
import threading
from pathlib import Path
from typing import Optional

from PySide6.QtCore import QObject, QThread, QUrl, Qt, Signal
from PySide6.QtGui import QDesktopServices, QPixmap
from PySide6.QtWidgets import (
    QFileDialog,
    QFormLayout,
    QHBoxLayout,
    QLabel,
    QSizePolicy,
    QVBoxLayout,
    QWidget,
)
from qfluentwidgets import (
    BodyLabel,
    CaptionLabel,
    ComboBox,
    FluentIcon,
    HeaderCardWidget,
    InfoBar,
    InfoBarPosition,
    LineEdit,
    PrimaryPushButton,
    PushButton,
    ScrollArea,
    Theme,
    isDarkTheme,
)

from core.addons_scanner import AddonsScanner
from core.archive_service import ArchiveSourceManager
from core.config_manager import ConfigManager
from core.history_manager import HistoryManager
from core.i18n import LocalizationManager
from core.models import (
    AppConfig,
    DetectedModInfo,
    EnvironmentStatus,
    ModMetadata,
    SurvivorId,
    SwapJobRequest,
    SwapProgress,
    SwapTargetResult,
)
from core.survivors import SurvivorRegistry
from core.swap_engine import SwapEngine
from core.vpk_service import VpkService
from ui.addon_ui_shared import (
    ArchiveVpkPickerDialog,
    ConversionOptionsGroupPanel,
    TemplatePreviewCard,
    TemplateTagsHintBar,
    install_vpks_with_conflict_check,
    launch_l4d2_steam,
    record_conversion_history,
    render_output_vpk_filenames,
    shutdown_worker_thread,
    update_template_preview_card,
)
from ui.addons_browser_dialog import AddonConflictDialog, AddonsBrowserDialog
from ui.conversion_confirm_dialog import ConversionConfirmDialog, ConversionConfirmEntry
from ui.error_dialog import ErrorDetailsDialog
from ui.theme import COLORS, L4d2ThemeManager
from ui.workshop_download_dialog import WorkshopUrlDialog
from ui.widgets import (
    ClickableImageLabel,
    DropZoneCard,
    FlowPanel,
    ImageZoomDialog,
    InlineWarningBanner,
    L4d2HeroBanner,
    ProgressLogCard,
    SurvivorGridPicker,
    add_card_header_icon,
    create_help_badge,
    create_icon_row,
    update_help_badge,
    wrap_tooltip_text,
)


class SwapWorker(QObject):
    """Background worker executing SwapEngine.run_job off the Qt UI thread."""

    progressUpdated = Signal(int, str, str)
    finished = Signal(list)
    failed = Signal(str)

    def __init__(
        self,
        env_status: EnvironmentStatus,
        kit_dir: Path,
        request: SwapJobRequest,
        keep_temp_on_error: bool = False,
        language_preference: str = "en-US",
    ) -> None:
        super().__init__()
        self.env_status = env_status
        self.kit_dir = kit_dir
        self.request = request
        self.keep_temp_on_error = keep_temp_on_error
        self.language_preference = language_preference
        self._cancel_event = threading.Event()

    def request_cancel(self) -> None:
        self._cancel_event.set()

    def run(self) -> None:
        try:
            engine = SwapEngine(
                self.env_status,
                self.kit_dir,
                i18n=LocalizationManager(self.language_preference),
            )

            def on_progress(prog: SwapProgress) -> None:
                self.progressUpdated.emit(prog.percent, prog.message, prog.log_line or "")

            results = engine.run_job(
                self.request,
                progress_cb=on_progress,
                keep_temp_on_error=self.keep_temp_on_error,
                cancel_cb=self._cancel_event.is_set,
            )
            self.finished.emit(results)
        except Exception as exc:
            self.failed.emit(str(exc))


class SwapPage(ScrollArea):
    """Primary guided workflow page styled in Left 4 Dead 2 colors."""

    conversionRecorded = Signal()
    addonsChanged = Signal()

    def __init__(
        self,
        config_mgr: ConfigManager,
        get_config_fn,
        get_env_fn,
        i18n: Optional[LocalizationManager] = None,
        history_mgr: Optional[HistoryManager] = None,
        parent: Optional[QWidget] = None,
    ) -> None:
        super().__init__(parent)
        self.setObjectName("swapPage")
        self.config_mgr = config_mgr
        self._get_config = get_config_fn
        self._get_env = get_env_fn
        self._i18n = i18n or LocalizationManager("en-US")
        self.history_mgr = history_mgr or HistoryManager(project_root=config_mgr.project_root)
        self._vpk_service = VpkService()

        self._detected_info: Optional[DetectedModInfo] = None
        self._last_results: list[SwapTargetResult] = []
        self._custom_addonimage_path: Optional[Path] = None
        self._original_cover_bytes: Optional[bytes] = None
        self._current_cover_full_pixmap: Optional[QPixmap] = None
        self._archive_temp_dirs: list[Path] = []
        self._current_job_meta: Optional[dict] = None
        self._suppress_origin_popup: bool = False
        self._worker_thread: Optional[QThread] = None
        self._worker: Optional[SwapWorker] = None

        self.view = QWidget(self)
        self.setWidget(self.view)
        self.setWidgetResizable(True)
        self.enableTransparentBackground()

        layout = QVBoxLayout(self.view)
        layout.setContentsMargins(28, 20, 28, 28)
        layout.setSpacing(14)

        self.hero_banner = L4d2HeroBanner(i18n=self._i18n, parent=self.view)
        layout.addWidget(self.hero_banner)

        self.drop_card = DropZoneCard(i18n=self._i18n, parent=self.view)
        layout.addWidget(self.drop_card)

        self.light_warning_banner = InlineWarningBanner(self.view)
        layout.addWidget(self.light_warning_banner)

        self.origin_card = HeaderCardWidget(self.view)
        add_card_header_icon(self.origin_card, FluentIcon.PIN)
        origin_inner = QWidget(self.origin_card)
        origin_vbox = QVBoxLayout(origin_inner)
        origin_vbox.setContentsMargins(0, 0, 0, 0)
        origin_vbox.setSpacing(8)
        origin_row = QHBoxLayout()
        origin_row.setContentsMargins(0, 0, 0, 0)
        self.origin_label = BodyLabel("", origin_inner)
        origin_row.addWidget(self.origin_label)
        self.origin_combo = ComboBox(origin_inner)
        self.origin_combo.addItem("", userData=None)
        for spec in SurvivorRegistry.all():
            self.origin_combo.addItem(f"{spec.display_name} ({spec.generation})", userData=spec.id)
        origin_row.addWidget(self.origin_combo, 1)
        origin_vbox.addLayout(origin_row)
        self.origin_warning_banner = InlineWarningBanner(origin_inner)
        origin_vbox.addWidget(self.origin_warning_banner)
        self.origin_card.viewLayout.addWidget(origin_inner)
        layout.addWidget(self.origin_card)

        self.dest_picker = SurvivorGridPicker(i18n=self._i18n, parent=self.view)
        layout.addWidget(self.dest_picker)

        self.meta_card = HeaderCardWidget(self.view)
        add_card_header_icon(self.meta_card, FluentIcon.EDIT)
        meta_inner = QWidget(self.meta_card)
        form = QFormLayout(meta_inner)
        form.setSpacing(10)
        form.setFieldGrowthPolicy(QFormLayout.FieldGrowthPolicy.ExpandingFieldsGrow)

        self.output_name_edit = LineEdit(meta_inner)
        self.addon_title_edit = LineEdit(meta_inner)
        self.addon_author_edit = LineEdit(meta_inner)
        self.addon_version_edit = LineEdit(meta_inner)
        self.addon_version_edit.setText("1.0")
        self.addon_desc_edit = LineEdit(meta_inner)

        self.lbl_output_name = BodyLabel("", meta_inner)
        self.lbl_addon_title = BodyLabel("", meta_inner)
        self.lbl_author = BodyLabel("", meta_inner)
        self.lbl_version = BodyLabel("", meta_inner)
        self.lbl_description = BodyLabel("", meta_inner)
        self.lbl_addon_image = BodyLabel("", meta_inner)
        self.lbl_options = BodyLabel("", meta_inner)

        cover_row_widget = QWidget(meta_inner)
        cover_row = QHBoxLayout(cover_row_widget)
        cover_row.setContentsMargins(0, 0, 0, 0)
        cover_row.setSpacing(10)
        self.cover_thumb_label = ClickableImageLabel(cover_row_widget)
        self.cover_thumb_label.setObjectName("coverThumbLabel")
        self.cover_thumb_label.setFixedSize(72, 46)
        self.cover_thumb_label.setAlignment(Qt.AlignmentFlag.AlignCenter)

        self.cover_zoom_badge = QLabel(self.cover_thumb_label)
        self.cover_zoom_badge.setFixedSize(18, 18)
        self.cover_zoom_badge.move(72 - 20, 46 - 20)
        self.cover_zoom_badge.setAlignment(Qt.AlignmentFlag.AlignCenter)
        self.cover_zoom_badge.setAttribute(Qt.WidgetAttribute.WA_TransparentForMouseEvents, True)
        self.cover_zoom_badge.setPixmap(FluentIcon.ZOOM_IN.icon(Theme.DARK).pixmap(11, 11))
        self.cover_zoom_badge.setStyleSheet(
            f"QLabel {{ background-color: rgba(15, 18, 24, 200); "
            f"border: 1px solid {COLORS.amber}; border-radius: 4px; padding: 0px; }}"
        )
        self.cover_zoom_badge.setVisible(False)

        cover_right = QVBoxLayout()
        cover_right.setContentsMargins(0, 0, 0, 0)
        cover_right.setSpacing(4)
        self.cover_actions_panel = FlowPanel(h_space=8, v_space=6, parent=cover_row_widget)
        self.choose_cover_btn = PushButton(FluentIcon.PHOTO, "", self.cover_actions_panel)
        self.reset_cover_btn = PushButton(FluentIcon.ROTATE, "", self.cover_actions_panel)
        self.reset_cover_btn.setEnabled(False)
        self.cover_actions_panel.flow.addWidget(self.choose_cover_btn)
        self.cover_actions_panel.flow.addWidget(self.reset_cover_btn)
        self.cover_actions_panel.sync_height(fallback_width=420)
        self.cover_status_label = CaptionLabel("", cover_row_widget)
        self.cover_status_label.setWordWrap(True)
        cover_right.addWidget(self.cover_actions_panel)
        cover_right.addWidget(self.cover_status_label)
        cover_row.addWidget(self.cover_thumb_label, 0, Qt.AlignmentFlag.AlignTop)
        cover_row.addLayout(cover_right, 1)

        self.tags_hint_bar = TemplateTagsHintBar(i18n=self._i18n, parent=meta_inner)
        self.tags_hint_bar.bind_target_edits(self.output_name_edit, self.addon_title_edit)
        self.tags_hint_label = self.tags_hint_bar.hint_label
        self.tags_preview_card = TemplatePreviewCard(i18n=self._i18n, parent=meta_inner)
        self.tags_preview_label = CaptionLabel("", self.tags_preview_card)
        self.tags_preview_label.setVisible(False)

        form.addRow(self.lbl_output_name, self.output_name_edit)
        form.addRow(self.lbl_addon_title, self.addon_title_edit)
        form.addRow("", self.tags_hint_bar)
        form.addRow("", self.tags_preview_card)
        form.addRow(self.lbl_author, self.addon_author_edit)
        form.addRow(self.lbl_version, self.addon_version_edit)
        form.addRow(self.lbl_description, self.addon_desc_edit)
        form.addRow(self.lbl_addon_image, cover_row_widget)

        self.options_group = ConversionOptionsGroupPanel(
            install_default=bool(self._get_config().auto_install_to_addons),
            sanitize_default=bool(self._get_config().sanitize_origin_title),
            fallback_width=620,
            i18n=self._i18n,
            parent=meta_inner,
        )
        self.toggles_panel = self.options_group
        self.switch_arms = self.options_group.switch_arms
        self.help_arms = self.options_group.help_arms
        self.switch_vgui = self.options_group.switch_vgui
        self.help_vgui = self.options_group.help_vgui
        self.weapons_option_row = self.options_group.weapons_row
        self.switch_weapons = self.options_group.switch_weapons
        self.help_weapons = self.options_group.help_weapons
        self.switch_install = self.options_group.switch_install
        self.help_install = self.options_group.help_install
        self.switch_sanitize_origin = self.options_group.switch_sanitize
        self.help_sanitize_origin = self.options_group.help_sanitize
        form.addRow(self.lbl_options, self.options_group)

        self.meta_card.viewLayout.addWidget(meta_inner)
        layout.addWidget(self.meta_card)

        self.action_panel = FlowPanel(h_space=8, v_space=8, parent=self.view)
        self.convert_btn = PrimaryPushButton(FluentIcon.PLAY, "", self.action_panel)
        self.convert_btn.setMinimumHeight(42)
        self.cancel_btn = PushButton(FluentIcon.CLOSE, "", self.action_panel)
        self.cancel_btn.setMinimumHeight(42)
        self.cancel_btn.setEnabled(False)
        self.cancel_btn.setVisible(False)
        self.install_btn = PushButton(FluentIcon.DOWNLOAD, "", self.action_panel)
        self.install_btn.setEnabled(False)
        self.open_out_btn = PushButton(FluentIcon.FOLDER, "", self.action_panel)
        self.launch_l4d2_btn = PushButton(FluentIcon.PLAY_SOLID, "", self.action_panel)
        self.clear_swap_btn = PushButton(FluentIcon.ERASE_TOOL, "", self.action_panel)
        for act_btn in (
            self.convert_btn,
            self.cancel_btn,
            self.install_btn,
            self.open_out_btn,
            self.launch_l4d2_btn,
            self.clear_swap_btn,
        ):
            self.action_panel.flow.addWidget(act_btn)
        self.action_panel.sync_height(fallback_width=760)
        layout.addWidget(self.action_panel)

        self.progress_card = ProgressLogCard(i18n=self._i18n, parent=self.view)
        layout.addWidget(self.progress_card)
        layout.addStretch(1)

        self.drop_card.sourceSelected.connect(self._on_source_selected)
        self.drop_card.workshopRequested.connect(self._on_browse_workshop_addons)
        self.drop_card.workshopUrlRequested.connect(self._on_download_workshop_url)
        self.origin_combo.currentIndexChanged.connect(self._on_origin_changed)
        self.dest_picker.selectionChanged.connect(self._on_dest_selection_changed)
        self.output_name_edit.textChanged.connect(self._refresh_template_preview)
        self.addon_title_edit.textChanged.connect(self._refresh_template_preview)
        self.switch_sanitize_origin.checkedChanged.connect(self._refresh_template_preview)
        self.cover_thumb_label.clicked.connect(self._on_zoom_cover)
        self.choose_cover_btn.clicked.connect(self._on_choose_cover_image)
        self.reset_cover_btn.clicked.connect(self._on_reset_cover_image)
        self.convert_btn.clicked.connect(self._on_start_conversion)
        self.cancel_btn.clicked.connect(self._on_cancel_conversion)
        self.install_btn.clicked.connect(self._on_install_last_results)
        self.open_out_btn.clicked.connect(self._on_open_output_dir)
        self.launch_l4d2_btn.clicked.connect(launch_l4d2_steam)
        self.clear_swap_btn.clicked.connect(self.reset_form)

        self.retranslate_ui(self._i18n)
        self._on_origin_changed()

    def retranslate_ui(self, i18n: LocalizationManager) -> None:
        self._i18n = i18n
        self.hero_banner.retranslate_ui(i18n)
        self.drop_card.retranslate_ui(i18n)
        self.origin_card.setTitle(i18n.tr("origin_card_title"))
        self.origin_label.setText(i18n.tr("origin_label"))
        self.origin_combo.setItemText(0, i18n.tr("origin_not_selected"))
        self.dest_picker.retranslate_ui(i18n)

        self.meta_card.setTitle(i18n.tr("meta_card_title"))
        self.lbl_output_name.setText(i18n.tr("meta_output_name"))
        self.output_name_edit.setPlaceholderText(i18n.tr("meta_output_placeholder"))
        self.lbl_addon_title.setText(i18n.tr("meta_addon_title"))
        self.addon_title_edit.setPlaceholderText(i18n.tr("meta_title_placeholder"))
        self.tags_hint_bar.retranslate_ui(i18n)
        self._refresh_template_preview()
        self.lbl_author.setText(i18n.tr("meta_author"))
        self.lbl_version.setText(i18n.tr("meta_version"))
        self.lbl_description.setText(i18n.tr("meta_description"))
        self.lbl_addon_image.setText(i18n.tr("meta_addon_image"))
        self.choose_cover_btn.setText(i18n.tr("cover_btn_browse"))
        self.reset_cover_btn.setText(i18n.tr("cover_btn_reset"))
        self.cover_actions_panel.sync_height(fallback_width=420)
        self.lbl_options.setText(i18n.tr("meta_options"))
        self._refresh_cover_preview()

        self.options_group.retranslate_ui(i18n)
        self._update_origin_mismatch_warning(show_popup=False)
        self._update_light_warning_banner()

        self.convert_btn.setText(i18n.tr("btn_start"))
        self.cancel_btn.setText(i18n.tr("btn_cancel"))
        self._update_install_btn_text()
        self.open_out_btn.setText(i18n.tr("btn_open_output"))
        self.launch_l4d2_btn.setText(i18n.tr("btn_launch_l4d2"))
        self.clear_swap_btn.setText(i18n.tr("btn_reset_swap"))
        self.clear_swap_btn.setToolTip(wrap_tooltip_text(i18n.tr("btn_reset_swap_tip")))
        self.progress_card.retranslate_ui(i18n)
        L4d2ThemeManager.apply_pointing_hand_cursors(self)

    def _cleanup_archive_temps(self) -> None:
        while self._archive_temp_dirs:
            temp_dir = self._archive_temp_dirs.pop(0)
            shutil.rmtree(temp_dir, ignore_errors=True)

    def _on_source_selected(self, path: Path) -> None:
        prep = ArchiveSourceManager.prepare_source(path)
        if not prep.valid:
            InfoBar.warning(
                self._i18n.tr("err_drop_invalid_title"),
                self._i18n.tr(prep.error_key, **prep.error_kwargs),
                parent=self.window(),
                position=InfoBarPosition.TOP,
                duration=6000,
            )
            return

        resolved_path = prep.resolved_path
        if resolved_path is None and prep.candidate_vpks:
            picker = ArchiveVpkPickerDialog(
                bundle_name=path.name,
                vpk_paths=prep.candidate_vpks,
                i18n=self._i18n,
                parent=self.window(),
            )
            if not picker.exec():
                if prep.temp_dir is not None:
                    shutil.rmtree(prep.temp_dir, ignore_errors=True)
                return
            resolved_path = picker.selected_vpk()

        if resolved_path is None:
            if prep.temp_dir is not None:
                shutil.rmtree(prep.temp_dir, ignore_errors=True)
            return

        try:
            info = self._vpk_service.inspect_source(resolved_path)
        except Exception as exc:
            if prep.temp_dir is not None:
                shutil.rmtree(prep.temp_dir, ignore_errors=True)
            InfoBar.error(
                self._i18n.tr("info_err_read_title"),
                str(exc),
                parent=self.window(),
                position=InfoBarPosition.TOP,
            )
            return

        self._cleanup_archive_temps()
        if prep.temp_dir is not None:
            self._archive_temp_dirs.append(prep.temp_dir)

        display_label = None
        fallback_stem = resolved_path.stem
        if prep.temp_dir is not None:
            fallback_stem = path.stem if resolved_path == prep.temp_dir else resolved_path.stem
            display_label = f"{path.name} -> {resolved_path.name}" if resolved_path.is_file() else path.name

        self._detected_info = info
        self.drop_card.set_detected_info(info, display_path=display_label)
        self._update_light_warning_banner()

        self._suppress_origin_popup = True
        try:
            if info.detected_origin is not None:
                for idx in range(self.origin_combo.count()):
                    if self.origin_combo.itemData(idx) == info.detected_origin:
                        self.origin_combo.setCurrentIndex(idx)
                        break
            else:
                self.origin_combo.setCurrentIndex(0)
        finally:
            self._suppress_origin_popup = False
        self._update_origin_mismatch_warning(show_popup=False)

        self.output_name_edit.setText(fallback_stem)
        self.addon_title_edit.setText(info.metadata.title or fallback_stem)
        self.addon_author_edit.setText(info.metadata.author)
        self.addon_version_edit.setText(info.metadata.version or "1.0")
        self.addon_desc_edit.setText(info.metadata.description)
        self.switch_arms.setChecked(info.has_arms)
        self.switch_vgui.setChecked(info.has_vgui)
        self.weapons_option_row.setVisible(False)
        self.toggles_panel.sync_height(max(620, self.toggles_panel.width()))
        self.switch_weapons.setChecked(info.has_weapons)
        self._custom_addonimage_path = None
        self._original_cover_bytes = AddonsScanner.read_source_preview_image(resolved_path)
        self._refresh_cover_preview()
        self._last_results = []
        self.install_btn.setEnabled(False)
        self._update_install_btn_text()
        self._refresh_template_preview()
        L4d2ThemeManager.apply_pointing_hand_cursors(self)

    def _on_choose_cover_image(self) -> None:
        img_str, _ = QFileDialog.getOpenFileName(
            self,
            self._i18n.tr("dlg_select_cover_title"),
            "",
            self._i18n.tr("dlg_select_cover_filter"),
        )
        if not img_str:
            return
        self._custom_addonimage_path = Path(img_str)
        self._refresh_cover_preview()
        L4d2ThemeManager.apply_pointing_hand_cursors(self)

    def _on_reset_cover_image(self) -> None:
        self._custom_addonimage_path = None
        self._refresh_cover_preview()
        L4d2ThemeManager.apply_pointing_hand_cursors(self)

    def _refresh_cover_preview(self) -> None:
        is_dark = isDarkTheme()
        border = COLORS.dark_border if is_dark else COLORS.light_border
        L4d2ThemeManager.install_surface_motion(
            self.cover_thumb_label,
            "QLabel#coverThumbLabel { background-color: {bg}; border: 1px solid {border}; border-radius: 4px; }",
            custom_colors=L4d2ThemeManager.image_surface_palette(is_dark),
            border_colors=L4d2ThemeManager.image_border_colors(is_dark),
        )

        pixmap = QPixmap()
        if self._custom_addonimage_path is not None and self._custom_addonimage_path.is_file():
            pixmap.load(str(self._custom_addonimage_path))
            self.cover_status_label.setText(
                self._i18n.tr("cover_status_custom", name=self._custom_addonimage_path.name)
            )
            self.reset_cover_btn.setEnabled(True)
        elif self._original_cover_bytes and pixmap.loadFromData(self._original_cover_bytes):
            self.cover_status_label.setText(self._i18n.tr("cover_status_original"))
            self.reset_cover_btn.setEnabled(False)
        else:
            self.cover_status_label.setText(self._i18n.tr("cover_status_none"))
            self.reset_cover_btn.setEnabled(False)

        if not pixmap.isNull():
            self._current_cover_full_pixmap = pixmap
            self.cover_thumb_label.setPixmap(
                pixmap.scaled(
                    self.cover_thumb_label.size(),
                    Qt.AspectRatioMode.KeepAspectRatio,
                    Qt.TransformationMode.SmoothTransformation,
                )
            )
            self.cover_thumb_label.setCursor(Qt.CursorShape.PointingHandCursor)
            self.cover_thumb_label.setToolTip(self._i18n.tr("addons_dlg_zoom_tip"))
            self.cover_zoom_badge.setVisible(True)
        else:
            self._current_cover_full_pixmap = None
            self.cover_thumb_label.setPixmap(QPixmap())
            self.cover_thumb_label.setCursor(Qt.CursorShape.ArrowCursor)
            self.cover_thumb_label.setToolTip("")
            self.cover_zoom_badge.setVisible(False)

    def _on_zoom_cover(self) -> None:
        if self._current_cover_full_pixmap is None or self._current_cover_full_pixmap.isNull():
            return
        title = self.addon_title_edit.text().strip()
        if not title and self._detected_info is not None:
            title = self._detected_info.metadata.title or self._detected_info.source_path.stem
        if not title:
            title = self._i18n.tr("meta_addon_image")
        dlg = ImageZoomDialog(
            title=title,
            pixmap=self._current_cover_full_pixmap,
            i18n=self._i18n,
            parent=self.window(),
        )
        dlg.exec()

    def _on_origin_changed(self) -> None:
        origin_id = self.origin_combo.currentData()
        self.dest_picker.set_origin_survivor(
            origin_id if isinstance(origin_id, SurvivorId) else None
        )
        self._update_origin_mismatch_warning(show_popup=not self._suppress_origin_popup)
        self._refresh_template_preview()

    def _update_light_warning_banner(self) -> None:
        if self._detected_info is not None and self._detected_info.has_light_models:
            self.light_warning_banner.set_warning(self._i18n.tr("light_warn_banner"))
        else:
            self.light_warning_banner.set_warning("")

    def _update_origin_mismatch_warning(self, show_popup: bool = False) -> None:
        origin_id = self.origin_combo.currentData()
        info = self._detected_info
        if (
            info is not None
            and info.detected_origin is not None
            and isinstance(origin_id, SurvivorId)
            and origin_id != info.detected_origin
        ):
            det_name = SurvivorRegistry.get(info.detected_origin).display_name
            sel_name = SurvivorRegistry.get(origin_id).display_name
            msg = self._i18n.tr("origin_mismatch_warn", detected=det_name, selected=sel_name)
            self.origin_warning_banner.set_warning(msg)
            if show_popup:
                InfoBar.warning(
                    self._i18n.tr("origin_label"),
                    msg,
                    parent=self.window(),
                    position=InfoBarPosition.TOP,
                    duration=5000,
                )
        else:
            self.origin_warning_banner.set_warning("")

    def _refresh_template_preview(self) -> None:
        origin_data = self.origin_combo.currentData()
        origin_id = origin_data if isinstance(origin_data, SurvivorId) else None
        dest_ids = self.dest_picker.selected_survivors()
        info = self._detected_info
        fallback_stem = info.source_path.stem if info is not None else "my_mod"
        typed_title = self.addon_title_edit.text().strip()
        if info is not None:
            orig_title = info.metadata.original_title or info.metadata.title or fallback_stem
        else:
            orig_title = typed_title if typed_title and "{" not in typed_title else "My Mod"
        update_template_preview_card(
            self.tags_preview_card,
            self.tags_preview_label,
            file_template=self.output_name_edit.text(),
            title_template=typed_title,
            orig_title=orig_title,
            origin_id=origin_id,
            dest_ids=dest_ids,
            i18n=self._i18n,
            fallback_stem=fallback_stem,
            sanitize_origin=self.switch_sanitize_origin.isChecked(),
        )

    def _on_start_conversion(self) -> None:
        if self._worker_thread is not None and self._worker_thread.isRunning():
            return

        if self._detected_info is None:
            InfoBar.warning(
                self._i18n.tr("info_no_mod_title"),
                self._i18n.tr("info_no_mod_msg"),
                parent=self.window(),
                position=InfoBarPosition.TOP,
            )
            return

        env: EnvironmentStatus = self._get_env()
        if not env.is_ready_for_swap:
            InfoBar.error(
                self._i18n.tr("info_setup_incomplete_title"),
                self._i18n.tr("info_setup_incomplete_msg"),
                parent=self.window(),
                position=InfoBarPosition.TOP,
            )
            return

        origin_id = self.origin_combo.currentData()
        if not isinstance(origin_id, SurvivorId):
            InfoBar.warning(
                self._i18n.tr("info_no_origin_title"),
                self._i18n.tr("info_no_origin_msg"),
                parent=self.window(),
                position=InfoBarPosition.TOP,
            )
            return
        destinations = self.dest_picker.selected_survivors()
        if not destinations:
            InfoBar.warning(
                self._i18n.tr("info_no_dest_title"),
                self._i18n.tr("info_no_dest_msg"),
                parent=self.window(),
                position=InfoBarPosition.TOP,
            )
            return

        cfg: AppConfig = self._get_config()
        output_dir = self.config_mgr.resolve_path(cfg.output_dir)
        kit_dir = self.config_mgr.resolve_path(cfg.kit_dir)

        orig_title = (
            self._detected_info.metadata.original_title
            or self._detected_info.metadata.title
            or self._detected_info.source_path.stem
        )
        meta = ModMetadata(
            title=self.addon_title_edit.text().strip() or self._detected_info.source_path.stem,
            version=self.addon_version_edit.text().strip() or "1.0",
            description=self.addon_desc_edit.text().strip(),
            author=self.addon_author_edit.text().strip(),
            author_steam_id=self._detected_info.metadata.author_steam_id,
            url=self._detected_info.metadata.url,
            extra_fields=dict(self._detected_info.metadata.extra_fields),
            original_title=orig_title,
        )

        output_template = self.output_name_edit.text().strip() or self._detected_info.source_path.stem
        cover_bytes = self._original_cover_bytes
        if self._custom_addonimage_path is not None and self._custom_addonimage_path.is_file():
            try:
                cover_bytes = self._custom_addonimage_path.read_bytes()
            except OSError:
                pass
        confirm_entry = ConversionConfirmEntry(
            title=meta.title,
            source_filename=self._detected_info.source_path.name,
            author=meta.author,
            version=meta.version,
            origin=origin_id,
            destinations=destinations,
            output_files=render_output_vpk_filenames(
                file_template=output_template,
                title_template=meta.title,
                orig_title=orig_title,
                origin_id=origin_id,
                dest_ids=destinations,
                fallback_stem=self._detected_info.source_path.stem,
                sanitize_origin=self.switch_sanitize_origin.isChecked(),
            ),
            output_dir=str(output_dir),
            cover_bytes=cover_bytes,
            include_arms=self.switch_arms.isChecked(),
            include_vgui=self.switch_vgui.isChecked(),
            include_weapons=(
                self.switch_weapons.isChecked() if self._detected_info.has_weapons else None
            ),
            sanitize_origin=self.switch_sanitize_origin.isChecked(),
            install_to_addons=self.switch_install.isChecked(),
        )
        confirm_dlg = ConversionConfirmDialog(
            [confirm_entry],
            i18n=self._i18n,
            parent=self.window(),
        )
        if not confirm_dlg.exec():
            return

        request = SwapJobRequest(
            source_path=self._detected_info.source_path,
            origin=origin_id,
            destinations=destinations,
            output_name_template=output_template,
            metadata=meta,
            output_dir=output_dir,
            install_to_addons=self.switch_install.isChecked(),
            addons_dir=env.l4d2_addons_dir,
            include_arms=self.switch_arms.isChecked(),
            include_vgui=self.switch_vgui.isChecked(),
            include_weapons=self.switch_weapons.isChecked(),
            sanitize_origin_title=self.switch_sanitize_origin.isChecked(),
            custom_addonimage_path=self._custom_addonimage_path,
        )

        self._current_job_meta = {
            "mod_title": meta.title,
            "author": meta.author,
            "source_path": str(self._detected_info.source_path),
            "origin": origin_id.value,
            "destinations": [d.value for d in destinations],
            "output_dir": str(output_dir),
            "installed_to_addons": self.switch_install.isChecked(),
            "custom_cover_used": self._custom_addonimage_path is not None,
        }

        self._set_busy(True)
        self.progress_card.reset()

        self._worker_thread = QThread(self)
        self._worker = SwapWorker(
            env_status=env,
            kit_dir=kit_dir,
            request=request,
            keep_temp_on_error=cfg.keep_temp_on_error,
            language_preference=self._i18n.preference,
        )
        self._worker.moveToThread(self._worker_thread)
        self._worker_thread.started.connect(self._worker.run)
        self._worker.progressUpdated.connect(self._on_worker_progress)
        self._worker.finished.connect(self._on_worker_finished)
        self._worker.failed.connect(self._on_worker_failed)
        self._worker.finished.connect(self._worker_thread.quit)
        self._worker.failed.connect(self._worker_thread.quit)
        self._worker_thread.finished.connect(self._cleanup_thread)
        self._worker_thread.start()

    def _on_worker_progress(self, percent: int, message: str, log_line: str) -> None:
        self.progress_card.update_progress(percent, message)
        if log_line and log_line != message:
            self.progress_card.append_log(log_line)

    def _on_worker_finished(self, results: list[SwapTargetResult]) -> None:
        self._set_busy(False)
        self._last_results = results
        succeeded = [r for r in results if r.success]
        cancelled = [r for r in results if r.cancelled]
        failed = [r for r in results if not r.success and not r.cancelled]
        conflict_prefix = self._i18n.tr(
            "prog_warn_addon_conflict",
            target="__T__",
            title="__M__",
            location="__L__",
        ).split("__T__", 1)[0]
        conflict_count = 0

        for r in results:
            if r.success:
                self.progress_card.append_log(
                    self._i18n.tr("log_target_ok", target=r.destination.value, path=r.vpk_path)
                )
                for warn in r.warnings:
                    self.progress_card.append_log(self._i18n.tr("log_warn_prefix", warn=warn))
                    if conflict_prefix and warn.startswith(conflict_prefix):
                        conflict_count += 1
            elif r.cancelled:
                self.progress_card.append_log(self._i18n.tr("prog_cancelled"))
            else:
                self.progress_card.append_log(
                    self._i18n.tr("log_target_fail", target=r.destination.value, error=r.error_message)
                )
                for log_line in r.logs[-15:]:
                    self.progress_card.append_log(f"    {log_line}")

        self.install_btn.setEnabled(bool(succeeded) and self._get_env().l4d2_addons_dir is not None)
        self._update_install_btn_text()
        L4d2ThemeManager.apply_pointing_hand_cursors(self)
        self._record_history(results=results)
        if any(r.installed_path is not None for r in succeeded):
            self.addonsChanged.emit()

        if cancelled:
            InfoBar.warning(
                self._i18n.tr("info_cancelled_title"),
                self._i18n.tr_plural("info_cancelled_msg", len(succeeded)),
                parent=self.window(),
                position=InfoBarPosition.TOP,
                duration=5000,
            )
        elif succeeded and not failed:
            if conflict_count > 0:
                addons_path = self._get_env().l4d2_addons_dir or ""
                installed_part = self._i18n.tr_plural(
                    "info_installed_msg",
                    len(succeeded),
                    path=addons_path,
                )
                conflict_part = self._i18n.tr_plural("info_conflicts_suffix", conflict_count)
                InfoBar.warning(
                    self._i18n.tr("info_done_title"),
                    f"{installed_part}. {conflict_part}",
                    parent=self.window(),
                    position=InfoBarPosition.TOP,
                    duration=7000,
                )
            else:
                InfoBar.success(
                    self._i18n.tr("info_done_title"),
                    self._i18n.tr_plural("info_done_msg", len(succeeded)),
                    parent=self.window(),
                    position=InfoBarPosition.TOP,
                    duration=5000,
                )
        elif succeeded and failed:
            ok_part = self._i18n.tr_plural("info_partial_ok", len(succeeded))
            fail_part = self._i18n.tr_plural("info_partial_fail", len(failed))
            InfoBar.warning(
                self._i18n.tr("info_partial_title"),
                self._i18n.tr("info_partial_hint", ok_part=ok_part, fail_part=fail_part),
                parent=self.window(),
                position=InfoBarPosition.TOP,
                duration=6000,
            )
        else:
            if failed:
                first_err = failed[0].error_message or self._i18n.tr("info_fail_unknown")
                summary = first_err.splitlines()[0].strip()
                blocks = []
                for item in failed:
                    header = f"[{item.destination.value}] {item.error_message or ''}".strip()
                    tail = "\n".join(item.logs[-40:]) if item.logs else ""
                    blocks.append(f"{header}\n{tail}".strip())
                details = "\n\n".join(blocks)
            else:
                summary = self._i18n.tr("info_fail_unknown")
                details = summary
            self._show_error_dialog(self._i18n.tr("info_fail_title"), summary, details)

    def _on_worker_failed(self, err: str) -> None:
        self._set_busy(False)
        self.progress_card.append_log(f"[ERROR] {err}")
        self._record_history(results=[], fatal_error=err)
        summary = err.splitlines()[0].strip() if err.strip() else self._i18n.tr("info_fail_unknown")
        self._show_error_dialog(self._i18n.tr("info_fail_title"), summary, err)

    def _record_history(
        self,
        results: list[SwapTargetResult],
        fatal_error: str = "",
    ) -> None:
        job_meta = self._current_job_meta
        self._current_job_meta = None
        if job_meta is None and not results:
            return

        if job_meta is None:
            info = self._detected_info
            origin_val = (
                info.detected_origin.value
                if info is not None and info.detected_origin is not None
                else (self.origin_combo.currentData().value if isinstance(self.origin_combo.currentData(), SurvivorId) else "")
            )
            job_meta = {
                "mod_title": self.addon_title_edit.text().strip() or (info.metadata.title if info else "Swap"),
                "author": self.addon_author_edit.text().strip(),
                "source_path": str(info.source_path) if info else "",
                "origin": origin_val,
                "destinations": [r.destination.value for r in results],
                "output_dir": str(self.config_mgr.resolve_path(self._get_config().output_dir)),
                "installed_to_addons": self.switch_install.isChecked(),
                "custom_cover_used": self._custom_addonimage_path is not None,
            }

        record_conversion_history(
            history_mgr=self.history_mgr,
            mod_title=job_meta["mod_title"],
            author=job_meta["author"],
            source_path=job_meta["source_path"],
            origin=job_meta["origin"],
            destinations=list(job_meta["destinations"]),
            output_dir=job_meta["output_dir"],
            installed_to_addons=bool(job_meta["installed_to_addons"]),
            custom_cover_used=bool(job_meta["custom_cover_used"]),
            results=results,
            fatal_error=fatal_error,
        )
        self.conversionRecorded.emit()

    def _show_error_dialog(self, title: str, summary: str, details: str) -> None:
        dlg = ErrorDetailsDialog(
            title=title,
            summary=summary,
            details=details,
            i18n=self._i18n,
            parent=self.window(),
        )
        dlg.exec()

    def _cleanup_thread(self) -> None:
        if self._worker is not None:
            self._worker.deleteLater()
            self._worker = None
        if self._worker_thread is not None:
            self._worker_thread.deleteLater()
            self._worker_thread = None

    def _set_busy(self, busy: bool) -> None:
        self.convert_btn.setEnabled(not busy)
        self.cancel_btn.setVisible(busy)
        self.cancel_btn.setEnabled(busy)
        if not busy:
            self.cancel_btn.setText(self._i18n.tr("btn_cancel"))
        self.drop_card.setEnabled(not busy)
        self.dest_picker.setEnabled(not busy)
        self.clear_swap_btn.setEnabled(not busy)
        L4d2ThemeManager.apply_pointing_hand_cursors(self)

    def reset_form(self) -> None:
        """Reset mod selection, origin, destinations, metadata, cover, options, and logs to initial state."""
        if self._worker_thread is not None and self._worker_thread.isRunning():
            return
        self._detected_info = None
        self._last_results = []
        self._custom_addonimage_path = None
        self._original_cover_bytes = None
        self._current_cover_full_pixmap = None
        self._current_job_meta = None
        self._cleanup_archive_temps()

        self.drop_card.clear()
        self.light_warning_banner.set_warning("")
        self.origin_warning_banner.set_warning("")

        self._suppress_origin_popup = True
        try:
            self.origin_combo.setCurrentIndex(0)
        finally:
            self._suppress_origin_popup = False

        self.dest_picker.clear_selection()

        self.output_name_edit.clear()
        self.addon_title_edit.clear()
        self.addon_author_edit.clear()
        self.addon_version_edit.setText("1.0")
        self.addon_desc_edit.clear()

        cfg = self._get_config()
        self.switch_arms.setChecked(True)
        self.switch_vgui.setChecked(True)
        self.weapons_option_row.setVisible(False)
        self.toggles_panel.sync_height(max(420, self.toggles_panel.width()))
        self.switch_weapons.setChecked(True)
        self.switch_install.setChecked(bool(cfg.auto_install_to_addons))
        self.switch_sanitize_origin.setChecked(bool(cfg.sanitize_origin_title))

        self.install_btn.setEnabled(False)
        self._update_install_btn_text()
        self._refresh_cover_preview()
        self._refresh_template_preview()
        self.progress_card.reset_idle()
        L4d2ThemeManager.apply_pointing_hand_cursors(self)

    def _on_cancel_conversion(self) -> None:
        if self._worker is not None:
            self._worker.request_cancel()
            self.cancel_btn.setEnabled(False)
            self.cancel_btn.setText(self._i18n.tr("btn_cancelling"))

    def _on_browse_workshop_addons(self) -> None:
        addons_dir = self._get_env().l4d2_addons_dir
        if addons_dir is None or not addons_dir.exists():
            InfoBar.warning(
                self._i18n.tr("info_addons_missing_title"),
                self._i18n.tr("info_addons_missing_msg"),
                parent=self.window(),
                position=InfoBarPosition.TOP,
            )
            return

        dlg = AddonsBrowserDialog(addons_dir, i18n=self._i18n, parent=self.window())
        if dlg.exec():
            entry = dlg.selected_entry()
            if entry is not None:
                self._on_source_selected(entry.vpk_path)

    def _on_download_workshop_url(self) -> None:
        env = self._get_env()
        cfg = self._get_config()
        dl_dir = self.config_mgr.resolve_path(cfg.workshop_download_dir or "Workshop_Downloads")
        dlg = WorkshopUrlDialog(
            download_dir=dl_dir,
            addons_dir=env.l4d2_addons_dir,
            allow_multiple=False,
            i18n=self._i18n,
            parent=self.window(),
        )
        if dlg.exec():
            paths = dlg.downloaded_paths()
            if paths:
                self._on_source_selected(paths[0])

    def shutdown_worker(self, timeout_ms: int = 5000) -> None:
        """Wait cleanly for any active swap worker thread and purge temp archive dirs."""
        shutdown_worker_thread(
            self._worker_thread,
            self._worker,
            cancel_fn=self._worker.request_cancel if self._worker is not None else None,
            ui_signals=(
                (self._worker.progressUpdated, self._worker.finished, self._worker.failed)
                if self._worker is not None
                else ()
            ),
            timeout_ms=timeout_ms,
        )
        self._worker = None
        self._worker_thread = None
        self._cleanup_archive_temps()

    def _on_install_last_results(self) -> None:
        addons_dir = self._get_env().l4d2_addons_dir
        if addons_dir is None:
            InfoBar.warning(
                self._i18n.tr("info_addons_missing_title"),
                self._i18n.tr("info_addons_missing_msg"),
                parent=self.window(),
                position=InfoBarPosition.TOP,
            )
            return

        ready_items = [
            (res.destination, res.vpk_path)
            for res in self._last_results
            if res.success and res.vpk_path and res.vpk_path.exists()
        ]
        if not ready_items:
            return

        if install_vpks_with_conflict_check(
            ready_items=ready_items,
            addons_dir=addons_dir,
            i18n=self._i18n,
            parent=self.window(),
            conflict_dialog_cls=AddonConflictDialog,
            info_bar_cls=InfoBar,
            info_position=InfoBarPosition.TOP,
        ):
            self.addonsChanged.emit()

    def _on_dest_selection_changed(self, _selected: list) -> None:
        self._update_install_btn_text()
        self._refresh_template_preview()

    def _update_install_btn_text(self) -> None:
        succeeded_count = sum(1 for r in self._last_results if r.success)
        if succeeded_count > 0:
            target_count = succeeded_count
        else:
            selected_count = len(self.dest_picker.selected_survivors())
            target_count = selected_count if selected_count > 0 else 2
        self.install_btn.setText(self._i18n.tr_plural("btn_install_results", target_count))

    def _on_open_output_dir(self) -> None:
        out_dir = self.config_mgr.resolve_path(self._get_config().output_dir)
        out_dir.mkdir(parents=True, exist_ok=True)
        try:
            os.startfile(str(out_dir))
        except OSError:
            QDesktopServices.openUrl(QUrl.fromLocalFile(str(out_dir)))
