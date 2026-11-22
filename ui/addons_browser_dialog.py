from __future__ import annotations

from pathlib import Path
from typing import Optional

from PySide6.QtCore import QThread, Qt
from PySide6.QtWidgets import QAbstractItemView, QHBoxLayout, QListWidgetItem, QWidget
from qfluentwidgets import (
    BodyLabel,
    CaptionLabel,
    ComboBox,
    FluentIcon,
    LineEdit,
    MessageBoxBase,
    PushButton,
    SubtitleLabel,
)

from core.addons_scanner import AddonsScanner
from core.i18n import LocalizationManager
from core.models import AddonConflict, InstalledAddonEntry
from core.survivors import SurvivorRegistry
from ui.addon_ui_shared import (
    AddonPreviewInspector,
    AddonsScanWorker,
    create_styled_list_widget,
    create_styled_mod_table,
    filter_addon_entries,
    populate_addon_table,
    set_addon_table_headers,
    shutdown_worker_thread,
)
from ui.theme import L4d2ThemeManager
from ui.widgets import ImageZoomDialog, create_icon_row


AddonImageZoomDialog = ImageZoomDialog


class AddonsBrowserDialog(MessageBoxBase):
    """Searchable browser for picking a survivor mod directly from L4D2 addons & workshop."""

    def __init__(
        self,
        addons_dir: Path,
        i18n: Optional[LocalizationManager] = None,
        parent: Optional[QWidget] = None,
        auto_scan: bool = True,
        multi_select: bool = False,
    ) -> None:
        super().__init__(parent)
        self.addons_dir = addons_dir
        self._i18n = i18n or LocalizationManager("en-US")
        self._multi_select = multi_select
        self._entries: list[InstalledAddonEntry] = []
        self._preview_cache: dict[Path, Optional[bytes]] = {}
        self._scan_thread: Optional[QThread] = None
        self._scan_worker: Optional[AddonsScanWorker] = None

        self.widget.setMinimumWidth(1020)

        self.title_label = SubtitleLabel(self._i18n.tr("addons_dlg_title"), self.widget)
        self.status_label = CaptionLabel(self._i18n.tr("addons_dlg_scanning"), self.widget)

        filter_row = QHBoxLayout()
        filter_row.setSpacing(10)
        self.search_edit = LineEdit(self.widget)
        self.search_edit.setClearButtonEnabled(True)
        self.search_edit.setPlaceholderText(self._i18n.tr("addons_dlg_search_ph"))

        self.source_combo = ComboBox(self.widget)
        self.source_combo.setMinimumWidth(145)
        self.source_combo.addItem(self._i18n.tr("addons_dlg_filter_src_all"), userData="")
        self.source_combo.addItem(self._i18n.tr("addons_dlg_src_addons"), userData="addons")
        self.source_combo.addItem(self._i18n.tr("addons_dlg_src_workshop"), userData="workshop")

        self.filter_combo = ComboBox(self.widget)
        self.filter_combo.setMinimumWidth(190)
        self.filter_combo.addItem(self._i18n.tr("addons_dlg_filter_all"), userData="")
        self.filter_combo.addItem(self._i18n.tr("addons_dlg_filter_l4d1"), userData="GEN:L4D1")
        self.filter_combo.addItem(self._i18n.tr("addons_dlg_filter_l4d2"), userData="GEN:L4D2")
        for spec in SurvivorRegistry.all():
            self.filter_combo.addItem(spec.display_name, userData=spec.id.value)

        filter_row.addWidget(self.search_edit, 3)
        filter_row.addWidget(self.source_combo, 1)
        filter_row.addWidget(self.filter_combo, 1)

        self.mod_table = create_styled_mod_table(self.widget, ["", "", "", "", ""], min_height=410)
        set_addon_table_headers(self.mod_table, self._i18n)
        if self._multi_select:
            self.mod_table.setSelectionMode(QAbstractItemView.SelectionMode.ExtendedSelection)

        self.preview_panel = AddonPreviewInspector(self._i18n, self.widget)
        self.preview_image_label = self.preview_panel.preview_image_label
        self.zoom_btn = self.preview_panel.zoom_btn
        self.preview_title_label = self.preview_panel.preview_title_label
        self.preview_meta_label = self.preview_panel.preview_meta_label

        content_row = QHBoxLayout()
        content_row.setSpacing(12)
        content_row.addWidget(self.mod_table, 1)
        content_row.addWidget(self.preview_panel)

        self.viewLayout.addLayout(
            create_icon_row(FluentIcon.GAME, self.title_label, self.widget, size=20, spacing=10)
        )
        self.viewLayout.addWidget(self.status_label)
        self.viewLayout.addLayout(filter_row)
        self.viewLayout.addLayout(content_row)

        L4d2ThemeManager.style_dialog_yes_button(
            self.yesButton,
            self._i18n.tr("addons_dlg_select_multi" if self._multi_select else "addons_dlg_select"),
        )
        L4d2ThemeManager.style_dialog_cancel_button(
            self.cancelButton,
            self._i18n.tr("addons_dlg_cancel"),
        )
        self.yesButton.setEnabled(False)

        self.search_edit.textChanged.connect(self._apply_filter)
        self.source_combo.currentIndexChanged.connect(self._apply_filter)
        self.filter_combo.currentIndexChanged.connect(self._apply_filter)
        self.mod_table.itemSelectionChanged.connect(self._on_selection_changed)
        self.mod_table.cellDoubleClicked.connect(self._on_row_double_clicked)

        L4d2ThemeManager.apply_pointing_hand_cursors(self)
        if auto_scan:
            self.start_scan()

    def start_scan(self) -> None:
        if self._scan_thread is not None and self._scan_thread.isRunning():
            return

        self.status_label.setText(self._i18n.tr("addons_dlg_scanning"))
        self._scan_thread = QThread(self)
        self._scan_worker = AddonsScanWorker(self.addons_dir)
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
        self._apply_filter()

    def selected_entries(self) -> list[InstalledAddonEntry]:
        sel_model = self.mod_table.selectionModel()
        if sel_model is None:
            single = self.selected_entry()
            return [single] if single is not None else []
        rows = sorted({idx.row() for idx in sel_model.selectedRows()})
        entries: list[InstalledAddonEntry] = []
        for row in rows:
            item = self.mod_table.item(row, 1)
            data = item.data(Qt.ItemDataRole.UserRole) if item is not None else None
            if isinstance(data, InstalledAddonEntry):
                entries.append(data)
        return entries

    def selected_entry(self) -> Optional[InstalledAddonEntry]:
        row = self.mod_table.currentRow()
        if row < 0:
            return None
        item = self.mod_table.item(row, 1)
        if item is None:
            return None
        data = item.data(Qt.ItemDataRole.UserRole)
        return data if isinstance(data, InstalledAddonEntry) else None

    def validate(self) -> bool:
        return bool(self.selected_entries()) if self._multi_select else (self.selected_entry() is not None)

    def done(self, r: int) -> None:
        self._shutdown_scan_thread()
        super().done(r)

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

    def _shutdown_scan_thread(self, timeout_ms: int = 3000) -> None:
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

    def _on_selection_changed(self) -> None:
        entry = self.selected_entry()
        has_sel = bool(self.selected_entries()) if self._multi_select else (entry is not None)
        self.yesButton.setEnabled(has_sel)
        if entry is None and self._multi_select:
            entries = self.selected_entries()
            entry = entries[0] if entries else None
        raw_img = self._get_preview_bytes(entry) if entry is not None else None
        self.preview_panel.set_entry(entry, raw_img)

    def _get_preview_bytes(self, entry: InstalledAddonEntry) -> Optional[bytes]:
        if entry.vpk_path not in self._preview_cache:
            self._preview_cache[entry.vpk_path] = (
                entry.preview_bytes
                if entry.preview_bytes is not None
                else AddonsScanner.read_addon_preview_image(entry.vpk_path)
            )
        return self._preview_cache.get(entry.vpk_path)

    def _on_row_double_clicked(self, row: int, _col: int) -> None:
        item = self.mod_table.item(row, 1)
        if item is not None and isinstance(item.data(Qt.ItemDataRole.UserRole), InstalledAddonEntry):
            self.accept()

    def _apply_filter(self) -> None:
        matched = filter_addon_entries(
            self._entries,
            query=self.search_edit.text(),
            source_filter=str(self.source_combo.currentData() or ""),
            survivor_filter=str(self.filter_combo.currentData() or ""),
        )
        populate_addon_table(self.mod_table, matched, self._i18n, self._get_preview_bytes)
        self._on_selection_changed()


