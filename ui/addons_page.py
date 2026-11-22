from __future__ import annotations

import os
from pathlib import Path
from typing import Callable, Optional

from PySide6.QtCore import QEasingCurve, QRectF, QThread, QUrl, QVariantAnimation, Qt, Signal
from PySide6.QtGui import QColor, QDesktopServices, QPainter, QPen
from PySide6.QtWidgets import (
    QGridLayout,
    QHBoxLayout,
    QVBoxLayout,
    QWidget,
)
from qfluentwidgets import (
    BodyLabel,
    CaptionLabel,
    ComboBox,
    FluentIcon,
    HeaderCardWidget,
    IconWidget,
    InfoBar,
    InfoBarPosition,
    LineEdit,
    MessageBox,
    PushButton,
    ScrollArea,
    StrongBodyLabel,
    SubtitleLabel,
    isDarkTheme,
)

from core.addons_scanner import AddonsScanner
from core.i18n import LocalizationManager
from core.models import EnvironmentStatus, InstalledAddonEntry, SurvivorId
from core.survivors import SurvivorRegistry
from ui.addon_ui_shared import (
    AddonPreviewInspector,
    AddonsScanWorker,
    create_styled_mod_table,
    filter_addon_entries,
    launch_l4d2_steam,
    populate_addon_table,
    set_addon_table_headers,
    shutdown_worker_thread,
)
from ui.theme import COLORS, L4d2ThemeManager
from ui.widgets import add_card_header_icon, lerp_color


