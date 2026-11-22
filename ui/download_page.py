from __future__ import annotations

import os
from pathlib import Path
import re
from typing import Callable, Optional

from PySide6.QtCore import QEvent, QObject, QSize, QThread, QTimer, QUrl, Qt, Signal
from PySide6.QtGui import QColor, QDesktopServices, QPainter, QPixmap
from PySide6.QtWidgets import (
    QApplication,
    QFrame,
    QGridLayout,
    QHBoxLayout,
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
    FlowLayout,
    FluentIcon,
    HeaderCardWidget,
    IconWidget,
    InfoBar,
    InfoBarPosition,
    MessageBox,
    PlainTextEdit,
    PrimaryPushButton,
    ProgressBar,
    PushButton,
    ScrollArea,
    StrongBodyLabel,
    SubtitleLabel,
    Theme,
    TitleLabel,
    isDarkTheme,
)

from core.addons_scanner import AddonsScanner
from core.config_manager import ConfigManager
from core.i18n import LocalizationManager
from core.models import AppConfig, EnvironmentStatus, InstalledAddonEntry, SurvivorId
from core.steam_bbcode import extract_steam_summary
from core.survivors import SurvivorRegistry
from core.workshop_downloader import (
    STEAM_WORKSHOP_ITEM_URL,
    WorkshopDownloadResult,
    WorkshopItemDetails,
    build_safe_vpk_filename,
    extract_workshop_item_ids,
    format_bytes,
    format_count,
    format_timestamp,
)
from ui.addon_ui_shared import (
    create_icon_row,
    create_preview_zoom_button,
    create_styled_mod_table,
    create_table_thumb_cell,
    install_vpks_with_conflict_check,
    set_table_headers_with_icons,
    shutdown_worker_thread,
)
from ui.addons_browser_dialog import AddonConflictDialog
from ui.theme import COLORS, L4d2ThemeManager
from ui.widgets import (
    ClickableImageLabel,
    FlowPanel as _FlowPanel,
    ImageZoomDialog,
    add_card_header_icon,
    bind_preview_media,
    clear_preview_media,
    create_help_badge,
    draw_person_glyph,
    survivor_gender,
    update_help_badge,
    wrap_tooltip_text,
)
from ui.workshop_description_dialog import WorkshopDescriptionDialog
from ui.workshop_download_dialog import WorkshopDownloadWorker, WorkshopFetchWorker


_WORKSHOP_ID_PREFIX_RE = re.compile(r"^(\d{5,15})(?:_|\.|$)")


class _ClickableCaptionLabel(CaptionLabel):
    """CaptionLabel emitting clicked on left-button press for opening full description modals."""

    clicked = Signal()

    def mousePressEvent(self, event) -> None:
        if event.button() == Qt.MouseButton.LeftButton:
            self.clicked.emit()
        super().mousePressEvent(event)
        event.ignore()


class _InlinePersonGlyph(QWidget):
    """Paints the shared vector survivor gender icon inside metadata pills."""

    def __init__(self, female: bool, color: QColor, size: int = 13, parent: Optional[QWidget] = None) -> None:
        super().__init__(parent)
        self._female = female
        self._color = QColor(color)
        self._size = size
        self.setFixedSize(size, size)

    def paintEvent(self, _event) -> None:
        painter = QPainter(self)
        painter.setRenderHint(QPainter.RenderHint.Antialiasing)
        draw_person_glyph(painter, 0.0, 0.0, float(self._size), self._color, female=self._female)


class _NotSkinClickFilter(QObject):
    """Detects clicks on help badge, disabled convert buttons, or the summary description box."""

    def __init__(self, page: WorkshopDownloadPage) -> None:
        super().__init__(page)
        self._page = page

    def eventFilter(self, obj, event) -> bool:
        if event.type() == QEvent.Type.MouseButtonRelease and event.button() == Qt.MouseButton.LeftButton:
            if obj is self._page.desc_box:
                pos = event.position().toPoint()
                if (
                    not self._page.item_desc_label.geometry().contains(pos)
                    and not self._page.full_desc_btn.geometry().contains(pos)
                    and self._page.item_desc_label.text().strip()
                ):
                    self._page._on_open_full_description()
                    return True
            if self._page._is_non_survivor_vpk:
                if obj is self._page.not_skin_badge:
                    self._page._show_not_survivor_popup()
                    return True
                if obj is self._page.actions_host:
                    pos = event.position().toPoint()
                    if (
                        self._page.send_swap_btn.geometry().contains(pos)
                        or self._page.send_batch_btn.geometry().contains(pos)
                    ):
                        self._page._show_not_survivor_popup()
                        return True
        return False


