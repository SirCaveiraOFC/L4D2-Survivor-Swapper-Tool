from __future__ import annotations

import os
import shutil
import threading
import uuid
from pathlib import Path
from typing import Callable, Optional

from PySide6.QtCore import QObject, QThread, QUrl, Qt, Signal
from PySide6.QtGui import QDesktopServices, QDragEnterEvent, QDragLeaveEvent, QDropEvent, QPixmap
from PySide6.QtWidgets import (
    QFileDialog,
    QFormLayout,
    QFrame,
    QHBoxLayout,
    QHeaderView,
    QLabel,
    QSizePolicy,
    QTableWidgetItem,
    QVBoxLayout,
    QWidget,
)
from qfluentwidgets import (
    BodyLabel,
    CaptionLabel,
    CardWidget,
    ComboBox,
    FluentIcon,
    HeaderCardWidget,
    InfoBar,
    InfoBarPosition,
    LineEdit,
    PrimaryPushButton,
    PushButton,
    ScrollArea,
    StrongBodyLabel,
    SubtitleLabel,
    TitleLabel,
    isDarkTheme,
)

from core.addons_scanner import AddonsScanner
from core.archive_service import ArchiveSourceManager
from core.config_manager import ConfigManager
from core.history_manager import HistoryManager
from core.i18n import LocalizationManager
from core.models import (
    AppConfig,
    BatchQueueItem,
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
    ConversionOptionsGroupPanel,
    TemplatePreviewCard,
    TemplateTagsHintBar,
    create_preview_zoom_button,
    create_styled_mod_table,
    create_table_thumb_cell,
    launch_l4d2_steam,
    record_conversion_history,
    render_output_vpk_filenames,
    set_table_headers_with_icons,
    shutdown_worker_thread,
    update_template_preview_card,
)
from ui.addons_browser_dialog import AddonsBrowserDialog
from ui.conversion_confirm_dialog import ConversionConfirmDialog, ConversionConfirmEntry
from ui.error_dialog import ErrorDetailsDialog
from ui.theme import COLORS, L4d2ThemeManager
from ui.workshop_download_dialog import WorkshopUrlDialog
from ui.widgets import (
    ClickableImageLabel,
    FlowPanel,
    ImageZoomDialog,
    InlineWarningBanner,
    ProgressLogCard,
    SurvivorCrewsPanel,
    add_card_header_icon,
    create_checkbox_with_help,
    create_help_badge,
    create_icon_row,
    update_checkbox_help,
    update_help_badge,
)


class BatchSwapWorker(QObject):
    """Background worker processing queued batch SwapJobRequest items sequentially."""

    progressUpdated = Signal(int, str, str)
    itemStarted = Signal(str)
    itemFinished = Signal(str, list, str)
    queueFinished = Signal(bool)

    def __init__(
        self,
        env_status: EnvironmentStatus,
        kit_dir: Path,
        jobs: list[tuple[str, str, SwapJobRequest]],
        keep_temp_on_error: bool = False,
        language_preference: str = "en-US",
    ) -> None:
        super().__init__()
        self.env_status = env_status
        self.kit_dir = kit_dir
        self.jobs = jobs
        self.keep_temp_on_error = keep_temp_on_error
        self.language_preference = language_preference
        self._cancel_event = threading.Event()

    def request_cancel(self) -> None:
        self._cancel_event.set()

    def run(self) -> None:
        local_i18n = LocalizationManager(self.language_preference)
        engine = SwapEngine(
            self.env_status,
            self.kit_dir,
            i18n=local_i18n,
        )
        total = max(1, len(self.jobs))
        was_cancelled = False

        for idx, (item_id, display_name, request) in enumerate(self.jobs):
            if self._cancel_event.is_set():
                was_cancelled = True
                break

            self.itemStarted.emit(item_id)
            prefix = local_i18n.tr(
                "batch_prog_item",
                index=idx + 1,
                total=total,
                name=display_name,
            )
            base_pct = int((idx / total) * 100)
            span_pct = max(1, 100.0 / total)

            def on_item_progress(prog: SwapProgress) -> None:
                overall = min(99, base_pct + int((prog.percent / 100.0) * span_pct))
                msg = f"{prefix}  ·  {prog.message}"
                line = prog.log_line or f"{prefix}: {prog.message}"
                self.progressUpdated.emit(overall, msg, line)

            try:
                results = engine.run_job(
                    request,
                    progress_cb=on_item_progress,
                    keep_temp_on_error=self.keep_temp_on_error,
                    cancel_cb=self._cancel_event.is_set,
                )
                self.itemFinished.emit(item_id, results, "")
                if any(r.cancelled for r in results) or self._cancel_event.is_set():
                    was_cancelled = True
                    break
            except Exception as exc:
                self.itemFinished.emit(item_id, [], str(exc))
                if self._cancel_event.is_set():
                    was_cancelled = True
                    break

        self.queueFinished.emit(was_cancelled)