class _SlotStatusCard(QWidget):
    """Clickable summary card showing active mod or conflict status with animated hover feedback."""

    clicked = Signal(object)

    def __init__(self, survivor_id: SurvivorId, parent: Optional[QWidget] = None) -> None:
        super().__init__(parent)
        self.survivor_id = survivor_id
        self.setObjectName("slotLoadoutCard")
        self.setAttribute(Qt.WidgetAttribute.WA_Hover, True)
        self.setCursor(Qt.CursorShape.PointingHandCursor)

        self._state_kind: str = "vanilla"
        self._selected: bool = False
        self._hover_t: float = 0.0
        self._hover_anim = QVariantAnimation(self)
        self._hover_anim.setDuration(150)
        self._hover_anim.setEasingCurve(QEasingCurve.Type.OutCubic)
        self._hover_anim.valueChanged.connect(self._on_hover_anim_value)

        lay = QVBoxLayout(self)
        lay.setContentsMargins(10, 8, 10, 8)
        lay.setSpacing(3)

        spec = SurvivorRegistry.get(survivor_id)
        self.name_label = StrongBodyLabel(f"{spec.display_name} ({spec.generation})", self)
        self.name_label.setAttribute(Qt.WidgetAttribute.WA_TransparentForMouseEvents, True)
        self.status_label = CaptionLabel("", self)
        self.status_label.setAttribute(Qt.WidgetAttribute.WA_TransparentForMouseEvents, True)
        self.status_label.setWordWrap(True)
        lay.addWidget(self.name_label)
        lay.addWidget(self.status_label)

    def _on_hover_anim_value(self, value: float) -> None:
        self._hover_t = float(value)
        self.update()

    def set_selected(self, selected: bool) -> None:
        if self._selected == selected:
            return
        self._selected = selected
        self.update()

    def enterEvent(self, event) -> None:
        super().enterEvent(event)
        self._hover_anim.stop()
        self._hover_anim.setStartValue(self._hover_t)
        self._hover_anim.setEndValue(1.0)
        self._hover_anim.start()

    def leaveEvent(self, event) -> None:
        super().leaveEvent(event)
        self._hover_anim.stop()
        self._hover_anim.setStartValue(self._hover_t)
        self._hover_anim.setEndValue(0.0)
        self._hover_anim.start()

    def mousePressEvent(self, event) -> None:
        if event.button() == Qt.MouseButton.LeftButton:
            self.clicked.emit(self.survivor_id)
        super().mousePressEvent(event)

    def set_slot_state(self, active_entries: list[InstalledAddonEntry], i18n: LocalizationManager) -> None:
        is_dark = isDarkTheme()
        if not active_entries:
            self.status_label.setText(i18n.tr("addons_page_slot_vanilla"))
            self._state_kind = "vanilla"
            text_color = COLORS.dark_muted if is_dark else COLORS.light_muted
        elif len(active_entries) == 1:
            self.status_label.setText(i18n.tr("addons_page_slot_active", title=active_entries[0].title))
            self._state_kind = "active"
            text_color = "#4ADE80" if is_dark else "#15803D"
        else:
            self.status_label.setText(i18n.tr("addons_page_slot_conflict", count=len(active_entries)))
            self._state_kind = "conflict"
            text_color = COLORS.amber if is_dark else COLORS.red

        title_color = COLORS.dark_text if is_dark else COLORS.light_text
        self.name_label.setStyleSheet(f"color: {title_color}; background: transparent;")
        self.status_label.setStyleSheet(f"color: {text_color}; background: transparent;")
        self.update()

    def paintEvent(self, _event) -> None:
        painter = QPainter(self)
        painter.setRenderHint(QPainter.Antialiasing)
        is_dark = isDarkTheme()
        rect = QRectF(self.rect()).adjusted(1.2, 1.2, -1.2, -1.2)
        idle_bg = QColor(COLORS.dark_card_alt if is_dark else COLORS.light_card_alt)

        if self._state_kind == "active":
            idle_border = QColor("#22C55E" if is_dark else "#15803D")
            hover_border = QColor("#4ADE80" if is_dark else "#16A34A")
            hover_bg = QColor("#183224" if is_dark else "#DCFCE7")
        elif self._state_kind == "conflict":
            idle_border = QColor(COLORS.amber if is_dark else COLORS.red)
            hover_border = QColor(COLORS.amber_bright if is_dark else COLORS.red_hover)
            hover_bg = QColor("#302310" if is_dark else "#FEE2E2")
        else:
            idle_border = QColor(COLORS.dark_border if is_dark else COLORS.light_border)
            hover_border = QColor(COLORS.amber if is_dark else "#C98E00")
            hover_bg = QColor("#282418" if is_dark else "#FCEFC7")

        emphasis = max(self._hover_t, 1.0 if self._selected else 0.0)
        bg = lerp_color(idle_bg, hover_bg, emphasis)
        border = lerp_color(idle_border, hover_border, emphasis)
        border_w = 1.2 + 0.8 * emphasis

        painter.setPen(QPen(border, border_w))
        painter.setBrush(bg)
        painter.drawRoundedRect(rect, 6.0, 6.0)


