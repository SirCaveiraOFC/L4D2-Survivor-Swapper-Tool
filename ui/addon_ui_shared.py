from __future__ import annotations

import shutil
import threading
import uuid
from datetime import datetime
from pathlib import Path
from typing import Any, Callable, Optional

from PySide6.QtCore import QEvent, QObject, QRect, QSize, QThread, QTimer, QUrl, Qt, Signal
from PySide6.QtGui import QColor, QDesktopServices, QFont, QFontMetrics, QIcon, QMouseEvent, QPainter, QPixmap
from PySide6.QtWidgets import (
    QAbstractItemView,
    QApplication,
    QFrame,
    QHBoxLayout,
    QHeaderView,
    QLabel,
    QListWidget,
    QSizePolicy,
    QStyle,
    QStyleOptionHeader,
    QTableWidgetItem,
    QToolButton,
    QVBoxLayout,
    QWidget,
)
from qfluentwidgets import (
    BodyLabel,
    CaptionLabel,
    FlowLayout,
    FluentIcon,
    IconWidget,
    MessageBoxBase,
    ScrollArea,
    StrongBodyLabel,
    SubtitleLabel,
    TableWidget,
    Theme,
    ToolTipFilter,
    ToolTipPosition,
    isDarkTheme,
)

from core.addons_scanner import AddonsScanner
from core.history_manager import HistoryManager
from core.i18n import LocalizationManager
from core.models import (
    ConversionHistoryEntry,
    ConversionHistoryOutput,
    InstalledAddonEntry,
    ModMetadata,
    SurvivorId,
    SwapTargetResult,
)
from core.survivors import SurvivorRegistry
from core.swap_engine import SwapEngine
from ui.theme import COLORS, L4d2ThemeManager
from ui.widgets import (
    ClickableImageLabel,
    FlowPanel,
    ImageZoomDialog,
    bind_preview_media,
    create_icon_row,
    create_switch_with_help,
    update_switch_help,
    wrap_tooltip_text,
)


def launch_l4d2_steam() -> None:
    """Launch Left 4 Dead 2 (Steam AppID 550) via Steam protocol."""
    QDesktopServices.openUrl(QUrl("steam://rungameid/550"))


_DETACHED_WORKERS: set[tuple[QThread, Optional[QObject]]] = set()


def shutdown_worker_thread(
    thread: Optional[QThread],
    worker: Optional[QObject] = None,
    cancel_fn: Optional[Callable[[], None]] = None,
    ui_signals: tuple[Any, ...] = (),
    timeout_ms: int = 3500,
) -> None:
    """Safely cancel, wait, or detach a worker QThread so widget destruction never aborts Qt."""
    if cancel_fn is not None:
        try:
            cancel_fn()
        except Exception:
            pass
    if thread is None or not thread.isRunning():
        return
    for sig in ui_signals:
        try:
            sig.disconnect()
        except (RuntimeError, TypeError):
            pass
    thread.quit()
    if thread.wait(timeout_ms):
        return

    entry = (thread, worker)
    _DETACHED_WORKERS.add(entry)
    thread.setParent(QApplication.instance())

    def _release() -> None:
        _DETACHED_WORKERS.discard(entry)
        if worker is not None:
            worker.deleteLater()
        thread.deleteLater()

    thread.finished.connect(_release)


class AddonsScanWorker(QObject):
    """Background worker scanning left4dead2/addons and workshop for survivor mods."""

    finished = Signal(list)
    failed = Signal(str)

    def __init__(self, addons_dir: Path) -> None:
        super().__init__()
        self.addons_dir = addons_dir
        self._cancel_event = threading.Event()

    def request_cancel(self) -> None:
        self._cancel_event.set()

    def run(self) -> None:
        try:
            entries = AddonsScanner.scan_survivor_addons(
                self.addons_dir,
                include_workshop=True,
                cancel_cb=self._cancel_event.is_set,
            )
            if not self._cancel_event.is_set():
                self.finished.emit(entries)
        except Exception as exc:
            if not self._cancel_event.is_set():
                self.failed.emit(str(exc))


def style_list_widget(list_widget: QListWidget) -> None:
    """Apply active Dark or Light L4D2 theme colors to an existing QListWidget."""
    is_dark = isDarkTheme()
    bg = COLORS.dark_card_alt if is_dark else COLORS.light_card_alt
    border = COLORS.dark_border if is_dark else COLORS.light_border
    text = COLORS.dark_text if is_dark else COLORS.light_text
    accent = COLORS.amber if is_dark else COLORS.red
    sel_bg = "rgba(245, 183, 0, 0.22)" if is_dark else "rgba(217, 43, 43, 0.14)"
    list_widget.setStyleSheet(
        f"QListWidget {{ background-color: {bg}; border: 1px solid {border}; "
        f"border-radius: 6px; color: {text}; padding: 4px; }}"
        f"QListWidget::item {{ padding: 6px 8px; border-radius: 4px; }}"
        f"QListWidget::item:selected {{ background-color: {sel_bg}; "
        f"border: 1px solid {accent}; color: {text}; }}"
    )


def create_styled_list_widget(
    parent: QWidget,
    min_height: int,
    max_height: Optional[int] = None,
) -> QListWidget:
    """Build a themed QListWidget with consistent height constraints."""
    list_widget = QListWidget(parent)
    list_widget.setMinimumHeight(min_height)
    if max_height is not None:
        list_widget.setMaximumHeight(max_height)
    style_list_widget(list_widget)
    return list_widget