class WorkshopDownloadPage(ScrollArea):
    """Dedicated Steam Workshop download hub with metadata inspector and Workshop_Downloads library."""

    sendToSwapRequested = Signal(Path)
    sendToBatchRequested = Signal(object)
    addonsChanged = Signal()

    def __init__(
        self,
        config_mgr: ConfigManager,
        get_config_fn: Callable[[], AppConfig],
        get_env_fn: Callable[[], EnvironmentStatus],
        i18n: Optional[LocalizationManager] = None,
        parent: Optional[QWidget] = None,
    ) -> None:
        super().__init__(parent)
        self.setObjectName("workshopDownloadPage")
        self.config_mgr = config_mgr
        self._get_config = get_config_fn
        self._get_env = get_env_fn
        self._i18n = i18n or LocalizationManager("en-US")

        self._fetch_thread: Optional[QThread] = None
        self._fetch_worker: Optional[WorkshopFetchWorker] = None
        self._dl_thread: Optional[QThread] = None
        self._dl_worker: Optional[WorkshopDownloadWorker] = None
        self._busy = False

        self._prefetched_details: dict[str, WorkshopItemDetails] = {}
        self._prefetched_previews: dict[str, bytes] = {}
        self._local_entries: list[InstalledAddonEntry] = []
        self._local_previews: dict[Path, bytes] = {}
        self._active_details: Optional[WorkshopItemDetails] = None
        self._active_vpk_path: Optional[Path] = None
        self._active_workshop_id: str = ""
        self._active_cover_pixmap: Optional[QPixmap] = None
        self._active_cover_bytes: Optional[bytes] = None
        self._is_non_survivor_vpk: bool = False
        self._last_status_key: str = "dl_status_idle"
        self._last_status_kwargs: dict = {}

        self.view = QWidget(self)
        self.view.setObjectName("workshopDownloadContainer")
        self.setWidget(self.view)
        self.setWidgetResizable(True)
        self.enableTransparentBackground()

        root = QVBoxLayout(self.view)
        root.setContentsMargins(28, 24, 28, 32)
        root.setSpacing(16)

        self.title_label = TitleLabel("", self.view)
        root.addLayout(create_icon_row(FluentIcon.DOWNLOAD, self.title_label, self.view, size=24, spacing=10))
        self.subtitle_label = CaptionLabel("", self.view)
        self.subtitle_label.setWordWrap(True)
        root.addWidget(self.subtitle_label)

        self.input_card = HeaderCardWidget(self.view)
        add_card_header_icon(self.input_card, FluentIcon.LINK)
        input_inner = QWidget(self.input_card)
        input_lay = QVBoxLayout(input_inner)
        input_lay.setContentsMargins(0, 0, 0, 0)
        input_lay.setSpacing(10)

        self.url_edit = PlainTextEdit(input_inner)
        self.url_edit.setFixedHeight(64)
        input_lay.addWidget(self.url_edit)

        self.input_btns_host = _FlowPanel(h_space=8, v_space=8, parent=input_inner)
        self.paste_btn = PushButton(FluentIcon.PASTE, "", self.input_btns_host)
        self.inspect_btn = PushButton(FluentIcon.SEARCH, "", self.input_btns_host)
        self.download_btn = PrimaryPushButton(FluentIcon.DOWNLOAD, "", self.input_btns_host)
        self.cancel_btn = PushButton(FluentIcon.CLOSE, "", self.input_btns_host)
        self.cancel_btn.setVisible(False)
        self.cancel_btn.setEnabled(False)
        self.open_dir_btn = PushButton(FluentIcon.FOLDER, "", self.input_btns_host)
        for btn in (
            self.paste_btn,
            self.inspect_btn,
            self.download_btn,
            self.cancel_btn,
            self.open_dir_btn,
        ):
            self.input_btns_host.flow.addWidget(btn)
        self.input_btns_host.sync_height(fallback_width=640)
        input_lay.addWidget(self.input_btns_host)

        self.progress_bar = ProgressBar(input_inner)
        self.progress_bar.setRange(0, 100)
        self.progress_bar.setValue(0)
        self.progress_bar.setVisible(False)
        self.status_label = CaptionLabel("", input_inner)
        self.status_label.setWordWrap(True)
        input_lay.addWidget(self.progress_bar)
        input_lay.addWidget(self.status_label)

        self.input_card.viewLayout.addWidget(input_inner)
        root.addWidget(self.input_card)

        self.details_card = HeaderCardWidget(self.view)
        add_card_header_icon(self.details_card, FluentIcon.INFO)
        details_inner = QWidget(self.details_card)
        details_main = QVBoxLayout(details_inner)
        details_main.setContentsMargins(0, 0, 0, 0)
        details_main.setSpacing(12)

        top_split = QHBoxLayout()
        top_split.setSpacing(16)

        self.cover_thumb = ClickableImageLabel(details_inner)
        self.cover_thumb.setFixedSize(216, 136)
        self.cover_thumb.setAlignment(Qt.AlignmentFlag.AlignCenter)
        self.cover_thumb.setWordWrap(True)
        self.cover_thumb.setObjectName("dlCoverThumb")
        self.cover_zoom_btn = create_preview_zoom_button(
            self.cover_thumb,
            tooltip="",
            size=28,
            margin=6,
        )
        self.cover_zoom_btn.setVisible(False)

        right_col = QVBoxLayout()
        right_col.setSpacing(10)
        self.item_title_label = SubtitleLabel("", details_inner)
        self.item_title_label.setWordWrap(True)

        self.pills_host = _FlowPanel(h_space=6, v_space=6, parent=details_inner)
        self.pills_flow = self.pills_host.flow

        self.stats_host = _FlowPanel(h_space=8, v_space=8, parent=details_inner)
        self.stats_row = self.stats_host.flow
        self.stats_host.setVisible(False)

        self.meta_host = QWidget(details_inner)
        self.meta_host.setSizePolicy(QSizePolicy.Policy.Expanding, QSizePolicy.Policy.Minimum)
        self.meta_vbox = QVBoxLayout(self.meta_host)
        self.meta_vbox.setContentsMargins(0, 0, 0, 0)
        self.meta_vbox.setSpacing(4)
        self.meta_host.setVisible(False)

        self.tags_host = QWidget(details_inner)
        self.tags_host.setSizePolicy(QSizePolicy.Policy.Expanding, QSizePolicy.Policy.Minimum)
        tags_outer = QHBoxLayout(self.tags_host)
        tags_outer.setContentsMargins(0, 0, 0, 0)
        tags_outer.setSpacing(8)
        tags_lbl_box = QWidget(self.tags_host)
        tags_lbl_row = QHBoxLayout(tags_lbl_box)
        tags_lbl_row.setContentsMargins(0, 3, 0, 0)
        tags_lbl_row.setSpacing(6)
        self.tags_icon = IconWidget(FluentIcon.TAG, tags_lbl_box)
        self.tags_icon.setFixedSize(13, 13)
        self.tags_key_label = CaptionLabel("", tags_lbl_box)
        tags_lbl_row.addWidget(self.tags_icon, 0, Qt.AlignmentFlag.AlignVCenter)
        tags_lbl_row.addWidget(self.tags_key_label, 0, Qt.AlignmentFlag.AlignVCenter)
        self.tags_chips_host = _FlowPanel(h_space=6, v_space=6, parent=self.tags_host)
        self.tags_flow = self.tags_chips_host.flow
        self.tags_chips_host.heightChanged.connect(self._on_tags_height_changed)
        tags_outer.addWidget(tags_lbl_box, 0, Qt.AlignmentFlag.AlignTop)
        tags_outer.addWidget(self.tags_chips_host, 1)
        self.tags_host.setVisible(False)

        right_col.addWidget(self.item_title_label)
        right_col.addWidget(self.pills_host)
        right_col.addWidget(self.stats_host)
        right_col.addWidget(self.meta_host)
        right_col.addWidget(self.tags_host)
        right_col.addStretch(1)

        top_split.addWidget(self.cover_thumb, 0, Qt.AlignmentFlag.AlignTop)
        top_split.addLayout(right_col, 1)
        details_main.addLayout(top_split)

        self.desc_box = QFrame(details_inner)
        self.desc_box.setObjectName("dlDescBox")
        self.desc_box.setCursor(Qt.CursorShape.PointingHandCursor)
        desc_row = QHBoxLayout(self.desc_box)
        desc_row.setContentsMargins(12, 8, 10, 8)
        desc_row.setSpacing(12)
        self.item_desc_label = _ClickableCaptionLabel("", self.desc_box)
        self.item_desc_label.setWordWrap(True)
        self.full_desc_btn = PushButton(FluentIcon.DOCUMENT, "", self.desc_box)
        desc_row.addWidget(self.item_desc_label, 1, Qt.AlignmentFlag.AlignVCenter)
        desc_row.addWidget(self.full_desc_btn, 0, Qt.AlignmentFlag.AlignVCenter)
        self.desc_box.setVisible(False)
        details_main.addWidget(self.desc_box)

        self.actions_host = _FlowPanel(h_space=8, v_space=8, parent=details_inner)
        actions_row = self.actions_host.flow
        self.send_swap_btn = PrimaryPushButton(FluentIcon.SYNC, "", self.actions_host)
        self.send_batch_btn = PushButton(FluentIcon.LIBRARY, "", self.actions_host)
        self.not_skin_badge = create_help_badge("", self.actions_host)
        self.not_skin_badge.setVisible(False)
        self.install_addons_btn = PushButton(FluentIcon.ZIP_FOLDER, "", self.actions_host)
        self.open_steam_btn = PushButton(FluentIcon.GLOBE, "", self.actions_host)
        for btn in (
            self.send_swap_btn,
            self.send_batch_btn,
            self.install_addons_btn,
            self.open_steam_btn,
        ):
            btn.setEnabled(False)
        actions_row.addWidget(self.send_swap_btn)
        actions_row.addWidget(self.send_batch_btn)
        actions_row.addWidget(self.not_skin_badge)
        actions_row.addWidget(self.install_addons_btn)
        actions_row.addWidget(self.open_steam_btn)
        self.actions_host.sync_height(fallback_width=720)
        self._click_filter = _NotSkinClickFilter(self)
        self.desc_box.installEventFilter(self._click_filter)
        self.not_skin_badge.installEventFilter(self._click_filter)
        self.actions_host.installEventFilter(self._click_filter)
        details_main.addWidget(self.actions_host)

        self.details_card.viewLayout.addWidget(details_inner)
        root.addWidget(self.details_card)

        self.library_card = HeaderCardWidget(self.view)
        add_card_header_icon(self.library_card, FluentIcon.FOLDER)
        lib_inner = QWidget(self.library_card)
        lib_lay = QVBoxLayout(lib_inner)
        lib_lay.setContentsMargins(0, 0, 0, 0)
        lib_lay.setSpacing(10)

        lib_bar = QHBoxLayout()
        lib_bar.setSpacing(8)
        self.refresh_lib_btn = PushButton(FluentIcon.SYNC, "", lib_inner)
        self.delete_lib_btn = PushButton(FluentIcon.DELETE, "", lib_inner)
        self.delete_lib_btn.setEnabled(False)
        lib_bar.addWidget(self.refresh_lib_btn)
        lib_bar.addWidget(self.delete_lib_btn)
        lib_bar.addStretch(1)
        lib_lay.addLayout(lib_bar)

        self.library_table = create_styled_mod_table(lib_inner, ["", "", "", "", ""], min_height=220)
        lib_lay.addWidget(self.library_table)

        self.library_card.viewLayout.addWidget(lib_inner)
        root.addWidget(self.library_card)

        self.paste_btn.clicked.connect(self._on_paste)
        self.inspect_btn.clicked.connect(self._on_inspect)
        self.download_btn.clicked.connect(self._on_download)
        self.cancel_btn.clicked.connect(self._on_cancel)
        self.open_dir_btn.clicked.connect(self._on_open_download_dir)
        self.cover_thumb.clicked.connect(self._on_zoom_cover)
        self.cover_zoom_btn.clicked.connect(self._on_zoom_cover)
        self.item_desc_label.clicked.connect(self._on_open_full_description)
        self.full_desc_btn.clicked.connect(self._on_open_full_description)
        self.send_swap_btn.clicked.connect(self._on_send_to_swap)
        self.send_batch_btn.clicked.connect(self._on_send_to_batch)
        self.install_addons_btn.clicked.connect(self._on_install_to_addons)
        self.open_steam_btn.clicked.connect(self._on_open_steam_page)
        self.refresh_lib_btn.clicked.connect(self.refresh_library)
        self.delete_lib_btn.clicked.connect(self._on_delete_selected)
        self.library_table.itemSelectionChanged.connect(self._on_library_selection_changed)

        self.retranslate_ui(self._i18n)
        self.refresh_library()

    def _download_dir(self) -> Path:
        configured = self._get_config().workshop_download_dir or "Workshop_Downloads"
        return self.config_mgr.resolve_path(configured)

    def _set_status(self, key: str, **kwargs) -> None:
        self._last_status_key = key
        self._last_status_kwargs = dict(kwargs)
        self.status_label.setText(self._i18n.tr(key, **kwargs))

    def retranslate_ui(self, i18n: LocalizationManager) -> None:
        self._i18n = i18n
        self.title_label.setText(i18n.tr("nav_download"))
        self.subtitle_label.setText(i18n.tr("dl_page_subtitle"))
        self.input_card.setTitle(i18n.tr("dl_card_input_title"))
        self.url_edit.setPlaceholderText(i18n.tr("dl_input_placeholder"))
        self.paste_btn.setText(i18n.tr("dl_btn_paste"))
        self.inspect_btn.setText(i18n.tr("dl_btn_inspect"))
        self.download_btn.setText(i18n.tr("dl_btn_download"))
        self.cancel_btn.setText(i18n.tr("dl_btn_cancel"))
        self.open_dir_btn.setText(i18n.tr("dl_btn_open_dir"))

        self.details_card.setTitle(i18n.tr("dl_card_details_title"))
        self.cover_zoom_btn.setToolTip(i18n.tr("addons_dlg_zoom_tip"))
        self.tags_key_label.setText(f"{i18n.tr('dl_lbl_tags')}:")
        self.full_desc_btn.setText(i18n.tr("dl_btn_full_desc"))
        update_help_badge(self.not_skin_badge, i18n.tr("dl_not_skin_msg"))
        self.send_swap_btn.setText(i18n.tr("dl_btn_send_swap"))
        self.send_batch_btn.setText(i18n.tr("dl_btn_send_batch"))
        self.install_addons_btn.setText(i18n.tr("dl_btn_install_addons"))
        self.open_steam_btn.setText(i18n.tr("dl_btn_open_steam"))

        self.library_card.setTitle(i18n.tr("dl_card_library_title"))
        self.refresh_lib_btn.setText(i18n.tr("dl_btn_refresh_lib"))
        self.delete_lib_btn.setText(i18n.tr("dl_btn_delete_lib"))

        set_table_headers_with_icons(
            self.library_table,
            [
                (FluentIcon.PHOTO, i18n.tr("dl_col_preview")),
                (FluentIcon.LINK, i18n.tr("dl_col_id")),
                (FluentIcon.PEOPLE, i18n.tr("dl_col_survivor")),
                (FluentIcon.TAG, i18n.tr("dl_col_mod")),
                (FluentIcon.INFO, i18n.tr("dl_col_size")),
            ],
        )
        if not self._busy:
            self.status_label.setText(i18n.tr(self._last_status_key, **self._last_status_kwargs))
        self._apply_details_styles()
        self._render_active_details()
        self.refresh_library()
        L4d2ThemeManager.apply_pointing_hand_cursors(self)

    def _apply_details_styles(self) -> None:
        is_dark = isDarkTheme()
        border = COLORS.dark_border if is_dark else COLORS.light_border
        muted = COLORS.dark_muted if is_dark else COLORS.light_muted
        L4d2ThemeManager.install_surface_motion(
            self.cover_thumb,
            f"QLabel#dlCoverThumb {{ background-color: {{bg}}; border: 1px solid {{border}}; "
            f"border-radius: 6px; color: {muted}; padding: 4px; }}",
            custom_colors=L4d2ThemeManager.image_surface_palette(is_dark),
            border_colors=L4d2ThemeManager.image_border_colors(is_dark),
        )
        self.status_label.setStyleSheet(f"color: {muted}; font-size: 12px;")
        self.item_desc_label.setStyleSheet(f"color: {muted}; font-size: 12px;")
        self.tags_key_label.setStyleSheet(f"color: {muted}; font-size: 11px; font-weight: 600;")
        L4d2ThemeManager.install_surface_motion(
            self.desc_box,
            f"QFrame#dlDescBox {{ background-color: {{bg}}; border: 1px solid {border}; border-radius: 6px; }}",
            tone="neutral",
        )

    def _set_busy(self, busy: bool) -> None:
        self._busy = busy
        self.url_edit.setEnabled(not busy)
        self.paste_btn.setEnabled(not busy)
        self.inspect_btn.setEnabled(not busy)
        self.download_btn.setEnabled(not busy)
        self.cancel_btn.setVisible(busy)
        self.cancel_btn.setEnabled(busy)
        self.input_btns_host.sync_height(fallback_width=max(560, self.input_card.width() - 60))
        L4d2ThemeManager.apply_pointing_hand_cursors(self)

    def _parse_ids(self) -> Optional[list[str]]:
        ids = extract_workshop_item_ids(self.url_edit.toPlainText())
        if not ids:
            InfoBar.warning(
                self._i18n.tr("dl_err_title"),
                self._i18n.tr("dl_err_invalid_id"),
                parent=self.window(),
                position=InfoBarPosition.TOP,
            )
            return None
        return ids

    def _on_paste(self) -> None:
        clipboard = QApplication.clipboard()
        if clipboard is not None and clipboard.text().strip():
            self.url_edit.setPlainText(clipboard.text().strip())

    def _on_inspect(self) -> None:
        if self._busy:
            return
        ids = self._parse_ids()
        if not ids:
            return
        self._set_busy(True)
        self.progress_bar.setVisible(False)
        self._set_status("dl_status_fetching")

        self._fetch_thread = QThread(self)
        self._fetch_worker = WorkshopFetchWorker(ids)
        self._fetch_worker.moveToThread(self._fetch_thread)
        self._fetch_thread.started.connect(self._fetch_worker.run)
        self._fetch_worker.fetched.connect(self._on_fetched)
        self._fetch_worker.failed.connect(self._on_worker_failed)
        self._fetch_worker.done.connect(self._fetch_thread.quit)
        self._fetch_thread.finished.connect(self._cleanup_fetch_thread)
        self._fetch_thread.start()

    def _on_download(self) -> None:
        if self._busy:
            return
        ids = self._parse_ids()
        if not ids:
            return
        self._set_busy(True)
        self.progress_bar.setVisible(True)
        self.progress_bar.setValue(0)
        self._set_status("dl_status_fetching")

        self._dl_thread = QThread(self)
        self._dl_worker = WorkshopDownloadWorker(
            item_ids=ids,
            target_dir=self._download_dir(),
            addons_dir=self._get_env().l4d2_addons_dir,
            prefetched_details=self._prefetched_details,
            prefetched_previews=self._prefetched_previews,
        )
        self._dl_worker.moveToThread(self._dl_thread)
        self._dl_thread.started.connect(self._dl_worker.run)
        self._dl_worker.progressUpdated.connect(self._on_download_progress)
        self._dl_worker.completed.connect(self._on_download_completed)
        self._dl_worker.failed.connect(self._on_worker_failed)
        self._dl_worker.completed.connect(self._dl_thread.quit)
        self._dl_worker.failed.connect(self._dl_thread.quit)
        self._dl_thread.finished.connect(self._cleanup_dl_thread)
        self._dl_thread.start()

    def _on_cancel(self) -> None:
        if self._dl_worker is not None:
            self._dl_worker.request_cancel()
            self.cancel_btn.setEnabled(False)

    def _cleanup_fetch_thread(self) -> None:
        if self._fetch_worker is not None:
            self._fetch_worker.deleteLater()
            self._fetch_worker = None
        if self._fetch_thread is not None:
            self._fetch_thread.deleteLater()
            self._fetch_thread = None

    def _cleanup_dl_thread(self) -> None:
        if self._dl_worker is not None:
            self._dl_worker.deleteLater()
            self._dl_worker = None
        if self._dl_thread is not None:
            self._dl_thread.deleteLater()
            self._dl_thread = None

    def _on_fetched(self, pairs: list[tuple[WorkshopItemDetails, Optional[bytes]]]) -> None:
        self._set_busy(False)
        for item, preview in pairs:
            self._prefetched_details[item.published_file_id] = item
            if preview is not None:
                self._prefetched_previews[item.published_file_id] = preview

        first_item, _ = pairs[0]
        self._active_details = first_item
        self._active_workshop_id = first_item.published_file_id
        candidate = self._download_dir() / build_safe_vpk_filename(
            first_item.published_file_id,
            first_item.filename,
            first_item.title,
        )
        self._active_vpk_path = candidate if candidate.is_file() else None
        if self._active_vpk_path is not None:
            self._set_status("dl_status_cached")
        elif first_item.has_direct_url:
            self._set_status("dl_status_ready")
        else:
            self._set_status("dl_status_no_direct")
        self._render_active_details()

    def _on_download_progress(
        self, index: int, total: int, title: str, done_bytes: int, total_bytes: int
    ) -> None:
        pct = int((done_bytes / total_bytes) * 100) if total_bytes > 0 else 0
        self.progress_bar.setValue(max(0, min(100, pct)))
        self.status_label.setText(
            self._i18n.tr(
                "dl_status_downloading",
                index=index,
                total=total,
                title=title,
                done=format_bytes(done_bytes),
                size=format_bytes(total_bytes) if total_bytes > 0 else "?",
            )
        )

    def _on_download_completed(self, results: list[WorkshopDownloadResult]) -> None:
        self._set_busy(False)
        self.progress_bar.setValue(100)
        for res in results:
            self._prefetched_details[res.details.published_file_id] = res.details
            if res.preview_bytes is not None:
                self._prefetched_previews[res.details.published_file_id] = res.preview_bytes

        first = results[0]
        self._active_details = first.details
        self._active_vpk_path = first.vpk_path
        self._active_workshop_id = first.details.published_file_id
        if len(results) == 1:
            self._set_status("dl_status_cached" if first.already_cached else "dl_status_done_one")
        else:
            self._set_status("dl_status_done_many", count=len(results))

        self.refresh_library(select_path=first.vpk_path)
        self._render_active_details()

    def _on_worker_failed(self, key: str, kwargs: dict) -> None:
        self._set_busy(False)
        self.progress_bar.setVisible(False)
        self._set_status(key, **(kwargs or {}))
        if key != "dl_err_cancelled":
            InfoBar.error(
                self._i18n.tr("dl_err_title"),
                self._i18n.tr(key, **(kwargs or {})),
                parent=self.window(),
                position=InfoBarPosition.TOP,
                duration=6000,
            )

    @staticmethod
    def _clear_layout_widgets(layout) -> None:
        while layout.count():
            item = layout.takeAt(0)
            w = item if isinstance(item, QWidget) else (item.widget() if item is not None else None)
            if w is not None:
                w.hide()
                w.setParent(None)
                w.deleteLater()

    def _add_pill(
        self,
        text: str,
        bg: str,
        border: str,
        fg: str,
        survivor_id: Optional[SurvivorId] = None,
    ) -> None:
        pill = QFrame(self.pills_host)
        pill.setObjectName("dlMetaPill")
        tone = "amber" if bg.lower() in {"#201c12", "#fdeca8"} else "neutral"
        L4d2ThemeManager.install_surface_motion(
            pill,
            f"QFrame#dlMetaPill {{ background-color: {{bg}}; border: 1px solid {border}; border-radius: 5px; }}",
            tone=tone,
        )
        row = QHBoxLayout(pill)
        row.setContentsMargins(8, 3, 9, 3)
        row.setSpacing(5)
        if survivor_id is not None:
            row.addWidget(
                _InlinePersonGlyph(
                    female=(survivor_gender(survivor_id) == "female"),
                    color=QColor(fg),
                    size=13,
                    parent=pill,
                )
            )
        lbl = QLabel(text, pill)
        lbl.setStyleSheet(
            f"QLabel {{ color: {fg}; font-size: 11px; font-weight: 700; border: none; background: transparent; }}"
        )
        row.addWidget(lbl)
        pill.show()
        self.pills_flow.addWidget(pill)

    def _add_stat_tile(
        self,
        icon: FluentIcon,
        value_text: str,
        caption_text: str,
        bg: str,
        border: str,
        fg: str,
        muted: str,
    ) -> None:
        tile = QFrame(self.stats_host)
        tile.setObjectName("dlStatTile")
        L4d2ThemeManager.install_surface_motion(
            tile,
            f"QFrame#dlStatTile {{ background-color: {{bg}}; border: 1px solid {border}; border-radius: 6px; }}",
            tone="neutral",
        )
        col = QVBoxLayout(tile)
        col.setContentsMargins(10, 6, 12, 6)
        col.setSpacing(2)

        top = QHBoxLayout()
        top.setContentsMargins(0, 0, 0, 0)
        top.setSpacing(6)
        ic = IconWidget(icon, tile)
        ic.setFixedSize(13, 13)
        val_lbl = StrongBodyLabel(value_text, tile)
        val_lbl.setStyleSheet(f"color: {fg}; font-size: 13px; font-weight: 700; border: none; background: transparent;")
        top.addWidget(ic, 0, Qt.AlignmentFlag.AlignVCenter)
        top.addWidget(val_lbl, 0, Qt.AlignmentFlag.AlignVCenter)
        top.addStretch(1)

        cap_lbl = CaptionLabel(caption_text, tile)
        cap_lbl.setStyleSheet(f"color: {muted}; font-size: 11px; border: none; background: transparent;")
        col.addLayout(top)
        col.addWidget(cap_lbl)
        tile.show()
        self.stats_row.addWidget(tile)

    def _add_meta_row(
        self,
        icon: FluentIcon,
        key_text: str,
        value_text: str,
        fg: str,
        muted: str,
    ) -> None:
        row_w = QWidget(self.meta_host)
        row_w.setMinimumHeight(20)
        row = QHBoxLayout(row_w)
        row.setContentsMargins(0, 0, 0, 0)
        row.setSpacing(8)
        ic = IconWidget(icon, row_w)
        ic.setFixedSize(13, 13)
        k_lbl = CaptionLabel(f"{key_text}:", row_w)
        k_lbl.setMinimumWidth(68)
        k_lbl.setStyleSheet(f"color: {muted}; font-size: 12px; font-weight: 600;")
        v_lbl = BodyLabel(value_text, row_w)
        v_lbl.setWordWrap(True)
        v_lbl.setTextInteractionFlags(Qt.TextInteractionFlag.TextSelectableByMouse)
        v_lbl.setStyleSheet(f"color: {fg}; font-size: 12px;")
        row.addWidget(ic, 0, Qt.AlignmentFlag.AlignVCenter)
        row.addWidget(k_lbl, 0, Qt.AlignmentFlag.AlignVCenter)
        row.addWidget(v_lbl, 1, Qt.AlignmentFlag.AlignVCenter)
        self.meta_vbox.addWidget(row_w)

    def _add_tag_chip(self, tag_text: str, bg: str, border: str, muted: str) -> None:
        chip = QLabel(tag_text, self.tags_chips_host)
        chip.setObjectName("dlTagChip")
        L4d2ThemeManager.install_surface_motion(
            chip,
            f"QLabel#dlTagChip {{ background-color: {{bg}}; border: 1px solid {border}; border-radius: 4px; "
            f"color: {muted}; font-size: 11px; padding: 2px 7px; }}",
            tone="neutral",
        )
        chip.show()
        self.tags_flow.addWidget(chip)

    def _on_tags_height_changed(self, h: int) -> None:
        if self.tags_host.isVisible():
            self.tags_host.setMinimumHeight(max(22, h))
            self.tags_host.updateGeometry()

    def _resync_flow_panels(self) -> None:
        card_w = max(480, self.details_card.width() - 280)
        self.input_btns_host.sync_height(fallback_width=max(520, self.input_card.width() - 60))
        self.pills_host.sync_height(fallback_width=card_w)
        if self.stats_host.isVisible():
            self.stats_host.sync_height(fallback_width=card_w)
        if self.tags_host.isVisible():
            h = self.tags_chips_host.sync_height(fallback_width=max(420, card_w - 60))
            self.tags_host.setMinimumHeight(max(22, h))
            self.tags_host.updateGeometry()
        self.actions_host.sync_height(fallback_width=max(520, self.details_card.width() - 60))

    def _render_active_details(self) -> None:
        self._clear_layout_widgets(self.pills_flow)
        self._clear_layout_widgets(self.stats_row)
        self._clear_layout_widgets(self.meta_vbox)
        self._clear_layout_widgets(self.tags_flow)
        details = self._active_details
        vpk_path = self._active_vpk_path if self._active_vpk_path and self._active_vpk_path.is_file() else None
        local_entry: Optional[InstalledAddonEntry] = None
        if vpk_path is not None:
            for entry in self._local_entries:
                if entry.vpk_path == vpk_path:
                    local_entry = entry
                    break
            if local_entry is None:
                local_entry = AddonsScanner._inspect_vpk_fast(
                    vpk_path,
                    "workshop",
                    vpk_path.parent,
                    {},
                    allow_non_survivor=True,
                )

        is_dark = isDarkTheme()
        text_fg = COLORS.dark_text if is_dark else COLORS.light_text
        muted_fg = COLORS.dark_muted if is_dark else COLORS.light_muted
        border_fg = COLORS.dark_border if is_dark else COLORS.light_border
        alt_bg = COLORS.dark_card_alt if is_dark else COLORS.light_card_alt
        amber_border = COLORS.amber if is_dark else "#9E7000"
        amber_fg = COLORS.amber_bright if is_dark else "#111315"
        amber_bg = "#201C12" if is_dark else "#FDECA8"

        if details is None and local_entry is None:
            self.item_title_label.setText(self._i18n.tr("dl_status_idle"))
            self.stats_host.setVisible(False)
            self.meta_host.setVisible(False)
            self.tags_host.setVisible(False)
            self.desc_box.setVisible(False)
            self.item_desc_label.setText("")
            self.item_desc_label.setCursor(Qt.CursorShape.ArrowCursor)
            self.not_skin_badge.setVisible(False)
            self._is_non_survivor_vpk = False
            self.send_swap_btn.setToolTip("")
            self.send_batch_btn.setToolTip("")
            clear_preview_media(self.cover_thumb)
            self.cover_thumb.setPixmap(QPixmap())
            self.cover_thumb.setText(self._i18n.tr("confirm_dlg_no_cover"))
            self.cover_thumb.setCursor(Qt.CursorShape.ArrowCursor)
            self.cover_zoom_btn.setVisible(False)
            self._active_cover_pixmap = None
            self._active_cover_bytes = None
            for btn in (self.send_swap_btn, self.send_batch_btn, self.install_addons_btn, self.open_steam_btn):
                btn.setEnabled(False)
            return

        sep = "," if self._i18n.active_language == "en-US" else "."
        wid = (details.published_file_id if details else "") or self._active_workshop_id
        title = (details.title if details else "") or (local_entry.title if local_entry else vpk_path.stem)
        self.item_title_label.setText(title)

        if wid:
            self._add_pill(self._i18n.tr("dl_meta_id", id=wid), alt_bg, border_fg, text_fg)
        self._add_pill(self._i18n.tr("dl_meta_app"), alt_bg, border_fg, text_fg)
        if details is not None and details.rating_stars is not None:
            if details.rating_stars > 0:
                stars_txt = ("★" * details.rating_stars) + ("☆" * (5 - details.rating_stars))
                self._add_pill(
                    self._i18n.tr(
                        "dl_meta_stars",
                        stars=stars_txt,
                        score=details.rating_stars,
                        count=format_count(details.num_ratings, sep),
                    ),
                    amber_bg,
                    amber_border,
                    amber_fg,
                )
            else:
                self._add_pill(
                    self._i18n.tr("dl_meta_stars_none"),
                    alt_bg,
                    border_fg,
                    text_fg,
                )
        if vpk_path is not None:
            self._add_pill(self._i18n.tr("dl_status_col_ready"), amber_bg, amber_border, amber_fg)
        if local_entry is not None and local_entry.origin is not None:
            spec = SurvivorRegistry.get(local_entry.origin)
            self._add_pill(
                f"{spec.display_name} ({spec.generation})",
                alt_bg,
                border_fg,
                text_fg,
                survivor_id=spec.id,
            )
        else:
            kind_key = AddonsScanner.detect_non_survivor_kind(
                vpk_path=vpk_path,
                tags=details.tags if details is not None else (),
            )
            if kind_key:
                self._add_pill(self._i18n.tr(kind_key), alt_bg, border_fg, text_fg)

        size_val = details.file_size if details and details.file_size > 0 else (
            vpk_path.stat().st_size if vpk_path is not None else 0
        )
        has_community_stats = details is not None and (
            details.subscriptions > 0 or details.favorited > 0 or details.views > 0
        )
        if has_community_stats:
            subs_caption = self._i18n.tr("dl_stat_subs")
            if details.lifetime_subscriptions > details.subscriptions:
                subs_caption = (
                    f"{subs_caption} \u00b7 "
                    + self._i18n.tr("dl_stat_total_sub", total=format_count(details.lifetime_subscriptions, sep))
                )
            self._add_stat_tile(
                FluentIcon.PEOPLE,
                format_count(details.subscriptions, sep),
                subs_caption,
                alt_bg,
                border_fg,
                text_fg,
                muted_fg,
            )
            self._add_stat_tile(
                FluentIcon.HEART,
                format_count(details.favorited, sep),
                self._i18n.tr("dl_stat_favs"),
                alt_bg,
                border_fg,
                text_fg,
                muted_fg,
            )
            self._add_stat_tile(
                FluentIcon.VIEW,
                format_count(details.views, sep),
                self._i18n.tr("dl_stat_views"),
                alt_bg,
                border_fg,
                text_fg,
                muted_fg,
            )
        if size_val > 0:
            self._add_stat_tile(
                FluentIcon.SAVE,
                format_bytes(size_val),
                self._i18n.tr("dl_stat_size"),
                alt_bg,
                border_fg,
                text_fg,
                muted_fg,
            )
        has_stats_tiles = self.stats_row.count() > 0
        if has_stats_tiles:
            self.stats_host.setVisible(True)
            self.stats_host.sync_height(fallback_width=max(480, self.details_card.width() - 280))
        else:
            self.stats_host.setMinimumHeight(0)
            self.stats_host.setVisible(False)

        meta_count = 0
        author_val = (details.creator_name if details else "") or (local_entry.author if local_entry else "")
        if author_val:
            self._add_meta_row(FluentIcon.EDIT, self._i18n.tr("dl_lbl_author"), author_val, text_fg, muted_fg)
            meta_count += 1

        file_val = ""
        if details is not None and vpk_path is not None:
            file_val = f"{details.filename or vpk_path.name}  \u2192  {vpk_path.name}"
        elif details is not None:
            saved_name = build_safe_vpk_filename(details.published_file_id, details.filename, details.title)
            file_val = f"{details.filename or saved_name}  \u2192  {saved_name}"
        elif vpk_path is not None:
            file_val = vpk_path.name
        if file_val:
            self._add_meta_row(FluentIcon.FOLDER, self._i18n.tr("dl_lbl_files"), file_val, text_fg, muted_fg)
            meta_count += 1

        date_parts: list[str] = []
        if details is not None and details.time_created > 0:
            date_parts.append(
                self._i18n.tr(
                    "dl_meta_created",
                    date=format_timestamp(details.time_created, self._i18n.active_language),
                )
            )
        if details is not None and details.time_updated > 0:
            date_parts.append(
                self._i18n.tr(
                    "dl_meta_updated",
                    date=format_timestamp(details.time_updated, self._i18n.active_language),
                )
            )
        if date_parts:
            self._add_meta_row(
                FluentIcon.CALENDAR,
                self._i18n.tr("dl_lbl_dates"),
                "   \u2022   ".join(date_parts),
                text_fg,
                muted_fg,
            )
            meta_count += 1
        self.meta_host.setMinimumHeight(meta_count * 22 if meta_count > 0 else 0)
        self.meta_host.setVisible(meta_count > 0)

        est_pills_w = max(560, self.details_card.width() - 280)
        self.pills_host.sync_height(fallback_width=est_pills_w)

        if details is not None and details.tags:
            for tag_txt in details.tags:
                self._add_tag_chip(tag_txt, alt_bg, border_fg, muted_fg)
            self.tags_host.setMinimumHeight(0)
            self.tags_host.setVisible(True)
            self.tags_chips_host.sync_height(fallback_width=max(520, est_pills_w - 60))
            self.tags_host.updateGeometry()
            QTimer.singleShot(0, self._resync_flow_panels)
        else:
            self.tags_host.setMinimumHeight(0)
            self.tags_host.setVisible(False)

        raw_desc = details.description if details is not None else ""
        has_desc = bool(raw_desc and raw_desc.strip())
        summary_txt = extract_steam_summary(raw_desc, title=title, max_len=240) if has_desc else ""
        self.item_desc_label.setText(summary_txt)
        self.item_desc_label.setCursor(
            Qt.CursorShape.PointingHandCursor if has_desc else Qt.CursorShape.ArrowCursor
        )
        self.desc_box.setVisible(has_desc)

        raw_img: Optional[bytes] = None
        if wid and wid in self._prefetched_previews:
            raw_img = self._prefetched_previews[wid]
        elif local_entry is not None and local_entry.preview_bytes:
            raw_img = local_entry.preview_bytes
        elif vpk_path is not None:
            raw_img = self._local_previews.get(vpk_path)

        pix = bind_preview_media(self.cover_thumb, raw_img, 208, 128)
        if pix is not None:
            self._active_cover_pixmap = pix
            self._active_cover_bytes = raw_img
            self.cover_thumb.setText("")
            self.cover_thumb.setCursor(Qt.CursorShape.PointingHandCursor)
            self.cover_thumb.setToolTip(self._i18n.tr("addons_dlg_zoom_tip"))
            self.cover_zoom_btn.setVisible(True)
        else:
            clear_preview_media(self.cover_thumb)
            self._active_cover_pixmap = None
            self._active_cover_bytes = None
            self.cover_thumb.setPixmap(QPixmap())
            self.cover_thumb.setText(self._i18n.tr("confirm_dlg_no_cover"))
            self.cover_thumb.setCursor(Qt.CursorShape.ArrowCursor)
            self.cover_thumb.setToolTip("")
            self.cover_zoom_btn.setVisible(False)

        has_file = vpk_path is not None
        is_non_skin = has_file and local_entry is not None and local_entry.origin is None
        is_survivor_skin = has_file and not is_non_skin
        self._is_non_survivor_vpk = is_non_skin
        self.send_swap_btn.setEnabled(is_survivor_skin)
        self.send_batch_btn.setEnabled(is_survivor_skin)
        self.not_skin_badge.setVisible(is_non_skin)
        tip = wrap_tooltip_text(self._i18n.tr("dl_not_skin_tip")) if is_non_skin else ""
        self.send_swap_btn.setToolTip(tip)
        self.send_batch_btn.setToolTip(tip)
        self.install_addons_btn.setEnabled(has_file)
        self.open_steam_btn.setEnabled(bool(wid))
        self._resync_flow_panels()
        QTimer.singleShot(0, self._resync_flow_panels)
        L4d2ThemeManager.apply_pointing_hand_cursors(self)

    def refresh_library(self, select_path: Optional[Path] = None) -> None:
        dl_dir = self._download_dir()
        entries: list[InstalledAddonEntry] = []
        previews: dict[Path, bytes] = {}

        if dl_dir.is_dir():
            for vpk_path in sorted(dl_dir.glob("*.vpk"), key=lambda p: p.stat().st_mtime, reverse=True):
                entry = AddonsScanner._inspect_vpk_fast(
                    vpk_path,
                    "workshop",
                    dl_dir,
                    {},
                    allow_non_survivor=True,
                )
                if entry is not None:
                    entries.append(entry)
                    if entry.preview_bytes is not None:
                        previews[entry.vpk_path] = entry.preview_bytes

        self._local_entries = entries
        self._local_previews = previews

        self.library_table.blockSignals(True)
        for old_row in range(self.library_table.rowCount()):
            old_widget = self.library_table.cellWidget(old_row, 0)
            if old_widget is not None:
                for lbl in old_widget.findChildren(QLabel):
                    clear_preview_media(lbl)
                self.library_table.removeCellWidget(old_row, 0)
                old_widget.hide()
                old_widget.setParent(None)
                old_widget.deleteLater()
        self.library_table.clearContents()
        self.library_table.setRowCount(len(entries))
        select_row = -1
        for row, entry in enumerate(entries):
            if select_path is not None and entry.vpk_path == select_path:
                select_row = row

            raw_img = previews.get(entry.vpk_path)
            if not raw_img:
                id_match = _WORKSHOP_ID_PREFIX_RE.match(entry.vpk_path.stem)
                if id_match:
                    raw_img = self._prefetched_previews.get(id_match.group(1))
            thumb_cell = create_table_thumb_cell(
                parent_table=self.library_table,
                raw_img=raw_img,
                is_dark=isDarkTheme(),
                title=entry.title,
                i18n=self._i18n,
            )

            id_match = _WORKSHOP_ID_PREFIX_RE.match(entry.vpk_path.stem)
            wid_text = id_match.group(1) if id_match else "—"
            wid_item = QTableWidgetItem(wid_text)
            wid_item.setTextAlignment(Qt.AlignmentFlag.AlignCenter)

            origin_label = SurvivorRegistry.get(entry.origin).display_name if entry.origin else "—"
            surv_item = QTableWidgetItem(origin_label)
            surv_item.setTextAlignment(Qt.AlignmentFlag.AlignCenter)

            title_item = QTableWidgetItem(entry.title)
            title_item.setToolTip(str(entry.vpk_path))

            size_text = format_bytes(entry.vpk_path.stat().st_size if entry.vpk_path.is_file() else 0)
            size_item = QTableWidgetItem(size_text)
            size_item.setTextAlignment(Qt.AlignmentFlag.AlignCenter)

            self.library_table.setItem(row, 0, QTableWidgetItem(""))
            self.library_table.setItem(row, 1, wid_item)
            self.library_table.setItem(row, 2, surv_item)
            self.library_table.setItem(row, 3, title_item)
            self.library_table.setItem(row, 4, size_item)
            self.library_table.setCellWidget(row, 0, thumb_cell)

        if select_row >= 0:
            self.library_table.selectRow(select_row)
        self.library_table.blockSignals(False)
        self.delete_lib_btn.setEnabled(self.library_table.currentRow() >= 0)
        L4d2ThemeManager.apply_pointing_hand_cursors(self)

    def _on_library_selection_changed(self) -> None:
        row = self.library_table.currentRow()
        if row < 0 or row >= len(self._local_entries):
            self.delete_lib_btn.setEnabled(False)
            return
        self.delete_lib_btn.setEnabled(True)
        L4d2ThemeManager.apply_pointing_hand_cursors(self)
        entry = self._local_entries[row]
        self._active_vpk_path = entry.vpk_path
        id_match = _WORKSHOP_ID_PREFIX_RE.match(entry.vpk_path.stem)
        self._active_workshop_id = id_match.group(1) if id_match else ""
        self._active_details = self._prefetched_details.get(self._active_workshop_id)
        self._render_active_details()

    def _on_zoom_cover(self) -> None:
        if self._active_cover_pixmap is None or self._active_cover_pixmap.isNull():
            return
        dlg = ImageZoomDialog(
            title=self.item_title_label.text(),
            pixmap=self._active_cover_pixmap,
            i18n=self._i18n,
            parent=self.window(),
            raw_bytes=self._active_cover_bytes,
        )
        dlg.exec()

    def _show_not_survivor_popup(self) -> None:
        InfoBar.warning(
            self._i18n.tr("dl_not_skin_title"),
            self._i18n.tr("dl_not_skin_msg"),
            parent=self.window(),
            position=InfoBarPosition.TOP,
            duration=6000,
        )

    def _on_open_full_description(self) -> None:
        details = self._active_details
        if details is None or not details.description.strip():
            return
        parts: list[str] = [f"ID {details.published_file_id}"]
        if details.creator_name:
            parts.append(details.creator_name)
        dlg = WorkshopDescriptionDialog(
            title=details.title,
            raw_description=details.description,
            subtitle="  \u2022  ".join(parts),
            steam_url=details.workshop_url,
            i18n=self._i18n,
            parent=self.window(),
        )
        dlg.exec()

    def _on_open_download_dir(self) -> None:
        dl_dir = self._download_dir()
        dl_dir.mkdir(parents=True, exist_ok=True)
        if os.name == "nt":
            os.startfile(str(dl_dir))
        else:
            QDesktopServices.openUrl(QUrl.fromLocalFile(str(dl_dir)))

    def _on_open_steam_page(self) -> None:
        wid = (self._active_details.published_file_id if self._active_details else "") or self._active_workshop_id
        if wid:
            QDesktopServices.openUrl(QUrl(STEAM_WORKSHOP_ITEM_URL.format(item_id=wid)))

    def _on_send_to_swap(self) -> None:
        if self._active_vpk_path and self._active_vpk_path.is_file():
            self.sendToSwapRequested.emit(self._active_vpk_path)

    def _on_send_to_batch(self) -> None:
        if self._active_vpk_path and self._active_vpk_path.is_file():
            self.sendToBatchRequested.emit([self._active_vpk_path])

    def _on_install_to_addons(self) -> None:
        if not self._active_vpk_path or not self._active_vpk_path.is_file():
            return
        addons_dir = self._get_env().l4d2_addons_dir
        if addons_dir is None or not addons_dir.is_dir():
            InfoBar.warning(
                self._i18n.tr("info_addons_missing_title"),
                self._i18n.tr("info_addons_missing_msg"),
                parent=self.window(),
                position=InfoBarPosition.TOP,
            )
            return
        entry = AddonsScanner._inspect_vpk_fast(
            self._active_vpk_path,
            "workshop",
            self._active_vpk_path.parent,
            {},
            allow_non_survivor=True,
        )
        ok = install_vpks_with_conflict_check(
            ready_items=[(entry.origin if entry else None, self._active_vpk_path)],
            addons_dir=addons_dir,
            i18n=self._i18n,
            parent=self.window(),
            conflict_dialog_cls=AddonConflictDialog,
            info_bar_cls=InfoBar,
            info_position=InfoBarPosition.TOP,
        )
        if ok:
            self.addonsChanged.emit()

    def _on_delete_selected(self) -> None:
        row = self.library_table.currentRow()
        if row < 0 or row >= len(self._local_entries):
            return
        target = self._local_entries[row].vpk_path
        box = MessageBox(
            self._i18n.tr("dl_confirm_delete_title"),
            self._i18n.tr("dl_confirm_delete_msg", name=target.name),
            self.window(),
        )
        L4d2ThemeManager.style_dialog_yes_button(box.yesButton, self._i18n.tr("dl_btn_delete_lib"), FluentIcon.DELETE)
        L4d2ThemeManager.style_dialog_cancel_button(box.cancelButton, self._i18n.tr("dl_btn_cancel"), FluentIcon.CLOSE)
        L4d2ThemeManager.apply_pointing_hand_cursors(box)
        if not box.exec():
            return
        try:
            target.unlink(missing_ok=True)
        except OSError as exc:
            InfoBar.error(
                self._i18n.tr("addons_page_del_title"),
                self._i18n.tr("addons_page_del_err", error=exc),
                parent=self.window(),
                position=InfoBarPosition.TOP,
                duration=6000,
            )
            return
        if self._active_vpk_path == target:
            self._active_vpk_path = None
        InfoBar.success(
            self._i18n.tr("dl_deleted_title"),
            self._i18n.tr("dl_deleted_msg", name=target.name),
            parent=self.window(),
            position=InfoBarPosition.TOP,
        )
        self.refresh_library()
        self._render_active_details()

    def shutdown_worker(self) -> None:
        clear_preview_media(self.cover_thumb)
        shutdown_worker_thread(
            self._fetch_thread,
            self._fetch_worker,
            cancel_fn=self._fetch_worker.request_cancel if self._fetch_worker is not None else None,
            ui_signals=(
                (self._fetch_worker.fetched, self._fetch_worker.failed)
                if self._fetch_worker is not None
                else ()
            ),
            timeout_ms=3000,
        )
        self._fetch_worker = None
        self._fetch_thread = None

        shutdown_worker_thread(
            self._dl_thread,
            self._dl_worker,
            cancel_fn=self._dl_worker.request_cancel if self._dl_worker is not None else None,
            ui_signals=(
                (self._dl_worker.progressUpdated, self._dl_worker.completed, self._dl_worker.failed)
                if self._dl_worker is not None
                else ()
            ),
            timeout_ms=3000,
        )
        self._dl_worker = None
        self._dl_thread = None