class AddonsLoadoutPage(ScrollArea):
    """Dedicated page displaying survivor loadout slots and managing addons/workshop VPKs."""

    loadModRequested = Signal(Path)

    def __init__(
        self,
        get_env_fn: Callable[[], EnvironmentStatus],
        i18n: Optional[LocalizationManager] = None,
        parent: Optional[QWidget] = None,
    ) -> None:
        super().__init__(parent)
        self.setObjectName("addonsLoadoutPage")
        self._get_env = get_env_fn
        self._i18n = i18n or LocalizationManager("en-US")
        self._entries: list[InstalledAddonEntry] = []
        self._preview_cache: dict[Path, Optional[bytes]] = {}
        self._scan_thread: Optional[QThread] = None
        self._scan_worker: Optional[AddonsScanWorker] = None
        self._slot_cards: dict[SurvivorId, _SlotStatusCard] = {}

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
        self.title_icon = IconWidget(FluentIcon.GAME, self.view)
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
        self.open_folder_btn = PushButton(FluentIcon.FOLDER, "", self.view)
        self.launch_l4d2_btn = PushButton(FluentIcon.PLAY_SOLID, "", self.view)

        header_row.addLayout(title_col, 1)
        header_row.addWidget(self.refresh_btn)
        header_row.addWidget(self.open_folder_btn)
        header_row.addWidget(self.launch_l4d2_btn)
        root.addLayout(header_row)

        self.slots_card = HeaderCardWidget(self.view)
        add_card_header_icon(self.slots_card, FluentIcon.PEOPLE)
        slots_inner = QWidget(self.slots_card)
        slots_grid = QGridLayout(slots_inner)
        slots_grid.setContentsMargins(0, 0, 0, 0)
        slots_grid.setSpacing(8)
        for idx, spec in enumerate(SurvivorRegistry.all()):
            slot_card = _SlotStatusCard(spec.id, slots_inner)
            slot_card.clicked.connect(self._on_slot_card_clicked)
            self._slot_cards[spec.id] = slot_card
            slots_grid.addWidget(slot_card, idx // 4, idx % 4)
        self.slots_card.viewLayout.addWidget(slots_inner)
        root.addWidget(self.slots_card)

        self.status_label = CaptionLabel("", self.view)
        root.addWidget(self.status_label)

        filter_row = QHBoxLayout()
        filter_row.setSpacing(10)
        self.search_edit = LineEdit(self.view)
        self.search_edit.setClearButtonEnabled(True)
        self.source_combo = ComboBox(self.view)
        self.source_combo.setMinimumWidth(140)
        self.filter_combo = ComboBox(self.view)
        self.filter_combo.setMinimumWidth(205)
        self.status_combo = ComboBox(self.view)
        self.status_combo.setMinimumWidth(165)
        filter_row.addWidget(self.search_edit, 3)
        filter_row.addWidget(self.source_combo, 1)
        filter_row.addWidget(self.filter_combo, 1)
        filter_row.addWidget(self.status_combo, 1)
        root.addLayout(filter_row)

        content_row = QHBoxLayout()
        content_row.setSpacing(12)
        self.mod_table = create_styled_mod_table(self.view, ["", "", "", "", ""], min_height=360)
        self.preview_panel = AddonPreviewInspector(self._i18n, self.view)

        self.toggle_enable_btn = PushButton(FluentIcon.COMPLETED, "", self.preview_panel)
        self.load_swap_btn = PushButton(FluentIcon.SYNC, "", self.preview_panel)
        self.delete_vpk_btn = PushButton(FluentIcon.DELETE, "", self.preview_panel)
        self.preview_panel.actions_layout.addWidget(self.toggle_enable_btn)
        self.preview_panel.actions_layout.addWidget(self.load_swap_btn)
        self.preview_panel.actions_layout.addWidget(self.delete_vpk_btn)

        content_row.addWidget(self.mod_table, 1)
        content_row.addWidget(self.preview_panel)
        root.addLayout(content_row, 1)

        self.refresh_btn.clicked.connect(self.refresh_view)
        self.open_folder_btn.clicked.connect(self._on_open_addons)
        self.launch_l4d2_btn.clicked.connect(launch_l4d2_steam)
        self.search_edit.textChanged.connect(self._apply_filter)
        self.source_combo.currentIndexChanged.connect(self._apply_filter)
        self.filter_combo.currentIndexChanged.connect(self._apply_filter)
        self.status_combo.currentIndexChanged.connect(self._apply_filter)
        self.mod_table.itemSelectionChanged.connect(self._on_selection_changed)
        self.mod_table.cellDoubleClicked.connect(lambda _r, _c: self._on_load_in_swapper())
        self.toggle_enable_btn.clicked.connect(self._on_toggle_selected)
        self.load_swap_btn.clicked.connect(self._on_load_in_swapper)
        self.delete_vpk_btn.clicked.connect(self._on_delete_selected)

        self.retranslate_ui(self._i18n)

    def retranslate_ui(self, i18n: LocalizationManager) -> None:
        self._i18n = i18n
        self.page_title.setText(i18n.tr("addons_page_title"))
        self.page_subtitle.setText(i18n.tr("addons_page_subtitle"))
        self.refresh_btn.setText(i18n.tr("addons_page_refresh"))
        self.open_folder_btn.setText(i18n.tr("addons_page_open_folder"))
        self.launch_l4d2_btn.setText(i18n.tr("btn_launch_l4d2"))
        self.slots_card.setTitle(i18n.tr("addons_page_slots_title"))
        self.search_edit.setPlaceholderText(i18n.tr("addons_dlg_search_ph"))

        self.load_swap_btn.setText(i18n.tr("addons_page_btn_load_swap"))
        self.delete_vpk_btn.setText(i18n.tr("addons_page_btn_delete"))

        self._rebuild_combos()
        set_addon_table_headers(self.mod_table, i18n)
        self.preview_panel.apply_theme_colors()
        self.preview_panel.retranslate_ui(i18n)
        self._refresh_slots()
        self._apply_filter()
        L4d2ThemeManager.apply_pointing_hand_cursors(self)

    def _rebuild_combos(self) -> None:
        src_val = self.source_combo.currentData()
        flt_val = self.filter_combo.currentData()
        sts_val = self.status_combo.currentData()

        for combo in (self.source_combo, self.filter_combo, self.status_combo):
            combo.blockSignals(True)
            combo.clear()

        self.source_combo.addItem(self._i18n.tr("addons_dlg_filter_src_all"), userData="")
        self.source_combo.addItem(self._i18n.tr("addons_dlg_src_addons"), userData="addons")
        self.source_combo.addItem(self._i18n.tr("addons_dlg_src_workshop"), userData="workshop")

        self.filter_combo.addItem(self._i18n.tr("addons_dlg_filter_all"), userData="")
        self.filter_combo.addItem(self._i18n.tr("addons_dlg_filter_l4d1"), userData="GEN:L4D1")
        self.filter_combo.addItem(self._i18n.tr("addons_dlg_filter_l4d2"), userData="GEN:L4D2")
        for spec in SurvivorRegistry.all():
            self.filter_combo.addItem(spec.display_name, userData=spec.id.value)

        self.status_combo.addItem(self._i18n.tr("addons_page_filter_status_all"), userData="")
        self.status_combo.addItem(self._i18n.tr("addons_page_filter_status_on"), userData="enabled")
        self.status_combo.addItem(self._i18n.tr("addons_page_filter_status_off"), userData="disabled")

        for combo, prev in (
            (self.source_combo, src_val),
            (self.filter_combo, flt_val),
            (self.status_combo, sts_val),
        ):
            idx = combo.findData(prev)
            if idx >= 0:
                combo.setCurrentIndex(idx)
            combo.blockSignals(False)

    def refresh_view(self) -> None:
        addons_dir = self._get_env().l4d2_addons_dir
        self.open_folder_btn.setEnabled(addons_dir is not None and addons_dir.exists())
        if addons_dir is None or not addons_dir.exists():
            self.populate_entries([])
            self.status_label.setText(self._i18n.tr("addons_page_no_addons_dir"))
            return

        if self._scan_thread is not None and self._scan_thread.isRunning():
            return

        self.status_label.setText(self._i18n.tr("addons_dlg_scanning"))
        self._scan_thread = QThread(self)
        self._scan_worker = AddonsScanWorker(addons_dir)
        self._scan_worker.moveToThread(self._scan_thread)
        self._scan_thread.started.connect(self._scan_worker.run)
        self._scan_worker.finished.connect(self._on_scan_finished)
        self._scan_worker.failed.connect(self._on_scan_failed)
        self._scan_worker.finished.connect(self._scan_thread.quit)
        self._scan_worker.failed.connect(self._scan_thread.quit)
        self._scan_thread.finished.connect(self._cleanup_scan_thread)
        self._scan_thread.start()

    def populate_entries(self, entries: list[InstalledAddonEntry]) -> None:
        self._entries = list(entries)
        for entry in entries:
            if entry.preview_bytes is not None:
                self._preview_cache[entry.vpk_path] = entry.preview_bytes
        if entries:
            self.status_label.setText(self._i18n.tr_plural("addons_dlg_found", len(entries)))
        else:
            self.status_label.setText(self._i18n.tr("addons_dlg_empty"))
        self._refresh_slots()
        self._apply_filter()

    def selected_entry(self) -> Optional[InstalledAddonEntry]:
        row = self.mod_table.currentRow()
        if row < 0:
            return None
        item = self.mod_table.item(row, 1)
        data = item.data(Qt.ItemDataRole.UserRole) if item is not None else None
        return data if isinstance(data, InstalledAddonEntry) else None

    def shutdown_scan(self, timeout_ms: int = 3000) -> None:
        shutdown_worker_thread(
            self._scan_thread,
            self._scan_worker,
            cancel_fn=self._scan_worker.request_cancel if self._scan_worker is not None else None,
            ui_signals=(
                (self._scan_worker.finished, self._scan_worker.failed)
                if self._scan_worker is not None
                else ()
            ),
            timeout_ms=timeout_ms,
        )
        self._scan_worker = None
        self._scan_thread = None

    def _on_scan_finished(self, entries: list[InstalledAddonEntry]) -> None:
        self.populate_entries(entries)

    def _on_scan_failed(self, err: str) -> None:
        self.status_label.setText(self._i18n.tr("addons_dlg_scan_err", error=err))

    def _cleanup_scan_thread(self) -> None:
        if self._scan_worker is not None:
            self._scan_worker.deleteLater()
            self._scan_worker = None
        if self._scan_thread is not None:
            self._scan_thread.deleteLater()
            self._scan_thread = None

    def _refresh_slots(self) -> None:
        for sid, card in self._slot_cards.items():
            active = [
                e for e in self._entries
                if e.enabled_in_game
                and (sid in e.replaced_survivors or (not e.replaced_survivors and e.origin == sid))
            ]
            card.set_slot_state(active, self._i18n)

    def _on_slot_card_clicked(self, survivor_id: SurvivorId) -> None:
        if str(self.filter_combo.currentData() or "") == survivor_id.value:
            self.filter_combo.setCurrentIndex(0)
            return
        idx = self.filter_combo.findData(survivor_id.value)
        if idx >= 0:
            self.filter_combo.setCurrentIndex(idx)

    def _get_preview_bytes(self, entry: InstalledAddonEntry) -> Optional[bytes]:
        if entry.vpk_path not in self._preview_cache:
            self._preview_cache[entry.vpk_path] = (
                entry.preview_bytes
                if entry.preview_bytes is not None
                else AddonsScanner.read_addon_preview_image(entry.vpk_path)
            )
        return self._preview_cache.get(entry.vpk_path)

    def _apply_filter(self) -> None:
        prev_vpk = self.selected_entry().vpk_path if self.selected_entry() else None
        survivor_filter = str(self.filter_combo.currentData() or "")
        for sid, card in self._slot_cards.items():
            card.set_selected(survivor_filter == sid.value)
        matched = filter_addon_entries(
            self._entries,
            query=self.search_edit.text(),
            source_filter=str(self.source_combo.currentData() or ""),
            survivor_filter=survivor_filter,
            status_filter=str(self.status_combo.currentData() or ""),
        )
        populate_addon_table(self.mod_table, matched, self._i18n, self._get_preview_bytes)

        if prev_vpk is not None:
            for row in range(self.mod_table.rowCount()):
                item = self.mod_table.item(row, 1)
                data = item.data(Qt.ItemDataRole.UserRole) if item is not None else None
                if isinstance(data, InstalledAddonEntry) and data.vpk_path == prev_vpk:
                    self.mod_table.selectRow(row)
                    break
        self._on_selection_changed()

    def _on_selection_changed(self) -> None:
        entry = self.selected_entry()
        has_sel = entry is not None
        self.toggle_enable_btn.setEnabled(has_sel)
        self.load_swap_btn.setEnabled(has_sel)
        self.delete_vpk_btn.setEnabled(has_sel)

        if entry is not None:
            if entry.enabled_in_game:
                self.toggle_enable_btn.setIcon(FluentIcon.CLOSE)
                self.toggle_enable_btn.setText(self._i18n.tr("addons_page_btn_disable"))
            else:
                self.toggle_enable_btn.setIcon(FluentIcon.COMPLETED)
                self.toggle_enable_btn.setText(self._i18n.tr("addons_page_btn_enable"))
            self.preview_panel.set_entry(entry, self._get_preview_bytes(entry))
        else:
            self.toggle_enable_btn.setText(self._i18n.tr("addons_page_btn_enable"))
            self.preview_panel.set_entry(None, None)

    def _on_toggle_selected(self) -> None:
        entry = self.selected_entry()
        addons_dir = self._get_env().l4d2_addons_dir
        if entry is None or addons_dir is None:
            return

        new_state = not entry.enabled_in_game
        if new_state:
            try:
                rel = entry.vpk_path.relative_to(addons_dir).as_posix()
            except ValueError:
                rel = entry.vpk_path.name
            AddonsScanner.update_addonlist(addons_dir, disable_entries=[], enable_filenames=[rel])
        else:
            AddonsScanner.update_addonlist(addons_dir, disable_entries=[entry], enable_filenames=[])

        entry.enabled_in_game = new_state
        self._refresh_slots()
        self._apply_filter()
        InfoBar.success(
            self._i18n.tr("addons_page_toggled_title"),
            self._i18n.tr(
                "addons_page_toggled_on" if new_state else "addons_page_toggled_off",
                title=entry.title,
            ),
            parent=self.window(),
            position=InfoBarPosition.TOP,
        )

    def _on_load_in_swapper(self) -> None:
        entry = self.selected_entry()
        if entry is not None:
            self.loadModRequested.emit(entry.vpk_path)

    def _on_delete_selected(self) -> None:
        entry = self.selected_entry()
        if entry is None or not entry.vpk_path.exists():
            return

        msg = self._i18n.tr(
            "addons_page_del_msg",
            name=entry.vpk_path.name,
            path=entry.vpk_path,
        )
        if entry.source_kind == "workshop":
            msg = f"{msg}\n\n{self._i18n.tr('addons_page_del_workshop_warn')}"

        dlg = MessageBox(self._i18n.tr("addons_page_del_title"), msg, self.window())
        L4d2ThemeManager.style_dialog_yes_button(dlg.yesButton, self._i18n.tr("addons_page_btn_delete"), FluentIcon.DELETE)
        L4d2ThemeManager.style_dialog_cancel_button(dlg.cancelButton, self._i18n.tr("addons_dlg_cancel"))
        if not dlg.exec():
            return

        try:
            entry.vpk_path.unlink()
        except OSError as exc:
            InfoBar.error(
                self._i18n.tr("addons_page_del_title"),
                self._i18n.tr("addons_page_del_err", error=exc),
                parent=self.window(),
                position=InfoBarPosition.TOP,
                duration=6000,
            )
            return

        self._preview_cache.pop(entry.vpk_path, None)
        self._entries = [e for e in self._entries if e.vpk_path != entry.vpk_path]
        self._refresh_slots()
        self._apply_filter()
        InfoBar.success(
            self._i18n.tr("addons_page_del_title"),
            self._i18n.tr("addons_page_del_ok", name=entry.vpk_path.name),
            parent=self.window(),
            position=InfoBarPosition.TOP,
        )

    def _on_open_addons(self) -> None:
        addons_dir = self._get_env().l4d2_addons_dir
        if addons_dir and addons_dir.exists():
            try:
                os.startfile(str(addons_dir))
            except OSError:
                QDesktopServices.openUrl(QUrl.fromLocalFile(str(addons_dir)))