class CenteredIconHeaderView(QHeaderView):
    """Horizontal table header centering each icon and text label together with a fixed gap."""

    _ICON_TEXT_GAP = 6
    _HEADER_PIXEL_SIZE = 13
    _MIN_SIDE_PADDING = 4
    _HINT_HORIZONTAL_PADDING = 22

    def __init__(
        self,
        orientation: Qt.Orientation = Qt.Orientation.Horizontal,
        parent: QWidget | None = None,
    ) -> None:
        super().__init__(orientation, parent)
        self.setDefaultAlignment(Qt.AlignmentFlag.AlignCenter)

    def _icon_edge(self) -> int:
        size = self.iconSize()
        edge = min(size.width(), size.height()) if size.isValid() else 0
        return edge if edge > 0 else 14

    def _header_font_metrics(self) -> QFontMetrics:
        font = QFont(self.font())
        if font.pixelSize() <= 0:
            font.setPixelSize(self._HEADER_PIXEL_SIZE)
        return QFontMetrics(font)

    def paintSection(self, painter: QPainter, rect: QRect, logicalIndex: int) -> None:
        """Paint the native section frame and center its icon and text as one group."""
        if not rect.isValid():
            return

        opt = QStyleOptionHeader()
        self.initStyleOption(opt)
        self.initStyleOptionForIndex(opt, logicalIndex)
        opt.rect = rect
        icon = opt.icon
        text = opt.text

        section_opt = QStyleOptionHeader(opt)
        section_opt.icon = QIcon()
        section_opt.text = ""
        painter.save()
        self.style().drawControl(QStyle.ControlElement.CE_HeaderSection, section_opt, painter, self)
        painter.restore()

        has_icon = not icon.isNull()
        if not has_icon and not text:
            return

        icon_edge = min(self._icon_edge(), max(1, rect.height() - 4)) if has_icon else 0
        gap = self._ICON_TEXT_GAP if (has_icon and text) else 0
        text_width = self._header_font_metrics().horizontalAdvance(text) if text else 0
        total_width = icon_edge + gap + text_width
        x = rect.x() + max(self._MIN_SIDE_PADDING, (rect.width() - total_width) // 2)

        painter.save()
        painter.setClipRect(rect)
        if has_icon:
            icon_y = rect.y() + (rect.height() - icon_edge) // 2
            icon.paint(painter, QRect(x, icon_y, icon_edge, icon_edge), Qt.AlignmentFlag.AlignCenter)
            x += icon_edge + gap
        if text:
            label_opt = QStyleOptionHeader(opt)
            label_opt.icon = QIcon()
            label_opt.text = text
            label_opt.textAlignment = Qt.AlignmentFlag.AlignVCenter | Qt.AlignmentFlag.AlignLeft
            avail_width = max(0, rect.right() - x - 2)
            label_opt.rect = QRect(x, rect.y(), avail_width, rect.height())
            self.style().drawControl(QStyle.ControlElement.CE_HeaderLabel, label_opt, painter, self)
        painter.restore()

    def sectionSizeFromContents(self, logicalIndex: int) -> QSize:
        """Allocate enough section width for the icon, fixed gap, text, and side padding."""
        size = super().sectionSizeFromContents(logicalIndex)
        model = self.model()
        if model is None:
            return size
        icon = model.headerData(logicalIndex, self.orientation(), Qt.ItemDataRole.DecorationRole)
        text = str(model.headerData(logicalIndex, self.orientation(), Qt.ItemDataRole.DisplayRole) or "")
        has_icon = isinstance(icon, QIcon) and not icon.isNull()
        icon_edge = self._icon_edge() if has_icon else 0
        gap = self._ICON_TEXT_GAP if (has_icon and text) else 0
        text_width = self._header_font_metrics().horizontalAdvance(text) if text else 0
        needed_width = icon_edge + gap + text_width + self._HINT_HORIZONTAL_PADDING
        return QSize(max(size.width(), needed_width), size.height())


def create_styled_mod_table(parent: QWidget, headers: list[str], min_height: int) -> TableWidget:
    """Build the standardized 5-column survivor mod TableWidget with thumbnail column."""
    table = TableWidget(parent)
    table.setHorizontalHeader(CenteredIconHeaderView(Qt.Orientation.Horizontal, table))
    table.setColumnCount(len(headers))
    table.setHorizontalHeaderLabels(headers)
    table.setMinimumHeight(min_height)
    table.setSelectionBehavior(QAbstractItemView.SelectionBehavior.SelectRows)
    table.setSelectionMode(QAbstractItemView.SelectionMode.SingleSelection)
    table.setEditTriggers(QAbstractItemView.EditTrigger.NoEditTriggers)
    table.setFocusPolicy(Qt.FocusPolicy.NoFocus)
    table.verticalHeader().setVisible(False)
    table.verticalHeader().setDefaultSectionSize(54)
    table.setBorderVisible(True)
    table.setBorderRadius(6)
    table.setWordWrap(False)
    table.viewport().setCursor(Qt.CursorShape.PointingHandCursor)

    header = table.horizontalHeader()
    header.setSectionResizeMode(0, QHeaderView.ResizeMode.Fixed)
    table.setColumnWidth(0, 88)
    header.setSectionResizeMode(1, QHeaderView.ResizeMode.ResizeToContents)
    header.setSectionResizeMode(2, QHeaderView.ResizeMode.ResizeToContents)
    header.setSectionResizeMode(3, QHeaderView.ResizeMode.Stretch)
    header.setSectionResizeMode(4, QHeaderView.ResizeMode.ResizeToContents)
    return table


def set_table_headers_with_icons(
    table: TableWidget,
    headers: list[tuple[FluentIcon, str]],
) -> None:
    """Apply localized labels and theme-aware Fluent icons to every TableWidget header column."""
    theme = Theme.DARK if isDarkTheme() else Theme.LIGHT
    table.horizontalHeader().setIconSize(QSize(14, 14))
    for col, (icon, label) in enumerate(headers):
        table.setHorizontalHeaderItem(col, QTableWidgetItem(icon.icon(theme), label))


def set_addon_table_headers(table: TableWidget, i18n: LocalizationManager) -> None:
    """Apply standard 5-column mod table header labels with Fluent icons."""
    set_table_headers_with_icons(
        table,
        [
            (FluentIcon.PHOTO, i18n.tr("addons_dlg_col_preview")),
            (FluentIcon.FOLDER, i18n.tr("addons_dlg_col_folder")),
            (FluentIcon.PEOPLE, i18n.tr("addons_dlg_col_survivor")),
            (FluentIcon.TAG, i18n.tr("addons_dlg_col_mod")),
            (FluentIcon.INFO, i18n.tr("addons_dlg_col_status")),
        ],
    )


def create_preview_zoom_button(
    parent_label: QWidget,
    tooltip: str = "",
    size: int = 32,
    margin: int = 8,
) -> QToolButton:
    """Attach a bottom-right amber-framed magnifying glass button inside a preview label."""
    btn = QToolButton(parent_label)
    btn.setIcon(FluentIcon.ZOOM_IN.icon(Theme.DARK))
    icon_edge = max(14, size // 2)
    btn.setIconSize(QSize(icon_edge, icon_edge))
    btn.setFixedSize(size, size)
    btn.move(max(0, parent_label.width() - size - margin), max(0, parent_label.height() - size - margin))
    if tooltip:
        btn.setToolTip(tooltip)
    btn.setCursor(Qt.CursorShape.PointingHandCursor)
    btn.setStyleSheet(
        f"QToolButton {{ background-color: rgba(15, 18, 24, 195); "
        f"border: 1px solid {COLORS.amber}; border-radius: 6px; padding: 0px; }}"
        f"QToolButton:hover {{ background-color: rgba(35, 40, 50, 235); "
        f"border: 1px solid {COLORS.amber_bright}; }}"
    )
    btn.setVisible(False)
    return btn


class _TableThumbLabel(ClickableImageLabel):
    """Clickable table thumbnail that consumes left presses so row selection does not swallow zoom clicks."""

    def __init__(self, parent: Optional[QWidget] = None) -> None:
        super().__init__(parent)
        self._press_inside = False

    def mousePressEvent(self, event: QMouseEvent) -> None:
        if event.button() == Qt.MouseButton.LeftButton:
            self._press_inside = True
            event.accept()
            return
        super().mousePressEvent(event)

    def mouseReleaseEvent(self, event: QMouseEvent) -> None:
        if event.button() == Qt.MouseButton.LeftButton:
            was_pressed = self._press_inside
            self._press_inside = False
            if was_pressed and self.rect().contains(event.position().toPoint()):
                event.accept()
                self.clicked.emit()
                return
        super().mouseReleaseEvent(event)


def create_table_thumb_cell(
    parent_table: TableWidget,
    raw_img: Optional[bytes],
    is_dark: bool,
    title: str = "",
    i18n: Optional[LocalizationManager] = None,
) -> QWidget:
    """Create a table cell widget rendering a mod thumbnail with click-to-zoom when available."""
    container = QWidget(parent_table)
    container.setStyleSheet("background: transparent;")
    layout = QHBoxLayout(container)
    layout.setContentsMargins(6, 4, 6, 4)
    layout.setAlignment(Qt.AlignmentFlag.AlignCenter)

    muted = COLORS.dark_muted if is_dark else COLORS.light_muted

    pixmap = QPixmap()
    has_image = bool(raw_img and pixmap.loadFromData(raw_img) and not pixmap.isNull())
    if has_image:
        thumb_label: QLabel = _TableThumbLabel(container)
        thumb_label.setObjectName("tableThumbLabel")
        thumb_label.setFixedSize(56, 44)
        thumb_label.setAlignment(Qt.AlignmentFlag.AlignCenter)
        thumb_label.setCursor(Qt.CursorShape.PointingHandCursor)
        if i18n is not None:
            thumb_label.setToolTip(i18n.tr("addons_dlg_zoom_tip"))
        L4d2ThemeManager.install_surface_motion(
            thumb_label,
            f"QLabel#tableThumbLabel {{ background-color: {{bg}}; border: 1px solid {{border}}; "
            f"border-radius: 4px; color: {muted}; }}",
            custom_colors=L4d2ThemeManager.image_surface_palette(is_dark),
            border_colors=L4d2ThemeManager.image_border_colors(is_dark),
        )
        thumb_label.setPixmap(
            pixmap.scaled(
                52,
                40,
                Qt.AspectRatioMode.KeepAspectRatio,
                Qt.TransformationMode.SmoothTransformation,
            )
        )
        bind_preview_media(thumb_label, raw_img, 52, 40)
        zoom_badge = QLabel(thumb_label)
        zoom_badge.setAttribute(Qt.WidgetAttribute.WA_TransparentForMouseEvents, True)
        zoom_badge.setFixedSize(14, 14)
        zoom_badge.move(56 - 16, 44 - 16)
        zoom_badge.setAlignment(Qt.AlignmentFlag.AlignCenter)
        zoom_badge.setPixmap(FluentIcon.ZOOM_IN.icon(Theme.DARK).pixmap(9, 9))
        zoom_badge.setStyleSheet(
            f"QLabel {{ background-color: rgba(15, 18, 24, 210); "
            f"border: 1px solid {COLORS.amber}; border-radius: 3px; padding: 0px; }}"
        )
        resolved_title = title.strip() or (
            i18n.tr("meta_addon_image") if i18n is not None else "Preview"
        )

        def _open_zoom() -> None:
            dlg = ImageZoomDialog(
                title=resolved_title,
                pixmap=pixmap,
                i18n=i18n,
                parent=parent_table.window() or parent_table,
                raw_bytes=raw_img,
            )
            dlg.exec()

        thumb_label.clicked.connect(_open_zoom)
    else:
        img_bg = COLORS.dark_window if is_dark else "#D8D2C5"
        border = COLORS.dark_border if is_dark else COLORS.light_border
        container.setAttribute(Qt.WidgetAttribute.WA_TransparentForMouseEvents, True)
        thumb_label = QLabel(container)
        thumb_label.setAttribute(Qt.WidgetAttribute.WA_TransparentForMouseEvents, True)
        thumb_label.setFixedSize(56, 44)
        thumb_label.setAlignment(Qt.AlignmentFlag.AlignCenter)
        thumb_label.setStyleSheet(
            f"QLabel {{ background-color: {img_bg}; border: 1px solid {border}; "
            f"border-radius: 4px; color: {muted}; }}"
        )
        thumb_label.setText("—")

    layout.addWidget(thumb_label)
    return container


def format_file_size(size_bytes: int) -> str:
    size_mb = size_bytes / (1024 * 1024)
    if size_mb >= 0.1:
        return f"{size_mb:.1f} MB"
    return f"{max(1, size_bytes // 1024)} KB"


def format_addon_details_text(entry: InstalledAddonEntry, i18n: LocalizationManager) -> str:
    """Format rich addoninfo and VPK inspection metadata for side inspector panels."""
    origin_names = [SurvivorRegistry.get(sid).display_name for sid in entry.replaced_survivors]
    if origin_names:
        origin_label = ", ".join(origin_names)
    elif entry.origin is not None:
        origin_label = SurvivorRegistry.get(entry.origin).display_name
    else:
        origin_label = i18n.tr("addons_dlg_unknown_origin")

    source_tag = i18n.tr(
        "addons_dlg_src_workshop"
        if entry.source_kind == "workshop"
        else "addons_dlg_src_addons"
    )
    author = entry.author.strip() or i18n.tr("addons_dlg_unknown_author")
    status = i18n.tr(
        "addons_dlg_status_enabled" if entry.enabled_in_game else "addons_dlg_status_disabled"
    )
    assets = [i18n.tr("addons_dlg_asset_body")]
    if entry.has_arms:
        assets.append(i18n.tr("addons_dlg_asset_arms"))
    if entry.has_vgui:
        assets.append(i18n.tr("addons_dlg_asset_vgui"))

    lines = [
        f"{i18n.tr('addons_dlg_lbl_origin')}: {origin_label}",
        f"{i18n.tr('addons_dlg_lbl_author')}: {author}",
    ]
    if entry.version.strip():
        lines.append(f"{i18n.tr('addons_dlg_lbl_version')}: {entry.version.strip()}")
    lines.append(f"{i18n.tr('addons_dlg_lbl_status')}: {status}")
    lines.append(f"{i18n.tr('addons_dlg_lbl_assets')}: {', '.join(assets)}")
    lines.append(f"{i18n.tr('addons_dlg_lbl_source')}: {source_tag}")
    if entry.file_size_bytes > 0:
        lines.append(f"{i18n.tr('addons_dlg_lbl_size')}: {format_file_size(entry.file_size_bytes)}")
    lines.append(f"{i18n.tr('addons_dlg_lbl_file')}: {entry.vpk_path.name}")
    if entry.author_steam_id.strip():
        lines.append(f"{i18n.tr('addons_dlg_lbl_steam')}: {entry.author_steam_id.strip()}")
    if entry.url.strip():
        lines.append(f"{i18n.tr('addons_dlg_lbl_url')}: {entry.url.strip()}")
    if entry.tagline.strip() and entry.tagline.strip() != entry.description.strip():
        lines.append(f"{i18n.tr('addons_dlg_lbl_tagline')}: {entry.tagline.strip()}")
    if entry.description.strip():
        lines.append("")
        lines.append(f"{i18n.tr('addons_dlg_lbl_desc')}:")
        lines.append(entry.description.strip())
    return "\n".join(lines)


def filter_addon_entries(
    entries: list[InstalledAddonEntry],
    query: str = "",
    source_filter: str = "",
    survivor_filter: str = "",
    status_filter: str = "",
) -> list[InstalledAddonEntry]:
    """Filter scanned survivor addon entries by text, folder kind, survivor/gen, and status."""
    cleaned_query = query.strip().lower()
    filter_gen = survivor_filter.split(":", 1)[1] if survivor_filter.startswith("GEN:") else None
    filter_id: Optional[SurvivorId] = (
        SurvivorId(survivor_filter)
        if survivor_filter and not survivor_filter.startswith("GEN:")
        else None
    )

    matched: list[InstalledAddonEntry] = []
    for entry in entries:
        if source_filter and entry.source_kind != source_filter:
            continue
        if status_filter == "enabled" and not entry.enabled_in_game:
            continue
        if status_filter == "disabled" and entry.enabled_in_game:
            continue

        if filter_gen is not None:
            entry_ids = set(entry.replaced_survivors)
            if entry.origin is not None:
                entry_ids.add(entry.origin)
            if not any(SurvivorRegistry.get(sid).generation == filter_gen for sid in entry_ids):
                continue
        elif filter_id is not None:
            if entry.origin != filter_id and filter_id not in entry.replaced_survivors:
                continue

        if cleaned_query:
            searchable = " ".join([entry.title, entry.vpk_path.name, entry.author]).lower()
            if cleaned_query not in searchable:
                continue

        matched.append(entry)
    return matched


def populate_addon_table(
    table: TableWidget,
    entries: list[InstalledAddonEntry],
    i18n: LocalizationManager,
    get_preview_fn: Callable[[InstalledAddonEntry], Optional[bytes]],
) -> None:
    """Fill a 5-column mod TableWidget cleanly with thumbnails, folder icons, and status colors."""
    is_dark = isDarkTheme()
    folder_icon = FluentIcon.FOLDER.icon()
    ok_icon = FluentIcon.COMPLETED.icon()
    off_icon = FluentIcon.CLOSE.icon()
    active_color = QColor("#4ADE80" if is_dark else "#15803D")
    inactive_color = QColor("#9CA3AF" if is_dark else "#B91C1C")

    table.setRowCount(len(entries))
    for row_idx, entry in enumerate(entries):
        source_tag = i18n.tr(
            "addons_dlg_src_workshop"
            if entry.source_kind == "workshop"
            else "addons_dlg_src_addons"
        )
        origin_label = (
            SurvivorRegistry.get(entry.origin).display_name
            if entry.origin is not None
            else i18n.tr("addons_dlg_unknown_origin")
        )
        status_text = i18n.tr(
            "addons_dlg_status_enabled"
            if entry.enabled_in_game
            else "addons_dlg_status_disabled_short"
        )

        preview_item = QTableWidgetItem("")
        folder_item = QTableWidgetItem(folder_icon, source_tag)
        folder_item.setData(Qt.ItemDataRole.UserRole, entry)
        survivor_item = QTableWidgetItem(origin_label)
        mod_item = QTableWidgetItem(entry.title)
        status_item = QTableWidgetItem(ok_icon if entry.enabled_in_game else off_icon, status_text)
        status_item.setForeground(active_color if entry.enabled_in_game else inactive_color)

        row_cells = (preview_item, folder_item, survivor_item, mod_item, status_item)
        for col_idx, cell in enumerate(row_cells):
            cell.setToolTip(str(entry.vpk_path))
            table.setItem(row_idx, col_idx, cell)
        table.setCellWidget(
            row_idx,
            0,
            create_table_thumb_cell(
                table,
                get_preview_fn(entry),
                is_dark,
                title=entry.title,
                i18n=i18n,
            ),
        )


class AddonPreviewInspector(QWidget):
    """Side inspector card showing enlarged clickable cover preview and full addon details."""

    def __init__(
        self,
        i18n: LocalizationManager,
        parent: Optional[QWidget] = None,
    ) -> None:
        super().__init__(parent)
        self._i18n = i18n
        self._current_entry: Optional[InstalledAddonEntry] = None
        self._current_full_pixmap: Optional[QPixmap] = None

        self.setObjectName("addonPreviewPanel")
        self.setFixedWidth(342)

        preview_lay = QVBoxLayout(self)
        preview_lay.setContentsMargins(12, 12, 12, 12)
        preview_lay.setSpacing(10)

        self.preview_image_label = ClickableImageLabel(self)
        self.preview_image_label.setFixedSize(318, 232)
        self.preview_image_label.setAlignment(Qt.AlignmentFlag.AlignCenter)
        self.preview_image_label.setWordWrap(True)

        self.zoom_btn = create_preview_zoom_button(
            self.preview_image_label,
            tooltip=self._i18n.tr("addons_dlg_zoom_tip"),
            size=32,
            margin=8,
        )

        self.preview_title_label = StrongBodyLabel("", self)
        self.preview_title_label.setWordWrap(True)

        self.details_scroll = ScrollArea(self)
        self.details_scroll.setWidgetResizable(True)
        self.details_scroll.setMinimumHeight(140)
        self.details_scroll.setStyleSheet("ScrollArea { background: transparent; border: none; }")
        details_inner = QWidget(self.details_scroll)
        details_inner.setStyleSheet("background: transparent;")
        details_lay = QVBoxLayout(details_inner)
        details_lay.setContentsMargins(0, 0, 4, 0)
        details_lay.setSpacing(6)

        self.preview_meta_label = CaptionLabel("", details_inner)
        self.preview_meta_label.setWordWrap(True)
        self.preview_meta_label.setTextInteractionFlags(Qt.TextInteractionFlag.TextSelectableByMouse)
        details_lay.addWidget(self.preview_meta_label)
        details_lay.addStretch(1)
        self.details_scroll.setWidget(details_inner)

        self.actions_layout = QVBoxLayout()
        self.actions_layout.setSpacing(6)

        preview_lay.addWidget(self.preview_image_label)
        preview_lay.addWidget(self.preview_title_label)
        preview_lay.addWidget(self.details_scroll, 1)
        preview_lay.addLayout(self.actions_layout)

        self.preview_image_label.clicked.connect(self.open_zoom_dialog)
        self.zoom_btn.clicked.connect(self.open_zoom_dialog)
        self.apply_theme_colors()
        self.set_entry(None, None)

    def apply_theme_colors(self) -> None:
        is_dark = isDarkTheme()
        panel_bg = COLORS.dark_card_alt if is_dark else COLORS.light_card_alt
        panel_border = COLORS.dark_border if is_dark else COLORS.light_border
        img_bg = COLORS.dark_window if is_dark else "#D8D2C5"
        muted = COLORS.dark_muted if is_dark else COLORS.light_muted
        self.setStyleSheet(
            f"QWidget#addonPreviewPanel {{ background-color: {panel_bg}; "
            f"border: 1px solid {panel_border}; border-radius: 6px; }}"
        )
        self.preview_image_label.setObjectName("addonPreviewImage")
        L4d2ThemeManager.install_surface_motion(
            self.preview_image_label,
            f"QLabel#addonPreviewImage {{ background-color: {{bg}}; border: 1px solid {{border}}; "
            f"border-radius: 6px; color: {muted}; padding: 4px; }}",
            custom_colors=L4d2ThemeManager.image_surface_palette(is_dark),
            border_colors=L4d2ThemeManager.image_border_colors(is_dark),
        )

    def retranslate_ui(self, i18n: LocalizationManager) -> None:
        self._i18n = i18n
        self.zoom_btn.setToolTip(i18n.tr("addons_dlg_zoom_tip"))
        if self._current_entry is None:
            self.preview_image_label.setText(i18n.tr("addons_dlg_select_preview"))
        else:
            if self._current_full_pixmap is None:
                self.preview_image_label.setText(i18n.tr("addons_dlg_no_preview"))
            else:
                self.preview_image_label.setToolTip(i18n.tr("addons_dlg_zoom_tip"))
            self.preview_meta_label.setText(format_addon_details_text(self._current_entry, i18n))

    def set_entry(self, entry: Optional[InstalledAddonEntry], raw_img: Optional[bytes]) -> None:
        self._current_entry = entry
        if entry is None:
            self._current_full_pixmap = None
            self.preview_image_label.setPixmap(QPixmap())
            self.preview_image_label.setText(self._i18n.tr("addons_dlg_select_preview"))
            self.preview_image_label.setCursor(Qt.CursorShape.ArrowCursor)
            self.preview_image_label.setToolTip("")
            self.zoom_btn.setVisible(False)
            self.preview_title_label.setText("")
            self.preview_meta_label.setText("")
            return

        loaded_pixmap = QPixmap()
        if raw_img and loaded_pixmap.loadFromData(raw_img) and not loaded_pixmap.isNull():
            self._current_full_pixmap = loaded_pixmap
            scaled = loaded_pixmap.scaled(
                310,
                224,
                Qt.AspectRatioMode.KeepAspectRatio,
                Qt.TransformationMode.SmoothTransformation,
            )
            self.preview_image_label.setText("")
            self.preview_image_label.setPixmap(scaled)
            self.preview_image_label.setCursor(Qt.CursorShape.PointingHandCursor)
            self.preview_image_label.setToolTip(self._i18n.tr("addons_dlg_zoom_tip"))
            self.zoom_btn.setVisible(True)
        else:
            self._current_full_pixmap = None
            self.preview_image_label.setPixmap(QPixmap())
            self.preview_image_label.setText(self._i18n.tr("addons_dlg_no_preview"))
            self.preview_image_label.setCursor(Qt.CursorShape.ArrowCursor)
            self.preview_image_label.setToolTip("")
            self.zoom_btn.setVisible(False)

        self.preview_title_label.setText(entry.title)
        self.preview_meta_label.setText(format_addon_details_text(entry, self._i18n))

    def open_zoom_dialog(self) -> None:
        if self._current_full_pixmap is None or self._current_full_pixmap.isNull():
            return
        title = (
            self._current_entry.title
            if self._current_entry is not None
            else self._i18n.tr("addons_dlg_title")
        )
        dlg = ImageZoomDialog(
            title=title,
            pixmap=self._current_full_pixmap,
            i18n=self._i18n,
            parent=self.window(),
        )
        dlg.exec()


class ArchiveVpkPickerDialog(MessageBoxBase):
    """Modal picker allowing selection of one VPK when an archive or folder holds several."""

    def __init__(
        self,
        bundle_name: str,
        vpk_paths: list[Path],
        i18n: Optional[LocalizationManager] = None,
        parent: Optional[QWidget] = None,
    ) -> None:
        super().__init__(parent)
        self._i18n = i18n or LocalizationManager("en-US")
        self._entries: list[InstalledAddonEntry] = []
        self._preview_cache: dict[Path, Optional[bytes]] = {}
        self.widget.setMinimumWidth(820)

        for vpk_path in vpk_paths:
            entry = AddonsScanner._inspect_vpk_fast(vpk_path, "addons", vpk_path.parent, {})
            if entry is not None:
                if entry.preview_bytes is not None:
                    self._preview_cache[entry.vpk_path] = entry.preview_bytes
                self._entries.append(entry)

        self.title_label = SubtitleLabel(self._i18n.tr("archive_picker_title"), self.widget)
        self.intro_label = BodyLabel(
            self._i18n.tr_plural("archive_picker_intro", len(self._entries), name=bundle_name),
            self.widget,
        )
        self.intro_label.setWordWrap(True)

        self.mod_table = create_styled_mod_table(self.widget, ["", "", "", "", ""], min_height=340)
        set_addon_table_headers(self.mod_table, self._i18n)
        self.mod_table.setColumnHidden(1, True)
        self.mod_table.setColumnHidden(4, True)

        self.viewLayout.addLayout(
            create_icon_row(FluentIcon.ZIP_FOLDER, self.title_label, self.widget, size=20, spacing=10)
        )
        self.viewLayout.addWidget(self.intro_label)
        self.viewLayout.addWidget(self.mod_table)

        populate_addon_table(
            self.mod_table,
            self._entries,
            self._i18n,
            lambda e: self._preview_cache.get(e.vpk_path),
        )
        if self._entries:
            self.mod_table.selectRow(0)

        L4d2ThemeManager.style_dialog_yes_button(
            self.yesButton,
            self._i18n.tr("addons_dlg_select"),
        )
        L4d2ThemeManager.style_dialog_cancel_button(
            self.cancelButton,
            self._i18n.tr("addons_dlg_cancel"),
        )
        self.yesButton.setEnabled(self.selected_vpk() is not None)
        self.mod_table.itemSelectionChanged.connect(
            lambda: self.yesButton.setEnabled(self.selected_vpk() is not None)
        )
        self.mod_table.cellDoubleClicked.connect(lambda _r, _c: self.accept() if self.selected_vpk() else None)
        L4d2ThemeManager.apply_pointing_hand_cursors(self)

    def selected_vpk(self) -> Optional[Path]:
        row = self.mod_table.currentRow()
        if row < 0:
            return None
        item = self.mod_table.item(row, 1)
        data = item.data(Qt.ItemDataRole.UserRole) if item is not None else None
        return data.vpk_path if isinstance(data, InstalledAddonEntry) else None

    def validate(self) -> bool:
        return self.selected_vpk() is not None


def install_vpks_with_conflict_check(
    ready_items: list[tuple[Optional[SurvivorId], Path]],
    addons_dir: Path,
    i18n: LocalizationManager,
    parent: QWidget,
    conflict_dialog_cls: Any,
    info_bar_cls: Any,
    info_position: Any,
) -> bool:
    """Resolve active survivor conflicts via addonlist.txt and copy generated VPKs to addons/."""
    planned = [(sid, vpk.name) for sid, vpk in ready_items if sid is not None]
    conflicts = AddonsScanner.find_conflicts(addons_dir, planned) if addons_dir.exists() else []
    disabled_count = 0
    if conflicts:
        dlg = conflict_dialog_cls(conflicts, i18n=i18n, parent=parent)
        if not dlg.exec() or dlg.choice == "cancel":
            return False
        if dlg.choice == "disable_and_install":
            disable_entries = [c.existing_addon for c in conflicts]
            AddonsScanner.update_addonlist(
                addons_dir,
                disable_entries=disable_entries,
                enable_filenames=[name for _, name in planned],
            )
            disabled_count = len({entry.vpk_path for entry in disable_entries})

    addons_dir.mkdir(parents=True, exist_ok=True)
    copied = 0
    failed_errors: list[str] = []
    for _, vpk_path in ready_items:
        try:
            shutil.copy2(vpk_path, addons_dir / vpk_path.name)
            copied += 1
        except OSError as exc:
            failed_errors.append(f"{vpk_path.name}: {exc}")

    if failed_errors:
        info_bar_cls.error(
            i18n.tr("info_install_failed_title"),
            i18n.tr("info_install_failed_msg", error=failed_errors[0]),
            parent=parent,
            position=info_position,
            duration=7000,
        )
        return False

    installed_text = i18n.tr_plural("info_installed_msg", copied, path=addons_dir)
    if disabled_count > 0:
        disabled_text = i18n.tr_plural("info_disabled_suffix", disabled_count)
        info_bar_cls.success(
            i18n.tr("info_installed_title"),
            f"{installed_text}. {disabled_text}",
            parent=parent,
            position=info_position,
            duration=6000,
        )
    else:
        info_bar_cls.success(
            i18n.tr("info_installed_title"),
            installed_text,
            parent=parent,
            position=info_position,
        )
    return True


def render_target_output_preview(
    file_template: str,
    title_template: str,
    orig_title: str,
    origin_id: Optional[SurvivorId],
    dest: SurvivorId,
    multi_target: bool,
    fallback_stem: str = "my_mod",
    sanitize_origin: bool = True,
) -> tuple[str, str, str]:
    """Compute target display name, sanitized VPK stem, and target AddonTitle via SwapEngine."""
    o_spec = SurvivorRegistry.get(origin_id or SurvivorId.ZOEY)
    d_spec = SurvivorRegistry.get(dest)
    resolved_orig = orig_title.strip() or fallback_stem or o_spec.display_name
    out_file = SwapEngine._sanitize_filename(
        SwapEngine._format_output_name(
            file_template or fallback_stem,
            o_spec,
            d_spec,
            multi_target=multi_target,
            title=resolved_orig,
            sanitize_origin=sanitize_origin,
        )
    )
    meta = SwapEngine._build_target_metadata(
        ModMetadata(title=title_template or resolved_orig, original_title=resolved_orig),
        o_spec,
        d_spec,
        sanitize_origin=sanitize_origin,
    )
    return d_spec.display_name, out_file, meta.title


def render_output_vpk_filenames(
    file_template: str,
    title_template: str,
    orig_title: str,
    origin_id: SurvivorId,
    dest_ids: list[SurvivorId],
    fallback_stem: str,
    sanitize_origin: bool = True,
) -> list[str]:
    """Return all final '.vpk' filenames that SwapEngine will build for one conversion job."""
    multi = len(dest_ids) > 1
    return [
        f"{render_target_output_preview(file_template, title_template, orig_title, origin_id, dest, multi, fallback_stem, sanitize_origin)[1]}.vpk"
        for dest in dest_ids
    ]


def format_template_preview(
    file_template: str,
    title_template: str,
    orig_title: str,
    origin_id: Optional[SurvivorId],
    dest_ids: list[SurvivorId],
    i18n: LocalizationManager,
    fallback_stem: str = "my_mod",
    sanitize_origin: bool = True,
    max_targets: Optional[int] = None,
) -> str:
    """Render live sample or multi-target filenames and AddonTitles using SwapEngine rules."""
    o_spec = SurvivorRegistry.get(origin_id or SurvivorId.ZOEY)

    def render_one(dest: SurvivorId, multi: bool) -> tuple[str, str, str]:
        return render_target_output_preview(
            file_template=file_template,
            title_template=title_template,
            orig_title=orig_title,
            origin_id=origin_id,
            dest=dest,
            multi_target=multi,
            fallback_stem=fallback_stem,
            sanitize_origin=sanitize_origin,
        )

    if not dest_ids:
        sample_dest = SurvivorId.COACH if o_spec.id != SurvivorId.COACH else SurvivorId.NICK
        if o_spec.id == SurvivorId.ZOEY:
            sample_dest = SurvivorId.NICK
        _, out_file, title_text = render_one(sample_dest, True)
        return i18n.tr("meta_tags_preview_sample", file=out_file, title=title_text)

    if len(dest_ids) == 1:
        _, out_file, title_text = render_one(dest_ids[0], False)
        return i18n.tr("meta_tags_preview", file=out_file, title=title_text)

    lines = [i18n.tr("meta_tags_preview_multi_hdr", count=len(dest_ids))]
    shown = dest_ids if max_targets is None else dest_ids[:max(1, max_targets)]
    for dest in shown:
        name, out_file, title_text = render_one(dest, True)
        lines.append(f"  • {name}: {out_file}.vpk  →  {title_text}")
    remaining = dest_ids[len(shown):]
    if remaining:
        names = ", ".join(SurvivorRegistry.get(d).display_name for d in remaining)
        lines.append(i18n.tr_plural("meta_tags_preview_more", len(remaining), names=names))
    return "\n".join(lines)


def update_template_preview_label(
    label: QLabel,
    file_template: str,
    title_template: str,
    orig_title: str,
    origin_id: Optional[SurvivorId],
    dest_ids: list[SurvivorId],
    i18n: LocalizationManager,
    fallback_stem: str = "my_mod",
    sanitize_origin: bool = True,
    max_targets: Optional[int] = None,
) -> None:
    """Update a preview QLabel text and overflow tooltip using rendered template targets."""
    text = format_template_preview(
        file_template=file_template,
        title_template=title_template,
        orig_title=orig_title,
        origin_id=origin_id,
        dest_ids=dest_ids,
        i18n=i18n,
        fallback_stem=fallback_stem,
        sanitize_origin=sanitize_origin,
        max_targets=max_targets,
    )
    full_tip = (
        format_template_preview(
            file_template=file_template,
            title_template=title_template,
            orig_title=orig_title,
            origin_id=origin_id,
            dest_ids=dest_ids,
            i18n=i18n,
            fallback_stem=fallback_stem,
            sanitize_origin=sanitize_origin,
            max_targets=8,
        )
        if max_targets is not None and len(dest_ids) > max_targets
        else ""
    )
    label.setText(text)
    label.setToolTip(wrap_tooltip_text(full_tip, width=64) if full_tip else "")


_TEMPLATE_TAG_SPECS: tuple[tuple[str, str], ...] = (
    ("{survivor}", "meta_tag_tip_survivor"),
    ("{origin}", "meta_tag_tip_origin"),
    ("{orig_title}", "meta_tag_tip_orig_title"),
    ("{generation}", "meta_tag_tip_generation"),
)


class _TemplateTagFilter(QObject):
    """Tracks tag badge clicks and last-focused template inputs for one-click insertion."""

    def __init__(self, bar: TemplateTagsHintBar) -> None:
        super().__init__(bar)
        self._bar = bar

    def eventFilter(self, obj: QObject, event: QEvent) -> bool:
        etype = event.type()
        if etype == QEvent.Type.FocusIn and obj in self._bar._target_edits:
            self._bar._active_edit = obj
        elif (
            etype == QEvent.Type.MouseButtonRelease
            and getattr(event, "button", lambda: None)() == Qt.MouseButton.LeftButton
            and isinstance(obj, QLabel)
        ):
            token = obj.property("_tag_token")
            if isinstance(token, str) and token:
                self._bar._emit_tag_insert(token)
                return True
        return super().eventFilter(obj, event)


class TemplateTagsHintBar(QWidget):
    """Interactive template token bar displaying supported placeholders as clickable badges."""

    tagClicked = Signal(str)

    def __init__(
        self,
        i18n: Optional[LocalizationManager] = None,
        parent: Optional[QWidget] = None,
    ) -> None:
        super().__init__(parent)
        self._i18n = i18n or LocalizationManager("en-US")
        self._target_edits: list[QWidget] = []
        self._active_edit: Optional[QWidget] = None
        self._filter = _TemplateTagFilter(self)
        self._resize_sync_timer = QTimer(self)
        self._resize_sync_timer.setSingleShot(True)
        self._resize_sync_timer.setInterval(0)
        self._resize_sync_timer.timeout.connect(self._on_resize_sync_timeout)

        sp = QSizePolicy(QSizePolicy.Policy.Expanding, QSizePolicy.Policy.Minimum)
        sp.setHeightForWidth(True)
        self.setSizePolicy(sp)

        self.flow = FlowLayout(self, needAni=False, isTight=False)
        self.flow.setContentsMargins(0, 2, 0, 2)
        self.flow.setHorizontalSpacing(6)
        self.flow.setVerticalSpacing(5)

        self.hint_label = CaptionLabel("", self)
        self.flow.addWidget(self.hint_label)

        self._chips: list[tuple[str, str, QLabel]] = []
        for token, tip_key in _TEMPLATE_TAG_SPECS:
            chip = QLabel(token, self)
            chip.setObjectName("templateTagBadge")
            chip.setProperty("_tag_token", token)
            chip.setCursor(Qt.CursorShape.PointingHandCursor)
            chip.installEventFilter(self._filter)
            chip.installEventFilter(ToolTipFilter(chip, showDelay=120, position=ToolTipPosition.TOP))
            self.flow.addWidget(chip)
            self._chips.append((token, tip_key, chip))

        self.retranslate_ui(self._i18n)

    def bind_target_edits(self, *edits: QWidget) -> None:
        """Bind template LineEdits so clicking any tag badge inserts it into the active field."""
        self._target_edits = [e for e in edits if e is not None]
        if self._target_edits and self._active_edit is None:
            self._active_edit = self._target_edits[0]
        for edit in self._target_edits:
            if not edit.property("_l4d2_tag_focus_hooked"):
                edit.setProperty("_l4d2_tag_focus_hooked", True)
                edit.installEventFilter(self._filter)

    def _emit_tag_insert(self, token: str) -> None:
        self.tagClicked.emit(token)
        target = self._active_edit or (self._target_edits[0] if self._target_edits else None)
        if target is not None and hasattr(target, "insert") and hasattr(target, "setFocus"):
            target.insert(token)
            target.setFocus()

    def hasHeightForWidth(self) -> bool:
        return True

    def heightForWidth(self, width: int) -> int:
        return self.flow.heightForWidth(max(1, width))

    def sizeHint(self) -> QSize:
        w = self.width() if (self.isVisible() and self.width() > 160) else 520
        h = max(26, self.flow.heightForWidth(w))
        return QSize(max(240, w), h)

    def minimumSizeHint(self) -> QSize:
        h = max(26, self.minimumHeight())
        return QSize(160, h)

    def _sync_flow_height(self) -> None:
        w = self.width() if (self.isVisible() and self.width() > 160) else 520
        h = max(26, self.flow.heightForWidth(w))
        if h != self.minimumHeight():
            self.setMinimumHeight(h)
            self.updateGeometry()
            parent = self.parentWidget()
            if parent is not None and parent.layout() is not None:
                parent.layout().invalidate()

    def showEvent(self, event) -> None:
        super().showEvent(event)
        QTimer.singleShot(0, self._sync_flow_height)

    def _on_resize_sync_timeout(self) -> None:
        if self.isVisible() and self.width() > 160:
            self._sync_flow_height()

    def resizeEvent(self, event) -> None:
        super().resizeEvent(event)
        if self.isVisible() and self.width() > 160:
            self._resize_sync_timer.start()

    def retranslate_ui(self, i18n: LocalizationManager) -> None:
        self._i18n = i18n
        is_dark = isDarkTheme()
        muted = COLORS.dark_muted if is_dark else COLORS.light_muted
        fg = COLORS.dark_text if is_dark else COLORS.light_text
        border = COLORS.dark_border if is_dark else COLORS.light_border

        self.hint_label.setText(i18n.tr("meta_tags_hint_title"))
        self.hint_label.setStyleSheet(f"color: {muted}; font-size: 12px; padding-top: 2px;")

        qss_tpl = (
            f"QLabel#templateTagBadge {{ background-color: {{bg}}; border: 1px solid {border}; "
            f"border-radius: 5px; color: {fg}; font-family: Consolas, 'Cascadia Mono', monospace; "
            f"font-size: 11px; font-weight: 600; padding: 2px 7px; }}"
        )
        for _token, tip_key, chip in self._chips:
            chip.setToolTip(wrap_tooltip_text(i18n.tr(tip_key)))
            L4d2ThemeManager.install_surface_motion(chip, qss_tpl, tone="neutral")


class TemplatePreviewCard(QFrame):
    """Structured live-preview panel showing resulting .vpk names and AddonTitles cleanly."""

    def __init__(
        self,
        i18n: Optional[LocalizationManager] = None,
        parent: Optional[QWidget] = None,
    ) -> None:
        super().__init__(parent)
        self.setObjectName("templatePreviewCard")
        self._i18n = i18n or LocalizationManager("en-US")
        self.setSizePolicy(QSizePolicy.Policy.Expanding, QSizePolicy.Policy.Minimum)
        self._resize_sync_timer = QTimer(self)
        self._resize_sync_timer.setSingleShot(True)
        self._resize_sync_timer.setInterval(0)
        self._resize_sync_timer.timeout.connect(self._on_resize_sync_timeout)

        root = QVBoxLayout(self)
        root.setContentsMargins(12, 9, 12, 9)
        root.setSpacing(6)

        hdr = QHBoxLayout()
        hdr.setContentsMargins(0, 0, 0, 0)
        hdr.setSpacing(6)
        self.header_icon = IconWidget(FluentIcon.VIEW, self)
        self.header_icon.setFixedSize(13, 13)
        self.header_title = StrongBodyLabel("", self)
        self.status_badge = QLabel("", self)
        self.status_badge.setObjectName("templatePreviewBadge")
        hdr.addWidget(self.header_icon, 0, Qt.AlignmentFlag.AlignVCenter)
        hdr.addWidget(self.header_title, 0, Qt.AlignmentFlag.AlignVCenter)
        hdr.addStretch(1)
        hdr.addWidget(self.status_badge, 0, Qt.AlignmentFlag.AlignVCenter)
        root.addLayout(hdr)

        self.rows_host = QWidget(self)
        self.rows_lay = QVBoxLayout(self.rows_host)
        self.rows_lay.setContentsMargins(0, 1, 0, 0)
        self.rows_lay.setSpacing(4)
        root.addWidget(self.rows_host)

        self.more_label = CaptionLabel("", self)
        self.more_label.setWordWrap(True)
        self.more_label.setVisible(False)
        self.more_label.installEventFilter(
            ToolTipFilter(self.more_label, showDelay=120, position=ToolTipPosition.TOP)
        )
        root.addWidget(self.more_label)

    def _clear_rows(self) -> None:
        while self.rows_lay.count():
            item = self.rows_lay.takeAt(0)
            w = item.widget()
            if w is not None:
                w.setParent(None)
                w.deleteLater()

    def _make_key_badge(self, text: str, bg: str, border: str, fg: str, min_w: int = 48) -> QLabel:
        badge = QLabel(text, self.rows_host)
        badge.setAlignment(Qt.AlignmentFlag.AlignCenter)
        badge.setMinimumWidth(min_w)
        badge.setStyleSheet(
            f"QLabel {{ background-color: {bg}; border: 1px solid {border}; border-radius: 4px; "
            f"color: {fg}; font-size: 10px; font-weight: 700; padding: 1px 6px; }}"
        )
        return badge

    def update_preview(
        self,
        file_template: str,
        title_template: str,
        orig_title: str,
        origin_id: Optional[SurvivorId],
        dest_ids: list[SurvivorId],
        i18n: LocalizationManager,
        fallback_stem: str = "my_mod",
        sanitize_origin: bool = True,
        max_targets: Optional[int] = None,
    ) -> None:
        """Rebuild structured output filename and AddonTitle rows using SwapEngine rules."""
        self._i18n = i18n
        is_dark = isDarkTheme()
        text_fg = COLORS.dark_text if is_dark else COLORS.light_text
        muted_fg = COLORS.dark_muted if is_dark else COLORS.light_muted
        border_fg = COLORS.dark_border if is_dark else COLORS.light_border
        pill_bg = COLORS.dark_card_alt if is_dark else COLORS.light_card_alt

        L4d2ThemeManager.install_surface_motion(
            self,
            f"QFrame#templatePreviewCard {{ background-color: {{bg}}; border: 1px solid {border_fg}; border-radius: 7px; }}",
            tone="card",
        )
        self.header_title.setText(i18n.tr("meta_preview_header_title"))
        self.header_title.setStyleSheet(f"color: {text_fg}; font-size: 12px; font-weight: 700; border: none; background: transparent;")

        o_spec = SurvivorRegistry.get(origin_id or SurvivorId.ZOEY)

        def render_one(dest: SurvivorId, multi: bool) -> tuple[str, str, str]:
            return render_target_output_preview(
                file_template=file_template,
                title_template=title_template,
                orig_title=orig_title,
                origin_id=origin_id,
                dest=dest,
                multi_target=multi,
                fallback_stem=fallback_stem,
                sanitize_origin=sanitize_origin,
            )

        self._clear_rows()

        if not dest_ids or len(dest_ids) == 1:
            is_sample = not dest_ids
            if is_sample:
                sample_dest = SurvivorId.COACH if o_spec.id != SurvivorId.COACH else SurvivorId.NICK
                if o_spec.id == SurvivorId.ZOEY:
                    sample_dest = SurvivorId.NICK
                _, out_file, title_text = render_one(sample_dest, True)
                badge_text = i18n.tr("meta_preview_sample_badge")
            else:
                _, out_file, title_text = render_one(dest_ids[0], False)
                badge_text = i18n.tr_plural("meta_preview_file_count", 1)

            self.status_badge.setText(badge_text)
            self.status_badge.setStyleSheet(
                f"QLabel#templatePreviewBadge {{ background-color: {pill_bg}; border: 1px solid {border_fg}; "
                f"border-radius: 4px; color: {muted_fg}; font-size: 10px; font-weight: 600; padding: 1px 7px; }}"
            )

            for key_lbl, val_txt, is_mono in (
                (i18n.tr("meta_preview_lbl_vpk"), f"{out_file}.vpk", True),
                (i18n.tr("meta_preview_lbl_title"), title_text, False),
            ):
                row_w = QWidget(self.rows_host)
                row_l = QHBoxLayout(row_w)
                row_l.setContentsMargins(0, 0, 0, 0)
                row_l.setSpacing(8)
                row_l.addWidget(self._make_key_badge(key_lbl, pill_bg, border_fg, muted_fg, min_w=46), 0, Qt.AlignmentFlag.AlignTop)
                val_lbl = QLabel(val_txt, row_w)
                val_lbl.setWordWrap(True)
                font_css = "font-family: Consolas, 'Cascadia Mono', monospace; font-weight: 600; " if is_mono else ""
                val_lbl.setStyleSheet(
                    f"color: {text_fg if is_mono else muted_fg}; {font_css}font-size: 12px; border: none; background: transparent;"
                )
                row_l.addWidget(val_lbl, 1, Qt.AlignmentFlag.AlignVCenter)
                row_w.setVisible(True)
                self.rows_lay.addWidget(row_w)

            self.more_label.setVisible(False)
            self.more_label.setToolTip("")
            self._sync_card_height()
            QTimer.singleShot(0, self._sync_card_height)
            return

        self.status_badge.setText(i18n.tr_plural("meta_preview_file_count", len(dest_ids)))
        self.status_badge.setStyleSheet(
            f"QLabel#templatePreviewBadge {{ background-color: {pill_bg}; border: 1px solid {border_fg}; "
            f"border-radius: 4px; color: {text_fg}; font-size: 10px; font-weight: 700; padding: 1px 7px; }}"
        )

        shown = dest_ids if max_targets is None else dest_ids[:max(1, max_targets)]
        for dest in shown:
            name, out_file, title_text = render_one(dest, True)
            row_w = QWidget(self.rows_host)
            row_l = QHBoxLayout(row_w)
            row_l.setContentsMargins(0, 0, 0, 0)
            row_l.setSpacing(8)
            row_l.addWidget(self._make_key_badge(name, pill_bg, border_fg, text_fg, min_w=64), 0, Qt.AlignmentFlag.AlignVCenter)
            file_lbl = QLabel(f"{out_file}.vpk", row_w)
            file_lbl.setStyleSheet(
                f"color: {text_fg}; font-family: Consolas, 'Cascadia Mono', monospace; "
                f"font-size: 11.5px; font-weight: 600; border: none; background: transparent;"
            )
            arrow_lbl = QLabel("\u2192", row_w)
            arrow_lbl.setStyleSheet(f"color: {muted_fg}; font-size: 11px; border: none; background: transparent;")
            ttl_lbl = QLabel(title_text, row_w)
            ttl_lbl.setWordWrap(True)
            ttl_lbl.setStyleSheet(f"color: {muted_fg}; font-size: 11.5px; border: none; background: transparent;")
            row_l.addWidget(file_lbl, 0, Qt.AlignmentFlag.AlignVCenter)
            row_l.addWidget(arrow_lbl, 0, Qt.AlignmentFlag.AlignVCenter)
            row_l.addWidget(ttl_lbl, 1, Qt.AlignmentFlag.AlignVCenter)
            row_w.setVisible(True)
            self.rows_lay.addWidget(row_w)

        remaining = dest_ids[len(shown):]
        if remaining:
            names = ", ".join(SurvivorRegistry.get(d).display_name for d in remaining)
            more_txt = i18n.tr_plural("meta_tags_preview_more", len(remaining), names=names).strip()
            self.more_label.setText(more_txt)
            self.more_label.setStyleSheet(f"color: {muted_fg}; font-size: 11px; border: none; background: transparent;")
            full_tip = format_template_preview(
                file_template=file_template,
                title_template=title_template,
                orig_title=orig_title,
                origin_id=origin_id,
                dest_ids=dest_ids,
                i18n=i18n,
                fallback_stem=fallback_stem,
                sanitize_origin=sanitize_origin,
                max_targets=8,
            )
            self.more_label.setToolTip(wrap_tooltip_text(full_tip, width=64))
            self.more_label.setVisible(True)
        else:
            self.more_label.setVisible(False)
            self.more_label.setToolTip("")
        self._sync_card_height()
        QTimer.singleShot(0, self._sync_card_height)

    def _sync_card_height(self) -> None:
        self.rows_lay.invalidate()
        self.rows_lay.activate()
        self.rows_host.updateGeometry()
        root_lay = self.layout()
        if root_lay is not None:
            root_lay.invalidate()
            root_lay.activate()
            target_h = max(62, root_lay.totalSizeHint().height())
        else:
            target_h = max(62, self.sizeHint().height())
        if target_h != self.minimumHeight():
            self.setMinimumHeight(target_h)
        self.updateGeometry()
        ancestor = self.parentWidget()
        while ancestor is not None:
            if ancestor.layout() is not None:
                ancestor.layout().invalidate()
                ancestor.layout().activate()
            ancestor.updateGeometry()
            if ancestor.objectName() in {"l4d2SwapContainer", "batchSwapContainer"}:
                break
            ancestor = ancestor.parentWidget()

    def _on_resize_sync_timeout(self) -> None:
        if self.isVisible():
            self._sync_card_height()

    def resizeEvent(self, event) -> None:
        super().resizeEvent(event)
        if self.isVisible():
            self._resize_sync_timer.start()


def update_template_preview_card(
    card: TemplatePreviewCard,
    compat_label: QLabel,
    file_template: str,
    title_template: str,
    orig_title: str,
    origin_id: Optional[SurvivorId],
    dest_ids: list[SurvivorId],
    i18n: LocalizationManager,
    fallback_stem: str = "my_mod",
    sanitize_origin: bool = True,
    max_targets: Optional[int] = None,
) -> None:
    """Update both the visual TemplatePreviewCard and its compatibility plain-text label."""
    update_template_preview_label(
        compat_label,
        file_template=file_template,
        title_template=title_template,
        orig_title=orig_title,
        origin_id=origin_id,
        dest_ids=dest_ids,
        i18n=i18n,
        fallback_stem=fallback_stem,
        sanitize_origin=sanitize_origin,
        max_targets=max_targets,
    )
    card.update_preview(
        file_template=file_template,
        title_template=title_template,
        orig_title=orig_title,
        origin_id=origin_id,
        dest_ids=dest_ids,
        i18n=i18n,
        fallback_stem=fallback_stem,
        sanitize_origin=sanitize_origin,
        max_targets=max_targets,
    )


class ConversionOptionsGroupPanel(FlowPanel):
    """Two categorized sub-cards grouping model asset and output/metadata toggles compactly."""

    def __init__(
        self,
        install_default: bool = False,
        sanitize_default: bool = True,
        fallback_width: int = 620,
        i18n: Optional[LocalizationManager] = None,
        parent: Optional[QWidget] = None,
    ) -> None:
        super().__init__(h_space=12, v_space=10, parent=parent, is_tight=True)
        self.setObjectName("conversionOptionsGroupPanel")
        self._i18n = i18n or LocalizationManager("en-US")
        self._fallback_width = fallback_width

        self.assets_card, assets_lay, self.assets_header_label = self._make_group_card(
            FluentIcon.EMOJI_TAB_SYMBOLS
        )
        self.arms_row, self.switch_arms, self.help_arms = create_switch_with_help(
            "", True, "", self.assets_card
        )
        self.vgui_row, self.switch_vgui, self.help_vgui = create_switch_with_help(
            "", True, "", self.assets_card
        )
        self.weapons_row, self.switch_weapons, self.help_weapons = create_switch_with_help(
            "", True, "", self.assets_card
        )
        self.weapons_row.setVisible(False)
        assets_lay.addWidget(self.arms_row)
        assets_lay.addWidget(self.vgui_row)
        assets_lay.addWidget(self.weapons_row)
        assets_lay.addStretch(1)

        self.output_card, output_lay, self.output_header_label = self._make_group_card(
            FluentIcon.FOLDER
        )
        self.install_row, self.switch_install, self.help_install = create_switch_with_help(
            "", install_default, "", self.output_card
        )
        self.sanitize_row, self.switch_sanitize, self.help_sanitize = create_switch_with_help(
            "", sanitize_default, "", self.output_card
        )
        output_lay.addWidget(self.install_row)
        output_lay.addWidget(self.sanitize_row)
        output_lay.addStretch(1)

        self.flow.addWidget(self.assets_card)
        self.flow.addWidget(self.output_card)
        self.retranslate_ui(self._i18n)

    def _make_group_card(self, icon: FluentIcon) -> tuple[QFrame, QVBoxLayout, CaptionLabel]:
        card = QFrame(self)
        card.setObjectName("optionsGroupCard")
        card.setMinimumWidth(260)
        card.setSizePolicy(QSizePolicy.Policy.Preferred, QSizePolicy.Policy.Minimum)
        lay = QVBoxLayout(card)
        lay.setContentsMargins(12, 9, 12, 10)
        lay.setSpacing(7)
        hdr = QHBoxLayout()
        hdr.setContentsMargins(0, 0, 0, 1)
        hdr.setSpacing(6)
        ico = IconWidget(icon, card)
        ico.setFixedSize(13, 13)
        title_lbl = CaptionLabel("", card)
        hdr.addWidget(ico, 0, Qt.AlignmentFlag.AlignVCenter)
        hdr.addWidget(title_lbl, 0, Qt.AlignmentFlag.AlignVCenter)
        hdr.addStretch(1)
        lay.addLayout(hdr)
        return card, lay, title_lbl

    def retranslate_ui(self, i18n: LocalizationManager) -> None:
        self._i18n = i18n
        is_dark = isDarkTheme()
        border = COLORS.dark_border if is_dark else COLORS.light_border
        muted = COLORS.dark_muted if is_dark else COLORS.light_muted
        sub_qss = (
            f"QFrame#optionsGroupCard {{ background-color: {{bg}}; border: 1px solid {border}; border-radius: 6px; }}"
        )
        for card in (self.assets_card, self.output_card):
            L4d2ThemeManager.install_surface_motion(card, sub_qss, tone="neutral")
        hdr_qss = (
            f"color: {muted}; font-size: 10.5px; font-weight: 700; "
            f"letter-spacing: 0.5px; border: none; background: transparent;"
        )
        self.assets_header_label.setText(i18n.tr("meta_opts_group_assets"))
        self.assets_header_label.setStyleSheet(hdr_qss)
        self.output_header_label.setText(i18n.tr("meta_opts_group_output"))
        self.output_header_label.setStyleSheet(hdr_qss)

        for sw, badge, text_key, help_key in (
            (self.switch_arms, self.help_arms, "switch_arms", "help_arms"),
            (self.switch_vgui, self.help_vgui, "switch_vgui", "help_vgui"),
            (self.switch_weapons, self.help_weapons, "switch_weapons", "help_weapons"),
            (self.switch_install, self.help_install, "switch_install", "help_install"),
            (self.switch_sanitize, self.help_sanitize, "switch_sanitize_origin", "help_sanitize_origin"),
        ):
            update_switch_help(sw, badge, i18n.tr(text_key), i18n.tr(help_key))

        self.assets_card.updateGeometry()
        self.output_card.updateGeometry()
        self.sync_height(fallback_width=max(self._fallback_width, self.width()))


def record_conversion_history(
    history_mgr: HistoryManager,
    mod_title: str,
    author: str,
    source_path: str,
    origin: str,
    destinations: list[str],
    output_dir: str,
    installed_to_addons: bool,
    custom_cover_used: bool,
    results: list[SwapTargetResult],
    fatal_error: str = "",
) -> ConversionHistoryEntry:
    """Persist one completed, partial, or failed conversion run to HistoryManager."""
    outputs = [
        ConversionHistoryOutput(
            destination=r.destination.value,
            success=r.success,
            cancelled=r.cancelled,
            vpk_path=str(r.vpk_path) if r.vpk_path else "",
            error_message=r.error_message or "",
            warnings=list(r.warnings),
        )
        for r in results
    ]
    if fatal_error and not outputs:
        outputs = [
            ConversionHistoryOutput(
                destination=dest,
                success=False,
                error_message=fatal_error.splitlines()[0],
            )
            for dest in destinations
        ]
    entry = ConversionHistoryEntry(
        entry_id=uuid.uuid4().hex[:12],
        created_at=datetime.now().strftime("%Y-%m-%d %H:%M:%S"),
        mod_title=mod_title,
        author=author,
        source_path=source_path,
        origin=origin,
        destinations=list(destinations),
        output_dir=output_dir,
        installed_to_addons=installed_to_addons,
        custom_cover_used=custom_cover_used,
        outputs=outputs,
    )
    history_mgr.add_entry(entry)
    return entry
