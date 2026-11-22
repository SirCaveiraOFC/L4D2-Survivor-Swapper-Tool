from __future__ import annotations

import os
from pathlib import Path
from typing import Callable, Optional

from PySide6.QtCore import QUrl, Qt, Signal
from PySide6.QtGui import QColor, QDesktopServices, QPixmap
from PySide6.QtWidgets import (
    QAbstractItemView,
    QHBoxLayout,
    QHeaderView,
    QListWidgetItem,
    QTableWidgetItem,
    QVBoxLayout,
    QWidget,
)
from qfluentwidgets import (
    BodyLabel,
    CaptionLabel,
    FluentIcon,
    IconWidget,
    InfoBar,
    InfoBarPosition,
    PrimaryPushButton,
    PushButton,
    ScrollArea,
    StrongBodyLabel,
    SubtitleLabel,
    TableWidget,
    isDarkTheme,
)

from core.addons_scanner import AddonsScanner
from core.history_manager import HistoryManager
from core.i18n import LocalizationManager
from core.models import ConversionHistoryEntry, EnvironmentStatus, SurvivorId
from core.survivors import SurvivorRegistry
from ui.addon_ui_shared import (
    CenteredIconHeaderView,
    create_preview_zoom_button,
    create_styled_list_widget,
    create_table_thumb_cell,
    install_vpks_with_conflict_check,
    set_table_headers_with_icons,
    style_list_widget,
)
from ui.addons_browser_dialog import AddonConflictDialog
from ui.theme import COLORS, L4d2ThemeManager
from ui.widgets import ClickableImageLabel, ImageZoomDialog