class BatchSwapPage(ScrollArea):
    """Multi-mod batch conversion queue with global defaults and per-mod overrides."""

    conversionRecorded = Signal()
    addonsChanged = Signal()

    def __init__(
        self,
        config_mgr: ConfigManager,
        history_mgr: HistoryManager,
        get_config_fn: Callable[[], AppConfig],
        get_env_fn: Callable[[], EnvironmentStatus],
        i18n: Optional[LocalizationManager] = None,
        parent: Optional[QWidget] = None,
    ) -> None:
        super().__init__(parent)
        self.setObjectName("batchSwapPage")
        self.config_mgr = config_mgr
        self.history_mgr = history_mgr
        self._get_config = get_config_fn
        self._get_env = get_env_fn
        self._i18n = i18n or LocalizationManager("en-US")
        self._vpk_service = VpkService()

        self._items: list[BatchQueueItem] = []
        self._archive_temp_dirs: list[Path] = []
        self._loading_detail = False
        self._worker_thread: Optional[QThread] = None
        self._worker: Optional[BatchSwapWorker] = None
        self._run_item_meta: dict[str, dict] = {}
        self._run_ok_count = 0
        self._run_fail_count = 0
        self._run_fatal_errors: list[str] = []
        self._run_installed_any = False

        self.view = QWidget(self)
        self.view.setObjectName("batchPageContainer")
        self.setWidget(self.view)
        self.setWidgetResizable(True)
        self.enableTransparentBackground()
        self.setAcceptDrops(True)

        root = QVBoxLayout(self.view)
        root.setContentsMargins(28, 24, 28, 32)
        root.setSpacing(16)

        self.title_label = TitleLabel("", self.view)
        root.addLayout(create_icon_row(FluentIcon.LIBRARY, self.title_label, self.view, size=24, spacing=10))
        self.subtitle_label = CaptionLabel("", self.view)
        self.subtitle_label.setWordWrap(True)
        root.addWidget(self.subtitle_label)

        self.toolbar_card = QFrame(self.view)
        self.toolbar_card.setObjectName("batchDropToolbar")
        self.toolbar_card.setAttribute(Qt.WidgetAttribute.WA_StyledBackground, True)
        toolbar_vbox = QVBoxLayout(self.toolbar_card)
        toolbar_vbox.setContentsMargins(16, 14, 16, 14)
        toolbar_vbox.setSpacing(10)

        self.toolbar_btns_panel = FlowPanel(h_space=8, v_space=8, parent=self.toolbar_card)
        self.add_files_btn = PushButton(FluentIcon.DOCUMENT, "", self.toolbar_btns_panel)
        self.add_dir_btn = PushButton(FluentIcon.FOLDER, "", self.toolbar_btns_panel)
        self.add_workshop_btn = PushButton(FluentIcon.GAME, "", self.toolbar_btns_panel)
        self.add_url_btn = PushButton(FluentIcon.LINK, "", self.toolbar_btns_panel)
        self.remove_btn = PushButton(FluentIcon.DELETE, "", self.toolbar_btns_panel)
        self.clear_btn = PushButton(FluentIcon.ERASE_TOOL, "", self.toolbar_btns_panel)
        self.remove_btn.setEnabled(False)
        self.clear_btn.setEnabled(False)
        for btn in (
            self.add_files_btn,
            self.add_dir_btn,
            self.add_workshop_btn,
            self.add_url_btn,
            self.remove_btn,
            self.clear_btn,
        ):
            self.toolbar_btns_panel.flow.addWidget(btn)
        self.toolbar_btns_panel.sync_height(fallback_width=720)
        toolbar_vbox.addWidget(self.toolbar_btns_panel)

        self.drop_hint_label = CaptionLabel("", self.toolbar_card)
        self.drop_hint_label.setWordWrap(True)
        toolbar_vbox.addWidget(self.drop_hint_label)
        root.addWidget(self.toolbar_card)

        self.global_card = HeaderCardWidget(self.view)
        add_card_header_icon(self.global_card, FluentIcon.SETTING)
        global_inner = QWidget(self.global_card)
        global_vbox = QVBoxLayout(global_inner)
        global_vbox.setContentsMargins(0, 0, 0, 0)
        global_vbox.setSpacing(10)

        self.global_quick_panel = FlowPanel(h_space=8, v_space=6, parent=global_inner)
        self.lbl_global_dests = StrongBodyLabel("", self.global_quick_panel)
        self.btn_global_all = PushButton(FluentIcon.TILES, "", self.global_quick_panel)
        self.btn_global_l4d1 = PushButton(FluentIcon.PEOPLE, "", self.global_quick_panel)
        self.btn_global_l4d2 = PushButton(FluentIcon.PEOPLE, "", self.global_quick_panel)
        self.btn_global_clear = PushButton(FluentIcon.ERASE_TOOL, "", self.global_quick_panel)
        apply_all_wrap = QWidget(self.global_quick_panel)
        apply_all_lay = QHBoxLayout(apply_all_wrap)
        apply_all_lay.setContentsMargins(0, 0, 0, 0)
        apply_all_lay.setSpacing(6)
        self.apply_all_btn = PushButton(FluentIcon.SYNC, "", apply_all_wrap)
        self.help_apply_all = create_help_badge("", apply_all_wrap)
        apply_all_lay.addWidget(self.apply_all_btn)
        apply_all_lay.addWidget(self.help_apply_all, 0, Qt.AlignmentFlag.AlignVCenter)
        for quick_w in (
            self.lbl_global_dests,
            self.btn_global_all,
            self.btn_global_l4d1,
            self.btn_global_l4d2,
            self.btn_global_clear,
            apply_all_wrap,
        ):
            self.global_quick_panel.flow.addWidget(quick_w)
        self.global_quick_panel.sync_height(fallback_width=720)
        global_vbox.addWidget(self.global_quick_panel)

        self.global_crews_panel = SurvivorCrewsPanel(
            button_min_width=142,
            button_min_height=38,
            fallback_width=680,
            on_toggled=self._on_global_defaults_changed,
            i18n=self._i18n,
            parent=global_inner,
        )
        self._global_buttons = self.global_crews_panel.buttons
        global_vbox.addWidget(self.global_crews_panel)

        tpl_form = QFormLayout()
        tpl_form.setSpacing(8)
        tpl_form.setFieldGrowthPolicy(QFormLayout.FieldGrowthPolicy.ExpandingFieldsGrow)
        self.lbl_global_name = BodyLabel("", global_inner)
        self.global_name_edit = LineEdit(global_inner)
        self.global_name_edit.setText("{orig_title}-{survivor}")
        self.lbl_global_title = BodyLabel("", global_inner)
        self.global_title_edit = LineEdit(global_inner)
        self.global_title_edit.setText("{orig_title} ({survivor})")
        self.global_tags_bar = TemplateTagsHintBar(i18n=self._i18n, parent=global_inner)
        self.global_tags_bar.bind_target_edits(self.global_name_edit, self.global_title_edit)
        self.global_tags_hint = self.global_tags_bar.hint_label
        self.global_preview_card = TemplatePreviewCard(i18n=self._i18n, parent=global_inner)
        self.global_preview_label = CaptionLabel("", self.global_preview_card)
        self.global_preview_label.setVisible(False)

        tpl_form.addRow(self.lbl_global_name, self.global_name_edit)
        tpl_form.addRow(self.lbl_global_title, self.global_title_edit)
        tpl_form.addRow("", self.global_tags_bar)
        tpl_form.addRow("", self.global_preview_card)

        self.lbl_global_opts = BodyLabel("", global_inner)
        self.global_options_group = ConversionOptionsGroupPanel(
            install_default=bool(self._get_config().auto_install_to_addons),
            sanitize_default=bool(self._get_config().sanitize_origin_title),
            fallback_width=620,
            i18n=self._i18n,
            parent=global_inner,
        )
        self.global_switch_arms = self.global_options_group.switch_arms
        self.global_help_arms = self.global_options_group.help_arms
        self.global_switch_vgui = self.global_options_group.switch_vgui
        self.global_help_vgui = self.global_options_group.help_vgui
        self.global_weapons_row = self.global_options_group.weapons_row
        self.global_switch_weapons = self.global_options_group.switch_weapons
        self.global_help_weapons = self.global_options_group.help_weapons
        self.global_switch_install = self.global_options_group.switch_install
        self.global_help_install = self.global_options_group.help_install
        self.global_switch_sanitize = self.global_options_group.switch_sanitize
        self.global_help_sanitize = self.global_options_group.help_sanitize
        tpl_form.addRow(self.lbl_global_opts, self.global_options_group)

        global_vbox.addLayout(tpl_form)
        self.global_card.viewLayout.addWidget(global_inner)
        root.addWidget(self.global_card)

        split_row = QHBoxLayout()
        split_row.setSpacing(14)

        self.queue_table = create_styled_mod_table(
            self.view,
            ["", "", "", "", ""],
            min_height=380,
        )
        q_header = self.queue_table.horizontalHeader()
        q_header.setSectionResizeMode(1, QHeaderView.ResizeMode.Stretch)
        q_header.setSectionResizeMode(2, QHeaderView.ResizeMode.ResizeToContents)
        q_header.setSectionResizeMode(3, QHeaderView.ResizeMode.ResizeToContents)
        q_header.setSectionResizeMode(4, QHeaderView.ResizeMode.ResizeToContents)
        self.queue_table.setMinimumWidth(460)
        split_row.addWidget(self.queue_table, 1)

        self.detail_card = CardWidget(self.view)
        self.detail_card.setObjectName("batchDetailPanel")
        self.detail_card.setAttribute(Qt.WidgetAttribute.WA_StyledBackground, True)
        self.detail_card.setFixedWidth(400)
        detail_vbox = QVBoxLayout(self.detail_card)
        detail_vbox.setContentsMargins(16, 14, 16, 16)
        detail_vbox.setSpacing(10)

        self.detail_title_label = SubtitleLabel("", self.detail_card)
        self.detail_title_label.setWordWrap(True)
        detail_vbox.addLayout(
            create_icon_row(FluentIcon.EDIT, self.detail_title_label, self.detail_card, size=18, spacing=8)
        )

        self.detail_empty_label = BodyLabel("", self.detail_card)
        self.detail_empty_label.setWordWrap(True)
        detail_vbox.addWidget(self.detail_empty_label)

        self.detail_editor = QWidget(self.detail_card)
        editor_vbox = QVBoxLayout(self.detail_editor)
        editor_vbox.setContentsMargins(0, 0, 0, 0)
        editor_vbox.setSpacing(10)

        cover_row = QHBoxLayout()
        cover_row.setSpacing(10)
        self.item_cover_thumb = ClickableImageLabel(self.detail_editor)
        self.item_cover_thumb.setObjectName("batchCoverThumb")
        self.item_cover_thumb.setFixedSize(112, 84)
        self.item_cover_thumb.setAlignment(Qt.AlignmentFlag.AlignCenter)
        self.item_cover_zoom_btn = create_preview_zoom_button(
            self.item_cover_thumb,
            tooltip=self._i18n.tr("addons_dlg_zoom_tip"),
            size=22,
            margin=4,
        )
        cover_btns = QVBoxLayout()
        cover_btns.setSpacing(4)
        self.item_choose_cover_btn = PushButton(FluentIcon.PHOTO, "", self.detail_editor)
        self.item_reset_cover_btn = PushButton(FluentIcon.SYNC, "", self.detail_editor)
        self.item_reset_cover_btn.setEnabled(False)
        self.item_cover_status_label = CaptionLabel("", self.detail_editor)
        self.item_cover_status_label.setWordWrap(True)
        cover_btns.addWidget(self.item_choose_cover_btn)
        cover_btns.addWidget(self.item_reset_cover_btn)
        cover_btns.addWidget(self.item_cover_status_label)
        cover_row.addWidget(self.item_cover_thumb)
        cover_row.addLayout(cover_btns, 1)
        editor_vbox.addLayout(cover_row)

        detail_form = QFormLayout()
        detail_form.setSpacing(6)
        detail_form.setRowWrapPolicy(QFormLayout.RowWrapPolicy.WrapAllRows)
        detail_form.setFieldGrowthPolicy(QFormLayout.FieldGrowthPolicy.ExpandingFieldsGrow)

        self.lbl_item_origin = BodyLabel("", self.detail_editor)
        self.item_origin_combo = ComboBox(self.detail_editor)
        self.item_origin_combo.addItem("", userData=None)
        for spec in SurvivorRegistry.all():
            self.item_origin_combo.addItem(f"{spec.display_name} ({spec.generation})", userData=spec.id)
        detail_form.addRow(self.lbl_item_origin, self.item_origin_combo)
        self.item_origin_warning = InlineWarningBanner(self.detail_editor)
        detail_form.addRow(self.item_origin_warning)
        self.item_light_warning = InlineWarningBanner(self.detail_editor)
        detail_form.addRow(self.item_light_warning)

        self.lbl_item_output = BodyLabel("", self.detail_editor)
        self.item_output_edit = LineEdit(self.detail_editor)
        self.lbl_item_title = BodyLabel("", self.detail_editor)
        self.item_title_edit = LineEdit(self.detail_editor)
        self.item_tags_bar = TemplateTagsHintBar(i18n=self._i18n, parent=self.detail_editor)
        self.item_tags_bar.bind_target_edits(self.item_output_edit, self.item_title_edit)
        self.item_preview_card = TemplatePreviewCard(i18n=self._i18n, parent=self.detail_editor)
        self.item_preview_label = CaptionLabel("", self.item_preview_card)
        self.item_preview_label.setVisible(False)
        self.lbl_item_author = BodyLabel("", self.detail_editor)
        self.item_author_edit = LineEdit(self.detail_editor)
        self.lbl_item_version = BodyLabel("", self.detail_editor)
        self.item_version_edit = LineEdit(self.detail_editor)
        self.lbl_item_desc = BodyLabel("", self.detail_editor)
        self.item_desc_edit = LineEdit(self.detail_editor)

        detail_form.addRow(self.lbl_item_output, self.item_output_edit)
        detail_form.addRow(self.lbl_item_title, self.item_title_edit)
        detail_form.addRow("", self.item_tags_bar)
        detail_form.addRow("", self.item_preview_card)
        detail_form.addRow(self.lbl_item_author, self.item_author_edit)
        detail_form.addRow(self.lbl_item_version, self.item_version_edit)
        detail_form.addRow(self.lbl_item_desc, self.item_desc_edit)
        editor_vbox.addLayout(detail_form)

        global_dest_chk_row, self.use_global_dests_chk, self.item_help_global_dests = create_checkbox_with_help(
            "", True, "", self.detail_editor
        )
        editor_vbox.addWidget(global_dest_chk_row)
        self.item_crews_panel = SurvivorCrewsPanel(
            button_min_width=142,
            button_min_height=34,
            fallback_width=360,
            on_toggled=self._on_item_detail_edited,
            i18n=self._i18n,
            parent=self.detail_editor,
        )
        self.item_dest_container = self.item_crews_panel
        self._item_dest_buttons = self.item_crews_panel.buttons
        editor_vbox.addWidget(self.item_crews_panel)

        global_opts_chk_row, self.use_global_opts_chk, self.item_help_global_opts = create_checkbox_with_help(
            "", True, "", self.detail_editor
        )
        editor_vbox.addWidget(global_opts_chk_row)
        self.item_options_group = ConversionOptionsGroupPanel(
            install_default=False,
            sanitize_default=True,
            fallback_width=360,
            i18n=self._i18n,
            parent=self.detail_editor,
        )
        self.item_switch_arms = self.item_options_group.switch_arms
        self.item_help_arms = self.item_options_group.help_arms
        self.item_switch_vgui = self.item_options_group.switch_vgui
        self.item_help_vgui = self.item_options_group.help_vgui
        self.item_weapons_row = self.item_options_group.weapons_row
        self.item_switch_weapons = self.item_options_group.switch_weapons
        self.item_help_weapons = self.item_options_group.help_weapons
        self.item_switch_install = self.item_options_group.switch_install
        self.item_help_install = self.item_options_group.help_install
        self.item_switch_sanitize = self.item_options_group.switch_sanitize
        self.item_help_sanitize = self.item_options_group.help_sanitize
        editor_vbox.addWidget(self.item_options_group)

        detail_vbox.addWidget(self.detail_editor)
        detail_vbox.addStretch(1)
        self.detail_editor.setVisible(False)
        split_row.addWidget(self.detail_card)
        root.addLayout(split_row)

        action_row = QHBoxLayout()
        action_row.setSpacing(10)
        self.convert_btn = PrimaryPushButton(FluentIcon.PLAY, "", self.view)
        self.convert_btn.setMinimumHeight(42)
        self.convert_btn.setEnabled(False)
        self.cancel_btn = PushButton(FluentIcon.CLOSE, "", self.view)
        self.cancel_btn.setMinimumHeight(42)
        self.cancel_btn.setVisible(False)
        self.cancel_btn.setEnabled(False)
        self.open_out_btn = PushButton(FluentIcon.FOLDER, "", self.view)
        self.launch_l4d2_btn = PushButton(FluentIcon.PLAY_SOLID, "", self.view)
        action_row.addWidget(self.convert_btn)
        action_row.addWidget(self.cancel_btn)
        action_row.addWidget(self.open_out_btn)
        action_row.addWidget(self.launch_l4d2_btn)
        action_row.addStretch(1)
        root.addLayout(action_row)

        self.progress_card = ProgressLogCard(i18n=self._i18n, parent=self.view)
        root.addWidget(self.progress_card)
        root.addStretch(1)

        self._connect_signals()
        self.retranslate_ui(self._i18n)
        self._apply_panel_styles(drag_active=False)

    def _connect_signals(self) -> None:
        self.add_files_btn.clicked.connect(self._on_browse_files)
        self.add_dir_btn.clicked.connect(self._on_browse_folder)
        self.add_workshop_btn.clicked.connect(self._on_browse_workshop)
        self.add_url_btn.clicked.connect(self._on_download_workshop_urls)
        self.remove_btn.clicked.connect(self._on_remove_selected)
        self.clear_btn.clicked.connect(self.clear_queue)

        self.btn_global_all.clicked.connect(lambda: self._select_global_group(None))
        self.btn_global_l4d1.clicked.connect(lambda: self._select_global_group("L4D1"))
        self.btn_global_l4d2.clicked.connect(lambda: self._select_global_group("L4D2"))
        self.btn_global_clear.clicked.connect(lambda: self._select_global_group("NONE"))
        self.apply_all_btn.clicked.connect(self.apply_global_defaults_to_all)

        self.global_name_edit.textChanged.connect(self._on_global_defaults_changed)
        self.global_title_edit.textChanged.connect(self._on_global_defaults_changed)
        for sw in (
            self.global_switch_arms,
            self.global_switch_vgui,
            self.global_switch_weapons,
            self.global_switch_install,
            self.global_switch_sanitize,
        ):
            sw.checkedChanged.connect(self._on_global_defaults_changed)

        self.queue_table.itemSelectionChanged.connect(self._on_queue_selection_changed)

        self.item_origin_combo.currentIndexChanged.connect(self._on_item_detail_edited)
        self.item_output_edit.textChanged.connect(self._on_item_detail_edited)
        self.item_title_edit.textChanged.connect(self._on_item_detail_edited)
        self.item_author_edit.textChanged.connect(self._on_item_detail_edited)
        self.item_version_edit.textChanged.connect(self._on_item_detail_edited)
        self.item_desc_edit.textChanged.connect(self._on_item_detail_edited)
        self.use_global_dests_chk.stateChanged.connect(self._on_item_detail_edited)
        self.use_global_opts_chk.stateChanged.connect(self._on_item_detail_edited)
        for sw in (
            self.item_switch_arms,
            self.item_switch_vgui,
            self.item_switch_weapons,
            self.item_switch_install,
            self.item_switch_sanitize,
        ):
            sw.checkedChanged.connect(self._on_item_detail_edited)

        self.item_cover_thumb.clicked.connect(self._on_zoom_item_cover)
        self.item_cover_zoom_btn.clicked.connect(self._on_zoom_item_cover)
        self.item_choose_cover_btn.clicked.connect(self._on_choose_item_cover)
        self.item_reset_cover_btn.clicked.connect(self._on_reset_item_cover)

        self.convert_btn.clicked.connect(self._on_start_batch)
        self.cancel_btn.clicked.connect(self._on_cancel_batch)
        self.open_out_btn.clicked.connect(self._on_open_output_dir)
        self.launch_l4d2_btn.clicked.connect(launch_l4d2_steam)

    def dragEnterEvent(self, event: QDragEnterEvent) -> None:
        urls = event.mimeData().urls()
        if any(
            url.isLocalFile() and ArchiveSourceManager.is_supported_drop_path(Path(url.toLocalFile()))
            for url in urls
        ):
            self._apply_panel_styles(drag_active=True)
            event.acceptProposedAction()
            return
        event.ignore()

    def dragLeaveEvent(self, _event: QDragLeaveEvent) -> None:
        self._apply_panel_styles(drag_active=False)

    def dropEvent(self, event: QDropEvent) -> None:
        self._apply_panel_styles(drag_active=False)
        local_paths = [Path(u.toLocalFile()) for u in event.mimeData().urls() if u.isLocalFile()]
        supported = [p for p in local_paths if ArchiveSourceManager.is_supported_drop_path(p)]
        if not supported:
            bad_name = local_paths[0].name if local_paths else "..."
            InfoBar.error(
                self._i18n.tr("err_drop_invalid_title"),
                self._i18n.tr("err_drop_unsupported_ext", name=bad_name),
                parent=self.window(),
                position=InfoBarPosition.TOP,
                duration=5000,
            )
            event.ignore()
            return
        event.acceptProposedAction()
        self.add_sources(supported)

    def add_sources(self, paths: list[Path]) -> int:
        """Inspect and append valid VPKs, folders, or archives (including multi-VPK packs)."""
        added = 0
        existing_resolved = {item.source_path.resolve() for item in self._items if item.source_path.exists()}

        for raw_path in paths:
            prep = ArchiveSourceManager.prepare_source(raw_path)
            if not prep.valid:
                if prep.temp_dir is not None:
                    shutil.rmtree(prep.temp_dir, ignore_errors=True)
                msg = (
                    self._i18n.tr(prep.error_key, **prep.error_kwargs)
                    if prep.error_key
                    else self._i18n.tr("err_drop_invalid_folder", name=raw_path.name)
                )
                InfoBar.warning(
                    self._i18n.tr("info_err_read_title"),
                    msg,
                    parent=self.window(),
                    position=InfoBarPosition.TOP,
                )
                continue

            if prep.temp_dir is not None:
                self._archive_temp_dirs.append(prep.temp_dir)

            targets = prep.candidate_vpks if prep.candidate_vpks else (
                [prep.resolved_path] if prep.resolved_path is not None else []
            )
            for src_path in targets:
                resolved_src = src_path.resolve()
                if resolved_src in existing_resolved:
                    continue
                existing_resolved.add(resolved_src)
                try:
                    info = self._vpk_service.inspect_source(src_path)
                except Exception as exc:
                    InfoBar.error(
                        self._i18n.tr("info_err_read_title"),
                        f"{src_path.name}: {exc}",
                        parent=self.window(),
                        position=InfoBarPosition.TOP,
                    )
                    continue

                stem = src_path.stem
                orig_title = info.metadata.original_title or info.metadata.title or stem
                title_tpl = self.global_title_edit.text().strip() or "{orig_title} ({survivor})"
                name_tpl = self.global_name_edit.text().strip() or "{orig_title}-{survivor}"
                item_meta = ModMetadata(
                    title=title_tpl,
                    version=info.metadata.version or "1.0",
                    description=info.metadata.description,
                    author=info.metadata.author,
                    author_steam_id=info.metadata.author_steam_id,
                    url=info.metadata.url,
                    extra_fields=dict(info.metadata.extra_fields),
                    original_title=orig_title,
                )
                cover_bytes = AddonsScanner.read_source_preview_image(src_path)
                item = BatchQueueItem(
                    item_id=uuid.uuid4().hex[:10],
                    source_path=src_path,
                    display_name=info.metadata.title or src_path.name,
                    detected_info=info,
                    origin=info.detected_origin,
                    destinations=[],
                    use_global_destinations=True,
                    use_global_options=True,
                    output_name_template=name_tpl,
                    metadata=item_meta,
                    include_arms=self.global_switch_arms.isChecked(),
                    include_vgui=self.global_switch_vgui.isChecked(),
                    include_weapons=self.global_switch_weapons.isChecked(),
                    install_to_addons=self.global_switch_install.isChecked(),
                    sanitize_origin_title=self.global_switch_sanitize.isChecked(),
                    original_cover_bytes=cover_bytes,
                )
                self._items.append(item)
                existing_resolved.add(src_path.resolve())
                added += 1

        if added > 0:
            self._rebuild_table(select_last=self.queue_table.currentRow() < 0)
            self._update_queue_action_states()
        return added

    def apply_global_defaults_to_all(self) -> None:
        """Reset all queued items back to current Global Queue Defaults."""
        name_tpl = self.global_name_edit.text().strip() or "{orig_title}-{survivor}"
        title_tpl = self.global_title_edit.text().strip() or "{orig_title} ({survivor})"
        for item in self._items:
            item.use_global_destinations = True
            item.use_global_options = True
            item.output_name_template = name_tpl
            item.metadata.title = title_tpl
            item.include_arms = self.global_switch_arms.isChecked()
            item.include_vgui = self.global_switch_vgui.isChecked()
            item.include_weapons = self.global_switch_weapons.isChecked()
            item.install_to_addons = self.global_switch_install.isChecked()
            item.sanitize_origin_title = self.global_switch_sanitize.isChecked()
        self._rebuild_table()
        self._load_selected_item_detail()

    def clear_queue(self) -> None:
        if self._worker_thread is not None and self._worker_thread.isRunning():
            return
        self._items.clear()
        self._cleanup_archive_temps()
        self._rebuild_table()
        self._load_selected_item_detail()
        self.progress_card.reset_idle()
        self._update_queue_action_states()

    def _selected_item(self) -> Optional[BatchQueueItem]:
        row = self.queue_table.currentRow()
        if row < 0:
            return None
        name_item = self.queue_table.item(row, 1)
        if name_item is None:
            return None
        item_id = name_item.data(Qt.ItemDataRole.UserRole)
        for item in self._items:
            if item.item_id == item_id:
                return item
        return None

    def _effective_destinations(self, item: BatchQueueItem) -> list[SurvivorId]:
        raw = self._selected_global_survivors() if item.use_global_destinations else item.destinations
        return [d for d in raw if d != item.origin]

    def _selected_global_survivors(self) -> list[SurvivorId]:
        return [sid for sid, btn in self._global_buttons.items() if btn.isChecked()]

    def _select_global_group(self, generation: Optional[str]) -> None:
        for sid, btn in self._global_buttons.items():
            spec = SurvivorRegistry.get(sid)
            checked = generation is None or spec.generation == generation
            if generation == "NONE":
                checked = False
            btn.blockSignals(True)
            btn.setChecked(checked)
            btn.blockSignals(False)
        self._on_global_defaults_changed()

    def _on_global_defaults_changed(self) -> None:
        self._refresh_all_table_rows_text()
        self._refresh_global_template_preview()
        self._load_selected_item_detail()

    def _on_browse_files(self) -> None:
        files, _ = QFileDialog.getOpenFileNames(
            self,
            self._i18n.tr("dlg_select_vpk_title"),
            "",
            self._i18n.tr("dlg_select_vpk_filter"),
        )
        if files:
            self.add_sources([Path(f) for f in files])

    def _on_browse_folder(self) -> None:
        dir_str = QFileDialog.getExistingDirectory(self, self._i18n.tr("dlg_select_dir_title"))
        if dir_str:
            self.add_sources([Path(dir_str)])

    def _on_browse_workshop(self) -> None:
        addons_dir = self._get_env().l4d2_addons_dir
        if addons_dir is None or not addons_dir.is_dir():
            InfoBar.warning(
                self._i18n.tr("info_addons_missing_title"),
                self._i18n.tr("info_addons_missing_msg"),
                parent=self.window(),
                position=InfoBarPosition.TOP,
            )
            return
        dlg = AddonsBrowserDialog(
            addons_dir=addons_dir,
            i18n=self._i18n,
            parent=self.window(),
            auto_scan=True,
            multi_select=True,
        )
        if dlg.exec():
            entries = dlg.selected_entries()
            if entries:
                self.add_sources([e.vpk_path for e in entries])

    def _on_download_workshop_urls(self) -> None:
        env = self._get_env()
        cfg = self._get_config()
        dl_dir = self.config_mgr.resolve_path(cfg.workshop_download_dir or "Workshop_Downloads")
        dlg = WorkshopUrlDialog(
            download_dir=dl_dir,
            addons_dir=env.l4d2_addons_dir,
            allow_multiple=True,
            i18n=self._i18n,
            parent=self.window(),
        )
        if dlg.exec():
            paths = dlg.downloaded_paths()
            if paths:
                self.add_sources(paths)

    def _on_remove_selected(self) -> None:
        item = self._selected_item()
        if item is None:
            return
        self._items = [it for it in self._items if it.item_id != item.item_id]
        self._rebuild_table()
        self._load_selected_item_detail()
        self._update_queue_action_states()

    def _rebuild_table(self, select_last: bool = False) -> None:
        current = self._selected_item()
        current_id = current.item_id if current is not None else None
        is_dark = isDarkTheme()

        self.queue_table.blockSignals(True)
        self.queue_table.setRowCount(len(self._items))
        selected_row = -1

        for row, item in enumerate(self._items):
            cover_bytes = self._resolve_item_cover_bytes(item)
            self.queue_table.setCellWidget(
                row,
                0,
                create_table_thumb_cell(
                    self.queue_table,
                    cover_bytes,
                    is_dark,
                    title=item.display_name,
                    i18n=self._i18n,
                ),
            )
            self.queue_table.setItem(row, 0, self._make_table_item(""))

            mod_cell = self._make_table_item(item.display_name)
            mod_cell.setData(Qt.ItemDataRole.UserRole, item.item_id)
            self.queue_table.setItem(row, 1, mod_cell)
            self.queue_table.setItem(row, 2, self._make_table_item(self._format_origin_text(item)))
            self.queue_table.setItem(row, 3, self._make_table_item(self._format_dest_text(item)))
            self.queue_table.setItem(row, 4, self._make_table_item(self._format_status_text(item)))

            if current_id is not None and item.item_id == current_id:
                selected_row = row

        self.queue_table.blockSignals(False)

        if self._items:
            if select_last or selected_row < 0:
                target_row = len(self._items) - 1 if select_last else 0
            else:
                target_row = selected_row
            self.queue_table.selectRow(target_row)
        self._load_selected_item_detail()

    def _refresh_all_table_rows_text(self) -> None:
        for row, item in enumerate(self._items):
            if row >= self.queue_table.rowCount():
                break
            origin_cell = self.queue_table.item(row, 2)
            dest_cell = self.queue_table.item(row, 3)
            status_cell = self.queue_table.item(row, 4)
            if origin_cell is not None:
                origin_cell.setText(self._format_origin_text(item))
            if dest_cell is not None:
                dest_cell.setText(self._format_dest_text(item))
            if status_cell is not None:
                status_cell.setText(self._format_status_text(item))

    def _refresh_row_by_id(self, item_id: str, refresh_thumb: bool = False) -> None:
        is_dark = isDarkTheme()
        for row, item in enumerate(self._items):
            if item.item_id != item_id:
                continue
            if refresh_thumb:
                self.queue_table.setCellWidget(
                    row,
                    0,
                    create_table_thumb_cell(
                        self.queue_table,
                        self._resolve_item_cover_bytes(item),
                        is_dark,
                        title=item.display_name,
                        i18n=self._i18n,
                    ),
                )
            mod_cell = self.queue_table.item(row, 1)
            origin_cell = self.queue_table.item(row, 2)
            dest_cell = self.queue_table.item(row, 3)
            status_cell = self.queue_table.item(row, 4)
            if mod_cell is not None:
                mod_cell.setText(item.display_name)
            if origin_cell is not None:
                origin_cell.setText(self._format_origin_text(item))
            if dest_cell is not None:
                dest_cell.setText(self._format_dest_text(item))
            if status_cell is not None:
                status_cell.setText(self._format_status_text(item))
            break

    @staticmethod
    def _make_table_item(text: str) -> QTableWidgetItem:
        cell = QTableWidgetItem(text)
        cell.setFlags(cell.flags() & ~Qt.ItemFlag.ItemIsEditable)
        return cell

    def _format_origin_text(self, item: BatchQueueItem) -> str:
        if item.origin is None:
            return self._i18n.tr("origin_not_selected")
        sel_name = SurvivorRegistry.get(item.origin).display_name
        det = item.detected_info.detected_origin
        if det is not None and item.origin != det:
            det_name = SurvivorRegistry.get(det).display_name
            return f"⚠ {self._i18n.tr('origin_mismatch_short', selected=sel_name, detected=det_name)}"
        return sel_name

    def _format_dest_text(self, item: BatchQueueItem) -> str:
        eff = self._effective_destinations(item)
        if item.use_global_destinations:
            return self._i18n.tr("batch_dest_global", count=len(eff))
        return self._i18n.tr_plural("batch_dest_count", len(eff))

    def _format_status_text(self, item: BatchQueueItem) -> str:
        if item.status == "running":
            return self._i18n.tr("batch_status_running")
        if item.status == "done":
            return item.status_detail or self._i18n.tr("batch_status_done", ok=1, total=1)
        if item.status == "partial":
            return item.status_detail
        if item.status == "failed":
            return self._i18n.tr("batch_status_failed")
        if item.status == "cancelled":
            return self._i18n.tr("batch_status_cancelled")
        return self._i18n.tr("batch_status_pending")

    def _on_queue_selection_changed(self) -> None:
        self._load_selected_item_detail()
        self._update_queue_action_states()

    def _sync_item_dest_buttons(self, item: BatchQueueItem) -> None:
        self.item_dest_container.setEnabled(not item.use_global_destinations)
        eff_dests = set(self._effective_destinations(item))
        origin_tag = self._i18n.tr("origin_tag")
        was_loading = self._loading_detail
        self._loading_detail = True
        try:
            for sid, btn in self._item_dest_buttons.items():
                spec = SurvivorRegistry.get(sid)
                is_orig = item.origin is not None and sid == item.origin
                btn.set_origin_blocked(is_orig)
                btn.setEnabled(not item.use_global_destinations and not is_orig)
                btn.setChecked((not is_orig) and (sid in eff_dests))
                btn.setToolTip(f"{spec.display_name} · {origin_tag}" if is_orig else "")
        finally:
            self._loading_detail = was_loading

    def _load_selected_item_detail(self) -> None:
        item = self._selected_item()
        if item is None:
            self.detail_empty_label.setVisible(True)
            self.detail_editor.setVisible(False)
            self._refresh_global_template_preview()
            return

        self._loading_detail = True
        try:
            self.detail_empty_label.setVisible(False)
            self.detail_editor.setVisible(True)

            target_idx = 0
            if item.origin is not None:
                for idx in range(self.item_origin_combo.count()):
                    if self.item_origin_combo.itemData(idx) == item.origin:
                        target_idx = idx
                        break
            self.item_origin_combo.setCurrentIndex(target_idx)

            self.item_output_edit.setText(item.output_name_template)
            self.item_title_edit.setText(item.metadata.title)
            self.item_author_edit.setText(item.metadata.author)
            self.item_version_edit.setText(item.metadata.version or "1.0")
            self.item_desc_edit.setText(item.metadata.description)

            self.use_global_dests_chk.setChecked(item.use_global_destinations)
            self._sync_item_dest_buttons(item)

            self.use_global_opts_chk.setChecked(item.use_global_options)
            self.item_weapons_row.setVisible(False)
            arms, vgui, weapons, install, sanitize = self._effective_options(item)
            self.item_switch_arms.setChecked(arms)
            self.item_switch_vgui.setChecked(vgui)
            self.item_switch_weapons.setChecked(weapons)
            self.item_switch_install.setChecked(install)
            self.item_switch_sanitize.setChecked(sanitize)
            for sw in (
                self.item_switch_arms,
                self.item_switch_vgui,
                self.item_switch_weapons,
                self.item_switch_install,
                self.item_switch_sanitize,
            ):
                sw.setEnabled(not item.use_global_options)

            self._refresh_item_banners(item, show_popup=False)
            self._refresh_item_cover_preview(item)
            self._refresh_item_template_preview(item)
            self._refresh_global_template_preview()
        finally:
            self._loading_detail = False

    def _on_item_detail_edited(self) -> None:
        if self._loading_detail:
            return
        item = self._selected_item()
        if item is None:
            return

        prev_origin = item.origin
        origin_data = self.item_origin_combo.currentData()
        item.origin = origin_data if isinstance(origin_data, SurvivorId) else None
        origin_changed = item.origin != prev_origin
        item.output_name_template = self.item_output_edit.text().strip()
        item.metadata.title = self.item_title_edit.text().strip()
        item.metadata.author = self.item_author_edit.text().strip()
        item.metadata.version = self.item_version_edit.text().strip() or "1.0"
        item.metadata.description = self.item_desc_edit.text().strip()

        item.use_global_destinations = self.use_global_dests_chk.isChecked()
        if not item.use_global_destinations:
            item.destinations = [
                sid
                for sid, btn in self._item_dest_buttons.items()
                if sid != item.origin and btn.isChecked()
            ]
        self._sync_item_dest_buttons(item)

        item.use_global_options = self.use_global_opts_chk.isChecked()
        if item.use_global_options:
            self._loading_detail = True
            try:
                arms, vgui, weapons, install, sanitize = self._effective_options(item)
                self.item_switch_arms.setChecked(arms)
                self.item_switch_vgui.setChecked(vgui)
                self.item_switch_weapons.setChecked(weapons)
                self.item_switch_install.setChecked(install)
                self.item_switch_sanitize.setChecked(sanitize)
            finally:
                self._loading_detail = False
            for sw in (
                self.item_switch_arms,
                self.item_switch_vgui,
                self.item_switch_weapons,
                self.item_switch_install,
                self.item_switch_sanitize,
            ):
                sw.setEnabled(False)
        else:
            for sw in (
                self.item_switch_arms,
                self.item_switch_vgui,
                self.item_switch_weapons,
                self.item_switch_install,
                self.item_switch_sanitize,
            ):
                sw.setEnabled(True)
            item.include_arms = self.item_switch_arms.isChecked()
            item.include_vgui = self.item_switch_vgui.isChecked()
            item.include_weapons = self.item_switch_weapons.isChecked()
            item.install_to_addons = self.item_switch_install.isChecked()
            item.sanitize_origin_title = self.item_switch_sanitize.isChecked()

        self._refresh_item_banners(item, show_popup=origin_changed)
        self._refresh_item_template_preview(item)
        self._refresh_row_by_id(item.item_id)

    def _refresh_item_banners(self, item: BatchQueueItem, show_popup: bool = False) -> None:
        det = item.detected_info.detected_origin
        if det is not None and item.origin is not None and item.origin != det:
            det_name = SurvivorRegistry.get(det).display_name
            sel_name = SurvivorRegistry.get(item.origin).display_name
            msg = self._i18n.tr("origin_mismatch_warn", detected=det_name, selected=sel_name)
            self.item_origin_warning.set_warning(msg)
            if show_popup:
                InfoBar.warning(
                    self._i18n.tr("origin_label"),
                    msg,
                    parent=self.window(),
                    position=InfoBarPosition.TOP,
                    duration=5000,
                )
        else:
            self.item_origin_warning.set_warning("")

        if item.detected_info.has_light_models:
            self.item_light_warning.set_warning(self._i18n.tr("light_warn_banner"))
        else:
            self.item_light_warning.set_warning("")

    def _effective_options(self, item: BatchQueueItem) -> tuple[bool, bool, bool, bool, bool]:
        if item.use_global_options:
            return (
                self.global_switch_arms.isChecked(),
                self.global_switch_vgui.isChecked(),
                self.global_switch_weapons.isChecked(),
                self.global_switch_install.isChecked(),
                self.global_switch_sanitize.isChecked(),
            )
        return (
            item.include_arms,
            item.include_vgui,
            item.include_weapons,
            item.install_to_addons,
            item.sanitize_origin_title,
        )

    def _refresh_global_template_preview(self) -> None:
        dest_ids = self._selected_global_survivors()
        file_tpl = self.global_name_edit.text().strip() or "{orig_title}-{survivor}"
        title_tpl = self.global_title_edit.text().strip() or "{orig_title} ({survivor})"
        sanitize = self.global_switch_sanitize.isChecked()
        selected = self._selected_item()
        if selected is not None:
            orig_id = selected.origin
            fallback_stem = selected.source_path.stem
            orig_title = (
                selected.metadata.original_title or selected.metadata.title or fallback_stem
            )
            eff_dests = [d for d in dest_ids if d != orig_id]
        else:
            orig_id = None
            fallback_stem = "my_mod"
            orig_title = "My Mod"
            eff_dests = dest_ids
        update_template_preview_card(
            self.global_preview_card,
            self.global_preview_label,
            file_template=file_tpl,
            title_template=title_tpl,
            orig_title=orig_title,
            origin_id=orig_id,
            dest_ids=eff_dests,
            i18n=self._i18n,
            fallback_stem=fallback_stem,
            sanitize_origin=sanitize,
            max_targets=4,
        )

    def _refresh_item_template_preview(self, item: BatchQueueItem) -> None:
        eff_dests = self._effective_destinations(item)
        stem = item.source_path.stem
        orig_title = item.metadata.original_title or item.metadata.title or stem
        _, _, _, _, sanitize = self._effective_options(item)
        update_template_preview_card(
            self.item_preview_card,
            self.item_preview_label,
            file_template=item.output_name_template or stem,
            title_template=item.metadata.title or orig_title,
            orig_title=orig_title,
            origin_id=item.origin,
            dest_ids=eff_dests,
            i18n=self._i18n,
            fallback_stem=stem,
            sanitize_origin=sanitize,
            max_targets=4,
        )

    def _resolve_item_cover_bytes(self, item: BatchQueueItem) -> Optional[bytes]:
        if item.custom_addonimage_path is not None and item.custom_addonimage_path.is_file():
            try:
                return item.custom_addonimage_path.read_bytes()
            except OSError:
                return item.original_cover_bytes
        return item.original_cover_bytes

    def _refresh_item_cover_preview(self, item: BatchQueueItem) -> None:
        pixmap = QPixmap()
        if item.custom_addonimage_path is not None and item.custom_addonimage_path.is_file():
            pixmap.load(str(item.custom_addonimage_path))
            self.item_cover_status_label.setText(
                self._i18n.tr("cover_status_custom", name=item.custom_addonimage_path.name)
            )
            self.item_reset_cover_btn.setEnabled(True)
        elif item.original_cover_bytes and pixmap.loadFromData(item.original_cover_bytes):
            self.item_cover_status_label.setText(self._i18n.tr("cover_status_original"))
            self.item_reset_cover_btn.setEnabled(False)
        else:
            self.item_cover_status_label.setText(self._i18n.tr("cover_status_none"))
            self.item_reset_cover_btn.setEnabled(False)

        if not pixmap.isNull():
            self.item_cover_thumb.setPixmap(
                pixmap.scaled(
                    104,
                    76,
                    Qt.AspectRatioMode.KeepAspectRatio,
                    Qt.TransformationMode.SmoothTransformation,
                )
            )
            self.item_cover_thumb.setText("")
            self.item_cover_thumb.setCursor(Qt.CursorShape.PointingHandCursor)
            self.item_cover_thumb.setToolTip(self._i18n.tr("addons_dlg_zoom_tip"))
            self.item_cover_zoom_btn.setToolTip(self._i18n.tr("addons_dlg_zoom_tip"))
            self.item_cover_zoom_btn.setVisible(True)
        else:
            self.item_cover_thumb.setPixmap(QPixmap())
            self.item_cover_thumb.setText("—")
            self.item_cover_thumb.setCursor(Qt.CursorShape.ArrowCursor)
            self.item_cover_thumb.setToolTip("")
            self.item_cover_zoom_btn.setVisible(False)

    def _on_choose_item_cover(self) -> None:
        item = self._selected_item()
        if item is None:
            return
        img_str, _ = QFileDialog.getOpenFileName(
            self,
            self._i18n.tr("dlg_select_cover_title"),
            "",
            self._i18n.tr("dlg_select_cover_filter"),
        )
        if not img_str:
            return
        item.custom_addonimage_path = Path(img_str)
        self._refresh_item_cover_preview(item)
        self._refresh_row_by_id(item.item_id, refresh_thumb=True)

    def _on_reset_item_cover(self) -> None:
        item = self._selected_item()
        if item is None:
            return
        item.custom_addonimage_path = None
        self._refresh_item_cover_preview(item)
        self._refresh_row_by_id(item.item_id, refresh_thumb=True)

    def _on_zoom_item_cover(self) -> None:
        item = self._selected_item()
        if item is None:
            return
        raw = self._resolve_item_cover_bytes(item)
        pix = QPixmap()
        if not raw or not pix.loadFromData(raw) or pix.isNull():
            return
        dlg = ImageZoomDialog(
            title=item.display_name,
            pixmap=pix,
            i18n=self._i18n,
            parent=self.window(),
        )
        dlg.exec()

    def _on_start_batch(self) -> None:
        if self._worker_thread is not None and self._worker_thread.isRunning():
            return
        if not self._items:
            InfoBar.warning(
                self._i18n.tr("batch_info_no_items_title"),
                self._i18n.tr("batch_info_no_items_msg"),
                parent=self.window(),
                position=InfoBarPosition.TOP,
            )
            return

        env = self._get_env()
        if not env.is_ready_for_swap:
            InfoBar.error(
                self._i18n.tr("info_setup_incomplete_title"),
                self._i18n.tr("info_setup_incomplete_msg"),
                parent=self.window(),
                position=InfoBarPosition.TOP,
            )
            return

        cfg = self._get_config()
        output_dir = self.config_mgr.resolve_path(cfg.output_dir)
        kit_dir = self.config_mgr.resolve_path(cfg.kit_dir)

        jobs: list[tuple[str, str, SwapJobRequest]] = []
        meta_map: dict[str, dict] = {}
        confirm_entries: list[ConversionConfirmEntry] = []

        for item in self._items:
            if item.origin is None:
                InfoBar.warning(
                    self._i18n.tr("batch_info_bad_item_title"),
                    self._i18n.tr("batch_info_bad_origin", name=item.display_name),
                    parent=self.window(),
                    position=InfoBarPosition.TOP,
                )
                return
            eff_dests = self._effective_destinations(item)
            if not eff_dests:
                InfoBar.warning(
                    self._i18n.tr("batch_info_bad_item_title"),
                    self._i18n.tr("batch_info_no_dests", name=item.display_name),
                    parent=self.window(),
                    position=InfoBarPosition.TOP,
                )
                return

            arms, vgui, weapons, install, sanitize = self._effective_options(item)
            stem = item.source_path.stem
            orig_title = item.metadata.original_title or item.metadata.title or stem
            meta = ModMetadata(
                title=item.metadata.title or orig_title,
                version=item.metadata.version or "1.0",
                description=item.metadata.description,
                author=item.metadata.author,
                author_steam_id=item.metadata.author_steam_id,
                url=item.metadata.url,
                extra_fields=dict(item.metadata.extra_fields),
                original_title=orig_title,
            )
            out_template = item.output_name_template or stem
            request = SwapJobRequest(
                source_path=item.source_path,
                origin=item.origin,
                destinations=eff_dests,
                output_name_template=out_template,
                metadata=meta,
                output_dir=output_dir,
                install_to_addons=install,
                addons_dir=env.l4d2_addons_dir,
                include_arms=arms,
                include_vgui=vgui,
                include_weapons=weapons,
                sanitize_origin_title=sanitize,
                custom_addonimage_path=item.custom_addonimage_path,
            )
            jobs.append((item.item_id, item.display_name, request))
            meta_map[item.item_id] = {
                "mod_title": item.display_name,
                "author": meta.author,
                "source_path": str(item.source_path),
                "origin": item.origin.value,
                "destinations": [d.value for d in eff_dests],
                "output_dir": str(output_dir),
                "installed_to_addons": install,
                "custom_cover_used": item.custom_addonimage_path is not None,
            }
            confirm_entries.append(
                ConversionConfirmEntry(
                    title=meta.title,
                    source_filename=item.source_path.name,
                    author=meta.author,
                    version=meta.version,
                    origin=item.origin,
                    destinations=eff_dests,
                    output_files=render_output_vpk_filenames(
                        file_template=out_template,
                        title_template=meta.title,
                        orig_title=orig_title,
                        origin_id=item.origin,
                        dest_ids=eff_dests,
                        fallback_stem=stem,
                        sanitize_origin=sanitize,
                    ),
                    output_dir=str(output_dir),
                    cover_bytes=self._resolve_item_cover_bytes(item),
                    include_arms=arms,
                    include_vgui=vgui,
                    include_weapons=weapons if item.detected_info.has_weapons else None,
                    sanitize_origin=sanitize,
                    install_to_addons=install,
                )
            )

        confirm_dlg = ConversionConfirmDialog(
            confirm_entries,
            i18n=self._i18n,
            parent=self.window(),
        )
        if not confirm_dlg.exec():
            return

        self._run_item_meta.clear()
        self._run_item_meta.update(meta_map)
        self._run_ok_count = 0
        self._run_fail_count = 0
        self._run_fatal_errors.clear()
        self._run_installed_any = False
        for item in self._items:
            item.status = "pending"
            item.status_detail = ""

        self._refresh_all_table_rows_text()
        self._set_busy(True)
        self.progress_card.reset()

        self._worker_thread = QThread(self)
        self._worker = BatchSwapWorker(
            env_status=env,
            kit_dir=kit_dir,
            jobs=jobs,
            keep_temp_on_error=cfg.keep_temp_on_error,
            language_preference=self._i18n.preference,
        )
        self._worker.moveToThread(self._worker_thread)
        self._worker_thread.started.connect(self._worker.run)
        self._worker.progressUpdated.connect(self._on_worker_progress)
        self._worker.itemStarted.connect(self._on_item_started)
        self._worker.itemFinished.connect(self._on_item_finished)
        self._worker.queueFinished.connect(self._on_queue_finished)
        self._worker.queueFinished.connect(self._worker_thread.quit)
        self._worker_thread.finished.connect(self._cleanup_thread)
        self._worker_thread.start()

    def _on_cancel_batch(self) -> None:
        if self._worker is not None:
            self._worker.request_cancel()
            self.cancel_btn.setEnabled(False)
            self.progress_card.append_log(self._i18n.tr("btn_cancelling"))

    def _on_worker_progress(self, percent: int, message: str, log_line: str) -> None:
        self.progress_card.update_progress(percent, message)
        if log_line and log_line != message:
            self.progress_card.append_log(log_line)

    def _on_item_started(self, item_id: str) -> None:
        for item in self._items:
            if item.item_id == item_id:
                item.status = "running"
                item.status_detail = ""
                break
        self._refresh_row_by_id(item_id)

    def _on_item_finished(
        self,
        item_id: str,
        results: list[SwapTargetResult],
        fatal_error: str,
    ) -> None:
        target_item = next((it for it in self._items if it.item_id == item_id), None)
        meta_snap = self._run_item_meta.get(item_id)

        ok_cnt = sum(1 for r in results if r.success)
        cancel_cnt = sum(1 for r in results if r.cancelled)
        fail_cnt = sum(1 for r in results if not r.success and not r.cancelled)
        self._run_ok_count += ok_cnt
        self._run_fail_count += fail_cnt + (len(meta_snap["destinations"]) if fatal_error and not results and meta_snap else 0)
        if any(r.installed_path is not None for r in results if r.success):
            self._run_installed_any = True

        if target_item is not None:
            total = len(results) or (len(meta_snap["destinations"]) if meta_snap else 1)
            if fatal_error:
                target_item.status = "failed"
                target_item.status_detail = ""
            elif cancel_cnt > 0 and ok_cnt == 0:
                target_item.status = "cancelled"
                target_item.status_detail = ""
            elif ok_cnt == total and fail_cnt == 0:
                target_item.status = "done"
                target_item.status_detail = self._i18n.tr("batch_status_done", ok=ok_cnt, total=total)
            elif ok_cnt > 0:
                target_item.status = "partial"
                target_item.status_detail = self._i18n.tr("batch_status_partial", ok=ok_cnt, total=total)
            else:
                target_item.status = "failed"
                target_item.status_detail = ""
            self._refresh_row_by_id(item_id)

        if fatal_error:
            self._run_fatal_errors.append(fatal_error)
            self.progress_card.append_log(f"[ERROR] {fatal_error}")

        if meta_snap is not None:
            record_conversion_history(
                history_mgr=self.history_mgr,
                mod_title=meta_snap["mod_title"],
                author=meta_snap["author"],
                source_path=meta_snap["source_path"],
                origin=meta_snap["origin"],
                destinations=list(meta_snap["destinations"]),
                output_dir=meta_snap["output_dir"],
                installed_to_addons=bool(meta_snap["installed_to_addons"]),
                custom_cover_used=bool(meta_snap["custom_cover_used"]),
                results=results,
                fatal_error=fatal_error,
            )
            self.conversionRecorded.emit()

    def _on_queue_finished(self, was_cancelled: bool) -> None:
        self._set_busy(False)
        if self._run_installed_any:
            self.addonsChanged.emit()

        ok_text = self._i18n.tr_plural("batch_done_ok", self._run_ok_count)
        fail_text = self._i18n.tr_plural("batch_done_fail", self._run_fail_count)
        summary = f"{ok_text}  ·  {fail_text}"

        if was_cancelled:
            InfoBar.warning(
                self._i18n.tr("info_cancelled_title"),
                summary,
                parent=self.window(),
                position=InfoBarPosition.TOP,
                duration=5000,
            )
            return

        self.progress_card.update_progress(100, summary)
        if self._run_fail_count > 0 or self._run_fatal_errors:
            InfoBar.warning(
                self._i18n.tr("info_partial_title"),
                summary,
                parent=self.window(),
                position=InfoBarPosition.TOP,
                duration=6000,
            )
            if self._run_fatal_errors:
                combined = "\n\n".join(self._run_fatal_errors)
                ErrorDetailsDialog(
                    title=self._i18n.tr("info_fail_title"),
                    summary=self._run_fatal_errors[0].splitlines()[0],
                    details=combined,
                    i18n=self._i18n,
                    parent=self.window(),
                ).exec()
        else:
            InfoBar.success(
                self._i18n.tr("info_done_title"),
                summary,
                parent=self.window(),
                position=InfoBarPosition.TOP,
                duration=5000,
            )

    def _set_busy(self, busy: bool) -> None:
        self.convert_btn.setEnabled(not busy and bool(self._items))
        self.cancel_btn.setVisible(busy)
        self.cancel_btn.setEnabled(busy)
        self.add_files_btn.setEnabled(not busy)
        self.add_dir_btn.setEnabled(not busy)
        self.add_workshop_btn.setEnabled(not busy)
        self.add_url_btn.setEnabled(not busy)
        self.remove_btn.setEnabled(not busy and self._selected_item() is not None)
        self.clear_btn.setEnabled(not busy and bool(self._items))
        self.apply_all_btn.setEnabled(not busy)
        L4d2ThemeManager.apply_pointing_hand_cursors(self)

    def _update_queue_action_states(self) -> None:
        busy = self._worker_thread is not None and self._worker_thread.isRunning()
        count = len(self._items)
        self.global_weapons_row.setVisible(False)
        self.convert_btn.setEnabled(not busy and count > 0)
        self.remove_btn.setEnabled(not busy and self._selected_item() is not None)
        self.clear_btn.setEnabled(not busy and count > 0)
        self.convert_btn.setText(self._i18n.tr_plural("batch_btn_start", count))

    def _cleanup_thread(self) -> None:
        if self._worker is not None:
            self._worker.deleteLater()
            self._worker = None
        if self._worker_thread is not None:
            self._worker_thread.deleteLater()
            self._worker_thread = None

    def _cleanup_archive_temps(self) -> None:
        for tmp_dir in self._archive_temp_dirs:
            shutil.rmtree(tmp_dir, ignore_errors=True)
        self._archive_temp_dirs.clear()

    def shutdown_worker(self) -> None:
        shutdown_worker_thread(
            self._worker_thread,
            self._worker,
            cancel_fn=self._worker.request_cancel if self._worker is not None else None,
            ui_signals=(
                (
                    self._worker.progressUpdated,
                    self._worker.itemStarted,
                    self._worker.itemFinished,
                    self._worker.queueFinished,
                )
                if self._worker is not None
                else ()
            ),
            timeout_ms=5000,
        )
        self._worker = None
        self._worker_thread = None
        self._cleanup_archive_temps()

    def _on_open_output_dir(self) -> None:
        out_dir = self.config_mgr.resolve_path(self._get_config().output_dir)
        out_dir.mkdir(parents=True, exist_ok=True)
        try:
            os.startfile(str(out_dir))
        except OSError:
            QDesktopServices.openUrl(QUrl.fromLocalFile(str(out_dir)))

    def _apply_panel_styles(self, drag_active: bool = False) -> None:
        is_dark = isDarkTheme()
        border = COLORS.l4d2_green if drag_active else (COLORS.dark_border if is_dark else COLORS.light_border)
        muted = COLORS.dark_muted if is_dark else COLORS.light_muted
        panel_border = COLORS.dark_border if is_dark else COLORS.light_border
        L4d2ThemeManager.install_surface_motion(
            self.toolbar_card,
            f"QFrame#batchDropToolbar {{ background-color: {{bg}}; "
            f"border: 1.5px dashed {border}; border-radius: 8px; }}",
            tone="card",
        )
        L4d2ThemeManager.install_surface_motion(
            self.detail_card,
            f"QWidget#batchDetailPanel {{ background-color: {{bg}}; "
            f"border: 1px solid {panel_border}; border-radius: 8px; }}",
            tone="neutral",
        )
        L4d2ThemeManager.install_surface_motion(
            self.item_cover_thumb,
            f"QLabel#batchCoverThumb {{ background-color: {{bg}}; "
            f"border: 1px solid {{border}}; border-radius: 6px; color: {muted}; }}",
            custom_colors=L4d2ThemeManager.image_surface_palette(is_dark),
            border_colors=L4d2ThemeManager.image_border_colors(is_dark),
        )

    def retranslate_ui(self, i18n: LocalizationManager) -> None:
        self._i18n = i18n
        self.title_label.setText(i18n.tr("batch_page_title"))
        self.subtitle_label.setText(i18n.tr("batch_page_subtitle"))
        self.add_files_btn.setText(i18n.tr("batch_btn_add_files"))
        self.add_dir_btn.setText(i18n.tr("batch_btn_add_dir"))
        self.add_workshop_btn.setText(i18n.tr("batch_btn_add_workshop"))
        self.add_url_btn.setText(i18n.tr("batch_btn_link"))
        self.remove_btn.setText(i18n.tr("batch_btn_remove"))
        self.clear_btn.setText(i18n.tr("batch_btn_clear"))
        self.toolbar_btns_panel.sync_height(fallback_width=720)
        self.drop_hint_label.setText(i18n.tr("batch_drop_hint"))

        self.global_card.setTitle(i18n.tr("batch_global_title"))
        self.lbl_global_dests.setText(i18n.tr("batch_global_dests"))
        self.btn_global_all.setText(i18n.tr("btn_all_others"))
        self.btn_global_l4d1.setText(i18n.tr("btn_l4d1_crew"))
        self.btn_global_l4d2.setText(i18n.tr("btn_l4d2_crew"))
        self.btn_global_clear.setText(i18n.tr("btn_clear"))
        self.apply_all_btn.setText(i18n.tr("batch_btn_apply_all"))
        update_help_badge(self.help_apply_all, i18n.tr("batch_help_apply_all"))
        self.global_quick_panel.sync_height(max(620, self.global_quick_panel.width()))
        self.global_crews_panel.retranslate_ui(i18n)
        self.item_crews_panel.retranslate_ui(i18n)

        self.lbl_global_name.setText(i18n.tr("batch_global_name_tpl"))
        self.global_name_edit.setPlaceholderText(i18n.tr("meta_output_placeholder"))
        self.lbl_global_title.setText(i18n.tr("batch_global_title_tpl"))
        self.global_title_edit.setPlaceholderText(i18n.tr("meta_title_placeholder"))
        self.global_tags_bar.retranslate_ui(i18n)
        self.item_tags_bar.retranslate_ui(i18n)
        self._refresh_global_template_preview()
        self.lbl_global_opts.setText(i18n.tr("meta_options"))
        self.global_options_group.retranslate_ui(i18n)
        self.item_options_group.retranslate_ui(i18n)

        set_table_headers_with_icons(
            self.queue_table,
            [
                (FluentIcon.PHOTO, i18n.tr("batch_col_preview")),
                (FluentIcon.TAG, i18n.tr("batch_col_mod")),
                (FluentIcon.PEOPLE, i18n.tr("batch_col_origin")),
                (FluentIcon.SYNC, i18n.tr("batch_col_dests")),
                (FluentIcon.INFO, i18n.tr("batch_col_status")),
            ],
        )

        self.detail_title_label.setText(i18n.tr("batch_detail_title"))
        self.detail_empty_label.setText(i18n.tr("batch_detail_empty"))
        self.lbl_item_origin.setText(i18n.tr("origin_label"))
        self.item_origin_combo.setItemText(0, i18n.tr("origin_not_selected"))
        self.lbl_item_output.setText(i18n.tr("meta_output_name"))
        self.item_output_edit.setPlaceholderText(i18n.tr("meta_output_placeholder"))
        self.lbl_item_title.setText(i18n.tr("meta_addon_title"))
        self.item_title_edit.setPlaceholderText(i18n.tr("meta_title_placeholder"))
        self.lbl_item_author.setText(i18n.tr("meta_author"))
        self.lbl_item_version.setText(i18n.tr("meta_version"))
        self.lbl_item_desc.setText(i18n.tr("meta_description"))
        self.item_choose_cover_btn.setText(i18n.tr("cover_btn_browse"))
        self.item_reset_cover_btn.setText(i18n.tr("cover_btn_reset"))
        update_checkbox_help(
            self.use_global_dests_chk,
            self.item_help_global_dests,
            i18n.tr("batch_chk_use_global_dests"),
            i18n.tr("batch_help_use_global_dests"),
        )
        update_checkbox_help(
            self.use_global_opts_chk,
            self.item_help_global_opts,
            i18n.tr("batch_chk_use_global_opts"),
            i18n.tr("batch_help_use_global_opts"),
        )

        self.cancel_btn.setText(i18n.tr("batch_btn_cancel"))
        self.open_out_btn.setText(i18n.tr("btn_open_output"))
        self.launch_l4d2_btn.setText(i18n.tr("btn_launch_l4d2"))
        self.progress_card.retranslate_ui(i18n)

        self._apply_panel_styles(drag_active=False)
        self._rebuild_table()
        self._refresh_global_template_preview()
        sel_item = self._selected_item()
        if sel_item is not None:
            self._refresh_item_template_preview(sel_item)
        self._update_queue_action_states()
        L4d2ThemeManager.apply_label_colors(self)
        L4d2ThemeManager.apply_pointing_hand_cursors(self)