class AddonConflictDialog(MessageBoxBase):
    """Interactive conflict resolver offering to disable conflicting L4D2 mods before installing."""

    def __init__(
        self,
        conflicts: list[AddonConflict],
        i18n: Optional[LocalizationManager] = None,
        parent: Optional[QWidget] = None,
    ) -> None:
        super().__init__(parent)
        self._i18n = i18n or LocalizationManager("en-US")
        self.choice: str = "cancel"

        self.widget.setMinimumWidth(640)

        self.title_label = SubtitleLabel(self._i18n.tr("conflict_dlg_title"), self.widget)
        unique_targets = len({conflict.target_survivor for conflict in conflicts})
        if len(conflicts) == 1:
            intro_key = "conflict_dlg_intro_one"
        elif unique_targets <= 1:
            intro_key = "conflict_dlg_intro_many_single"
        else:
            intro_key = "conflict_dlg_intro_many_multi"
        self.intro_label = BodyLabel(self._i18n.tr(intro_key), self.widget)
        self.intro_label.setWordWrap(True)

        self.conflict_list = create_styled_list_widget(self.widget, min_height=130, max_height=240)
        for conflict in conflicts:
            entry = conflict.existing_addon
            target_name = SurvivorRegistry.get(conflict.target_survivor).display_name
            source_tag = self._i18n.tr(
                "addons_dlg_src_workshop"
                if entry.source_kind == "workshop"
                else "addons_dlg_src_addons"
            )
            line = f"[{target_name}] {entry.title}  ({source_tag}: {entry.vpk_path.name})"
            item = QListWidgetItem(line)
            item.setToolTip(str(entry.vpk_path))
            self.conflict_list.addItem(item)

        self.viewLayout.addLayout(
            create_icon_row(FluentIcon.INFO, self.title_label, self.widget, size=20, spacing=10)
        )
        self.viewLayout.addWidget(self.intro_label)
        self.viewLayout.addWidget(self.conflict_list)

        L4d2ThemeManager.style_dialog_yes_button(
            self.yesButton,
            self._i18n.tr("conflict_dlg_disable_install"),
        )
        L4d2ThemeManager.style_dialog_cancel_button(
            self.cancelButton,
            self._i18n.tr("conflict_dlg_cancel"),
        )

        self.install_anyway_btn = PushButton(
            FluentIcon.DOWNLOAD,
            self._i18n.tr("conflict_dlg_install_anyway"),
            self.buttonGroup,
        )
        self.install_anyway_btn.clicked.connect(self._choose_install_anyway)
        self.buttonLayout.insertWidget(1, self.install_anyway_btn)

        L4d2ThemeManager.apply_pointing_hand_cursors(self)

    def validate(self) -> bool:
        self.choice = "disable_and_install"
        return True

    def reject(self) -> None:
        self.choice = "cancel"
        super().reject()

    def _choose_install_anyway(self) -> None:
        self.choice = "install_anyway"
        self.accept()