class HistoryPage(ScrollArea):
    """Dedicated page reviewing previous skin conversions and reinstalling or reopening them."""

    reopenSourceRequested = Signal(Path)
    addonsChanged = Signal()

    def __init__(
        self,
        history_mgr: HistoryManager,
        get_env_fn: Callable[[], EnvironmentStatus],
        i18n: Optional[LocalizationManager] = None,
        parent: Optional[QWidget] = None,
    ) -> None:
        super().__init__(parent)
        self.setObjectName("historyPage")
        self.history_mgr = history_mgr
        self._get_env = get_env_fn
        self._i18n = i18n or LocalizationManager("en-US")
        self._entries: list[ConversionHistoryEntry] = []
        self._thumb_cache: dict[str, Optional[bytes]] = {}
        self._current_detail_pixmap: Optional[QPixmap] = None

        self.view = QWidget(self)
        self.setWidget(self.view)
        self.setWidgetResizable(True)
        self.enableTransparentBackground()

        root = QVBoxLayout(self.view)
        root.setContentsMargins(28, 20, 28, 28)
        root.setSpacing(14)

        header_row = QHBoxLayout()
        header_row.setSpacing(10)
        title_col = QVBoxLayout()
        title_col.setSpacing(2)
        title_row = QHBoxLayout()
        title_row.setSpacing(8)
        self.title_icon = IconWidget(FluentIcon.HISTORY, self.view)
        self.title_icon.setFixedSize(20, 20)
        self.page_title = SubtitleLabel("", self.view)
        title_row.addWidget(self.title_icon, 0, Qt.AlignmentFlag.AlignVCenter)
        title_row.addWidget(self.page_title)
        title_row.addStretch(1)
        self.page_subtitle = BodyLabel("", self.view)
        self.page_subtitle.setWordWrap(True)
        title_col.addLayout(title_row)
        title_col.addWidget(self.page_subtitle)

        self.refresh_btn = PushButton(FluentIcon.SYNC, "", self.view)
        self.clear_btn = PushButton(FluentIcon.DELETE, "", self.view)
        header_row.addLayout(title_col, 1)
        header_row.addWidget(self.refresh_btn)
        header_row.addWidget(self.clear_btn)
        root.addLayout(header_row)

        self.count_label = CaptionLabel("", self.view)
        root.addWidget(self.count_label)

        content_row = QHBoxLayout()
        content_row.setSpacing(12)

        self.history_table = TableWidget(self.view)
        self.history_table.setHorizontalHeader(
            CenteredIconHeaderView(Qt.Orientation.Horizontal, self.history_table)
        )
        self.history_table.setColumnCount(5)
        self.history_table.setMinimumHeight(420)
        self.history_table.setSelectionBehavior(QAbstractItemView.SelectionBehavior.SelectRows)
        self.history_table.setSelectionMode(QAbstractItemView.SelectionMode.SingleSelection)
        self.history_table.setEditTriggers(QAbstractItemView.EditTrigger.NoEditTriggers)
        self.history_table.setFocusPolicy(Qt.FocusPolicy.NoFocus)
        self.history_table.verticalHeader().setVisible(False)
        self.history_table.verticalHeader().setDefaultSectionSize(54)
        self.history_table.setBorderVisible(True)
        self.history_table.setBorderRadius(6)
        self.history_table.setWordWrap(False)
        self.history_table.viewport().setCursor(Qt.CursorShape.PointingHandCursor)

        hdr = self.history_table.horizontalHeader()
        hdr.setSectionResizeMode(0, QHeaderView.ResizeMode.ResizeToContents)
        hdr.setSectionResizeMode(1, QHeaderView.ResizeMode.Fixed)
        self.history_table.setColumnWidth(1, 84)
        hdr.setSectionResizeMode(2, QHeaderView.ResizeMode.Stretch)
        hdr.setSectionResizeMode(3, QHeaderView.ResizeMode.ResizeToContents)
        hdr.setSectionResizeMode(4, QHeaderView.ResizeMode.ResizeToContents)

        self.detail_panel = QWidget(self.view)
        self.detail_panel.setObjectName("historyDetailPanel")
        self.detail_panel.setAttribute(Qt.WidgetAttribute.WA_StyledBackground, True)
        self.detail_panel.setFixedWidth(360)
        detail_lay = QVBoxLayout(self.detail_panel)
        detail_lay.setContentsMargins(14, 14, 14, 14)
        detail_lay.setSpacing(10)

        self.detail_thumb_label = ClickableImageLabel(self.detail_panel)
        self.detail_thumb_label.setFixedSize(240, 160)
        self.detail_thumb_label.setAlignment(Qt.AlignmentFlag.AlignCenter)
        self.detail_thumb_label.setVisible(False)
        self.detail_zoom_btn = create_preview_zoom_button(
            self.detail_thumb_label,
            tooltip=self._i18n.tr("addons_dlg_zoom_tip"),
            size=28,
            margin=6,
        )

        self.detail_title = StrongBodyLabel("", self.detail_panel)
        self.detail_title.setWordWrap(True)
        self.detail_meta = CaptionLabel("", self.detail_panel)
        self.detail_meta.setWordWrap(True)
        self.detail_meta.setTextInteractionFlags(Qt.TextInteractionFlag.TextSelectableByMouse)
        self.outputs_list = create_styled_list_widget(self.detail_panel, min_height=180)

        self.reopen_btn = PushButton(FluentIcon.SYNC, "", self.detail_panel)
        self.install_btn = PrimaryPushButton(FluentIcon.DOWNLOAD, "", self.detail_panel)
        self.open_dir_btn = PushButton(FluentIcon.FOLDER, "", self.detail_panel)
        self.remove_btn = PushButton(FluentIcon.DELETE, "", self.detail_panel)

        detail_lay.addWidget(self.detail_thumb_label, 0, Qt.AlignmentFlag.AlignHCenter)
        detail_lay.addWidget(self.detail_title)
        detail_lay.addWidget(self.detail_meta)
        detail_lay.addWidget(self.outputs_list, 1)
        detail_lay.addWidget(self.install_btn)
        detail_lay.addWidget(self.reopen_btn)
        detail_lay.addWidget(self.open_dir_btn)
        detail_lay.addWidget(self.remove_btn)

        content_row.addWidget(self.history_table, 1)
        content_row.addWidget(self.detail_panel)
        root.addLayout(content_row, 1)

        self.refresh_btn.clicked.connect(self.refresh_view)
        self.clear_btn.clicked.connect(self._on_clear_history)
        self.history_table.itemSelectionChanged.connect(self._on_selection_changed)
        self.detail_thumb_label.clicked.connect(self._on_zoom_detail_cover)
        self.detail_zoom_btn.clicked.connect(self._on_zoom_detail_cover)
        self.reopen_btn.clicked.connect(self._on_reopen_source)
        self.install_btn.clicked.connect(self._on_install_outputs)
        self.open_dir_btn.clicked.connect(self._on_open_output_dir)
        self.remove_btn.clicked.connect(self._on_remove_selected)

        self.retranslate_ui(self._i18n)
        self.refresh_view()

    def retranslate_ui(self, i18n: LocalizationManager) -> None:
        self._i18n = i18n
        self.page_title.setText(i18n.tr("hist_page_title"))
        self.page_subtitle.setText(i18n.tr("hist_page_subtitle"))
        self.refresh_btn.setText(i18n.tr("addons_page_refresh"))
        self.clear_btn.setText(i18n.tr("hist_btn_clear"))
        self.reopen_btn.setText(i18n.tr("hist_btn_reopen"))
        self.install_btn.setText(i18n.tr("hist_btn_install"))
        self.open_dir_btn.setText(i18n.tr("hist_btn_open_folder"))
        self.remove_btn.setText(i18n.tr("hist_btn_remove"))
        set_table_headers_with_icons(
            self.history_table,
            [
                (FluentIcon.DATE_TIME, i18n.tr("hist_col_date")),
                (FluentIcon.PHOTO, i18n.tr("addons_dlg_col_preview")),
                (FluentIcon.TAG, i18n.tr("hist_col_mod")),
                (FluentIcon.SYNC, i18n.tr("hist_col_swap")),
                (FluentIcon.INFO, i18n.tr("hist_col_status")),
            ],
        )

        is_dark = isDarkTheme()
        panel_border = COLORS.dark_border if is_dark else COLORS.light_border
        L4d2ThemeManager.install_surface_motion(
            self.detail_panel,
            f"QWidget#historyDetailPanel {{ background-color: {{bg}}; "
            f"border: 1px solid {panel_border}; border-radius: 6px; }}",
            tone="neutral",
        )
        style_list_widget(self.outputs_list)
        self.detail_thumb_label.setObjectName("historyDetailThumb")
        L4d2ThemeManager.install_surface_motion(
            self.detail_thumb_label,
            "QLabel#historyDetailThumb { background-color: {bg}; border: 1px solid {border}; border-radius: 6px; padding: 4px; }",
            custom_colors=L4d2ThemeManager.image_surface_palette(is_dark),
            border_colors=L4d2ThemeManager.image_border_colors(is_dark),
        )
        self.detail_zoom_btn.setToolTip(i18n.tr("addons_dlg_zoom_tip"))
        if self._current_detail_pixmap is not None:
            self.detail_thumb_label.setToolTip(i18n.tr("addons_dlg_zoom_tip"))
        self._populate_table()
        L4d2ThemeManager.apply_pointing_hand_cursors(self)

    def refresh_view(self) -> None:
        self._entries = self.history_mgr.load()
        self._thumb_cache.clear()
        self._populate_table()

    def _resolve_entry_preview_bytes(self, entry: ConversionHistoryEntry) -> Optional[bytes]:
        if entry.entry_id in self._thumb_cache:
            return self._thumb_cache[entry.entry_id]
        raw: Optional[bytes] = None
        for out in entry.outputs:
            if out.vpk_path:
                out_path = Path(out.vpk_path)
                if out_path.exists():
                    raw = AddonsScanner.read_source_preview_image(out_path)
                    if raw:
                        break
        if not raw and entry.source_path:
            src_path = Path(entry.source_path)
            if src_path.exists():
                raw = AddonsScanner.read_source_preview_image(src_path)
        self._thumb_cache[entry.entry_id] = raw
        return raw

    def selected_entry(self) -> Optional[ConversionHistoryEntry]:
        row = self.history_table.currentRow()
        if row < 0:
            return None
        item = self.history_table.item(row, 0)
        data = item.data(Qt.ItemDataRole.UserRole) if item is not None else None
        return data if isinstance(data, ConversionHistoryEntry) else None

    def _populate_table(self) -> None:
        if not self._entries:
            self.count_label.setText(self._i18n.tr("hist_empty"))
        else:
            self.count_label.setText(self._i18n.tr_plural("hist_count", len(self._entries)))
        self.clear_btn.setEnabled(bool(self._entries))

        is_dark = isDarkTheme()
        ok_color = QColor("#4ADE80" if is_dark else "#15803D")
        warn_color = QColor(COLORS.amber if is_dark else COLORS.amber_deep)
        err_color = QColor("#F87171" if is_dark else "#B91C1C")

        self.history_table.setRowCount(len(self._entries))
        for row_idx, entry in enumerate(self._entries):
            ok_count = sum(1 for o in entry.outputs if o.success)
            cancel_count = sum(1 for o in entry.outputs if o.cancelled)
            total = max(1, len(entry.outputs) or len(entry.destinations))

            if cancel_count > 0:
                status_text = self._i18n.tr("hist_status_cancelled", ok=ok_count, total=total)
                color = warn_color
            elif ok_count == total:
                status_text = self._i18n.tr("hist_status_ok", ok=ok_count, total=total)
                color = ok_color
            elif ok_count > 0:
                status_text = self._i18n.tr("hist_status_partial", ok=ok_count, total=total)
                color = warn_color
            else:
                status_text = self._i18n.tr("hist_status_failed")
                color = err_color

            origin_name = self._survivor_name(entry.origin)
            dest_names = ", ".join(self._survivor_name(d) for d in entry.destinations)
            swap_label = f"{origin_name} -> {dest_names}"

            raw_img = self._resolve_entry_preview_bytes(entry)
            self.history_table.setCellWidget(
                row_idx,
                1,
                create_table_thumb_cell(
                    self.history_table,
                    raw_img,
                    is_dark,
                    title=entry.mod_title,
                    i18n=self._i18n,
                ),
            )

            date_item = QTableWidgetItem(self._i18n.format_date_str(entry.created_at))
            date_item.setData(Qt.ItemDataRole.UserRole, entry)
            thumb_item = QTableWidgetItem("")
            mod_item = QTableWidgetItem(entry.mod_title)
            swap_item = QTableWidgetItem(swap_label)
            status_item = QTableWidgetItem(status_text)
            status_item.setForeground(color)

            for col, cell in enumerate((date_item, thumb_item, mod_item, swap_item, status_item)):
                self.history_table.setItem(row_idx, col, cell)

        if self._entries and self.history_table.currentRow() < 0:
            self.history_table.selectRow(0)
        self._on_selection_changed()

    def _survivor_name(self, raw_id: str) -> str:
        try:
            return SurvivorRegistry.get(raw_id).display_name
        except Exception:
            return raw_id or "?"

    def _on_selection_changed(self) -> None:
        entry = self.selected_entry()
        self.outputs_list.clear()
        has_sel = entry is not None
        self.reopen_btn.setEnabled(has_sel)
        self.open_dir_btn.setEnabled(has_sel and bool(entry.output_dir))
        self.remove_btn.setEnabled(has_sel)

        if entry is None:
            self._current_detail_pixmap = None
            self.detail_zoom_btn.setVisible(False)
            self.detail_thumb_label.setVisible(False)
            self.detail_title.setText("")
            self.detail_meta.setText(self._i18n.tr("hist_select_hint"))
            self.install_btn.setEnabled(False)
            return

        raw_img = self._resolve_entry_preview_bytes(entry)
        loaded_pix = QPixmap()
        if raw_img and loaded_pix.loadFromData(raw_img) and not loaded_pix.isNull():
            self._current_detail_pixmap = loaded_pix
            self.detail_thumb_label.setPixmap(
                loaded_pix.scaled(
                    232,
                    152,
                    Qt.AspectRatioMode.KeepAspectRatio,
                    Qt.TransformationMode.SmoothTransformation,
                )
            )
            self.detail_thumb_label.setCursor(Qt.CursorShape.PointingHandCursor)
            self.detail_thumb_label.setToolTip(self._i18n.tr("addons_dlg_zoom_tip"))
            self.detail_thumb_label.setVisible(True)
            self.detail_zoom_btn.setVisible(True)
        else:
            self._current_detail_pixmap = None
            self.detail_thumb_label.setPixmap(QPixmap())
            self.detail_thumb_label.setVisible(False)
            self.detail_zoom_btn.setVisible(False)

        self.detail_title.setText(entry.mod_title)
        meta_lines = [
            f"{self._i18n.tr('hist_col_date')}: {self._i18n.format_date_str(entry.created_at)}",
            f"{self._i18n.tr('addons_dlg_lbl_author')}: {entry.author or self._i18n.tr('addons_dlg_unknown_author')}",
            f"{self._i18n.tr('addons_dlg_lbl_file')}: {Path(entry.source_path).name}",
        ]
        self.detail_meta.setText("\n".join(meta_lines))

        existing_vpks = 0
        for out in entry.outputs:
            dest_name = self._survivor_name(out.destination)
            if out.success and out.vpk_path:
                vpk_file = Path(out.vpk_path)
                exists_tag = "[OK]" if vpk_file.exists() else f"[{self._i18n.tr('badge_missing')}]"
                if vpk_file.exists():
                    existing_vpks += 1
                line = f"{dest_name}: {vpk_file.name}  {exists_tag}"
            elif out.cancelled:
                line = f"{dest_name}: {self._i18n.tr('btn_cancel')}"
            else:
                line = f"{dest_name}: {out.error_message}"
            item = QListWidgetItem(line)
            item.setToolTip(out.vpk_path or out.error_message)
            self.outputs_list.addItem(item)

        self.install_btn.setEnabled(
            existing_vpks > 0 and self._get_env().l4d2_addons_dir is not None
        )

    def _on_zoom_detail_cover(self) -> None:
        if self._current_detail_pixmap is None or self._current_detail_pixmap.isNull():
            return
        entry = self.selected_entry()
        dlg = ImageZoomDialog(
            title=entry.mod_title if entry is not None else self._i18n.tr("hist_page_title"),
            pixmap=self._current_detail_pixmap,
            i18n=self._i18n,
            parent=self.window(),
        )
        dlg.exec()

    def _on_reopen_source(self) -> None:
        entry = self.selected_entry()
        if entry is None:
            return
        src = Path(entry.source_path)
        if not src.exists():
            InfoBar.warning(
                self._i18n.tr("hist_source_missing_title"),
                self._i18n.tr("hist_source_missing_msg", path=src),
                parent=self.window(),
                position=InfoBarPosition.TOP,
            )
            return
        self.reopenSourceRequested.emit(src)

    def _on_install_outputs(self) -> None:
        entry = self.selected_entry()
        addons_dir = self._get_env().l4d2_addons_dir
        if entry is None or addons_dir is None:
            return

        ready: list[tuple[SurvivorId, Path]] = []
        for out in entry.outputs:
            if out.success and out.vpk_path:
                vpk_path = Path(out.vpk_path)
                if vpk_path.exists():
                    try:
                        ready.append((SurvivorId(out.destination), vpk_path))
                    except ValueError:
                        pass

        if not ready:
            InfoBar.warning(
                self._i18n.tr("hist_no_vpk_title"),
                self._i18n.tr("hist_no_vpk_msg"),
                parent=self.window(),
                position=InfoBarPosition.TOP,
            )
            return

        if install_vpks_with_conflict_check(
            ready_items=ready,
            addons_dir=addons_dir,
            i18n=self._i18n,
            parent=self.window(),
            conflict_dialog_cls=AddonConflictDialog,
            info_bar_cls=InfoBar,
            info_position=InfoBarPosition.TOP,
        ):
            self.addonsChanged.emit()

    def _on_open_output_dir(self) -> None:
        entry = self.selected_entry()
        if entry is None or not entry.output_dir:
            return
        out_dir = Path(entry.output_dir)
        if out_dir.exists():
            try:
                os.startfile(str(out_dir))
            except OSError:
                QDesktopServices.openUrl(QUrl.fromLocalFile(str(out_dir)))

    def _on_remove_selected(self) -> None:
        entry = self.selected_entry()
        if entry is None:
            return
        self._entries = self.history_mgr.remove_entry(entry.entry_id)
        self._populate_table()

    def _on_clear_history(self) -> None:
        self.history_mgr.clear()
        self._entries = []
        self._populate_table()
