from __future__ import annotations

from pathlib import Path
import threading
from typing import Optional

from PySide6.QtCore import QObject, QThread, Qt, Signal
from PySide6.QtGui import QPixmap
from PySide6.QtWidgets import (
    QHBoxLayout,
    QLabel,
    QVBoxLayout,
    QWidget,
)
from qfluentwidgets import (
    BodyLabel,
    CaptionLabel,
    CardWidget,
    FluentIcon,
    InfoBar,
    InfoBarPosition,
    LineEdit,
    MessageBoxBase,
    PlainTextEdit,
    ProgressBar,
    PushButton,
    StrongBodyLabel,
    SubtitleLabel,
    isDarkTheme,
)

from core.i18n import LocalizationManager
from core.workshop_downloader import (
    WorkshopDownloadResult,
    WorkshopError,
    WorkshopItemDetails,
    download_vpk,
    enrich_item_from_web,
    extract_workshop_item_ids,
    fetch_items_details,
    fetch_preview_bytes,
    format_bytes,
    format_count,
    format_timestamp,
)
from ui.addon_ui_shared import create_icon_row, shutdown_worker_thread
from ui.theme import COLORS, L4d2ThemeManager
from ui.widgets import bind_preview_media, clear_preview_media


class WorkshopFetchWorker(QObject):
    """Background worker querying Steam Workshop item metadata and cover thumbnails."""

    fetched = Signal(object)
    failed = Signal(str, object)
    done = Signal()

    def __init__(self, item_ids: list[str]) -> None:
        super().__init__()
        self._item_ids = list(item_ids)
        self._cancel_event = threading.Event()

    def request_cancel(self) -> None:
        self._cancel_event.set()

    def run(self) -> None:
        try:
            if self._cancel_event.is_set():
                return
            details_list = fetch_items_details(self._item_ids)
            results: list[tuple[WorkshopItemDetails, Optional[bytes]]] = []
            for idx, item in enumerate(details_list):
                if self._cancel_event.is_set():
                    return
                enriched = enrich_item_from_web(item) if idx < 3 else item
                if self._cancel_event.is_set():
                    return
                preview = fetch_preview_bytes(enriched.preview_url) if idx == 0 else None
                results.append((enriched, preview))
            if not self._cancel_event.is_set():
                self.fetched.emit(results)
        except WorkshopError as exc:
            if not self._cancel_event.is_set():
                self.failed.emit(exc.key, exc.kwargs)
        except Exception as exc:
            if not self._cancel_event.is_set():
                self.failed.emit("dl_err_network", {"reason": str(exc)})
        finally:
            self.done.emit()


class WorkshopDownloadWorker(QObject):
    """Background worker resolving metadata (if needed) and streaming Workshop VPKs."""

    progressUpdated = Signal(int, int, str, int, int)
    completed = Signal(object)
    failed = Signal(str, object)

    def __init__(
        self,
        item_ids: list[str],
        target_dir: Path,
        addons_dir: Optional[Path] = None,
        prefetched_details: Optional[dict[str, WorkshopItemDetails]] = None,
        prefetched_previews: Optional[dict[str, bytes]] = None,
        overwrite: bool = False,
    ) -> None:
        super().__init__()
        self._item_ids = list(item_ids)
        self._target_dir = target_dir
        self._addons_dir = addons_dir
        self._details = dict(prefetched_details or {})
        self._previews = dict(prefetched_previews or {})
        self._overwrite = overwrite
        self._cancel_event = threading.Event()

    def request_cancel(self) -> None:
        self._cancel_event.set()

    def run(self) -> None:
        try:
            missing_ids = [wid for wid in self._item_ids if wid not in self._details]
            if missing_ids:
                for item in fetch_items_details(missing_ids):
                    self._details[item.published_file_id] = item

            ordered_items = [
                enrich_item_from_web(self._details[wid])
                if (self._details[wid].rating_stars is None and not self._details[wid].creator_name)
                else self._details[wid]
                for wid in self._item_ids
                if wid in self._details
            ]
            if not ordered_items:
                raise WorkshopError("dl_err_not_found", item_id=self._item_ids[0] if self._item_ids else "?")

            total_items = len(ordered_items)
            results: list[WorkshopDownloadResult] = []
            for idx, item in enumerate(ordered_items, start=1):
                if self._cancel_event.is_set():
                    raise WorkshopError("dl_err_cancelled")

                def on_prog(done_bytes: int, total_bytes: int, i: int = idx, title: str = item.title) -> None:
                    self.progressUpdated.emit(i, total_items, title, done_bytes, total_bytes)

                res = download_vpk(
                    details=item,
                    target_dir=self._target_dir,
                    addons_dir=self._addons_dir,
                    progress_cb=on_prog,
                    cancel_event=self._cancel_event,
                    overwrite=self._overwrite,
                    preview_bytes=self._previews.get(item.published_file_id),
                )
                results.append(res)
            self.completed.emit(results)
        except WorkshopError as exc:
            self.failed.emit(exc.key, exc.kwargs)
        except Exception as exc:
            self.failed.emit("dl_err_network", {"reason": str(exc)})


class WorkshopUrlDialog(MessageBoxBase):
    """Quick Steam Workshop URL/ID download modal for Individual Swap and Batch Queue."""

    def __init__(
        self,
        download_dir: Path,
        addons_dir: Optional[Path] = None,
        allow_multiple: bool = False,
        i18n: Optional[LocalizationManager] = None,
        parent: Optional[QWidget] = None,
    ) -> None:
        super().__init__(parent)
        self._download_dir = download_dir
        self._addons_dir = addons_dir
        self._allow_multiple = allow_multiple
        self._i18n = i18n or LocalizationManager("en-US")

        self._fetch_thread: Optional[QThread] = None
        self._fetch_worker: Optional[WorkshopFetchWorker] = None
        self._dl_thread: Optional[QThread] = None
        self._dl_worker: Optional[WorkshopDownloadWorker] = None
        self._prefetched_details: dict[str, WorkshopItemDetails] = {}
        self._prefetched_previews: dict[str, bytes] = {}
        self._results: list[WorkshopDownloadResult] = []
        self._busy = False
        self._suppress_auto_accept = False

        self.widget.setMinimumWidth(620)
        is_dark = isDarkTheme()
        muted_fg = COLORS.dark_muted if is_dark else COLORS.light_muted
        border_fg = COLORS.dark_border if is_dark else COLORS.light_border
        card_bg = COLORS.dark_card if is_dark else COLORS.light_card
        alt_bg = COLORS.dark_card_alt if is_dark else COLORS.light_card_alt

        title_key = "dl_dlg_title_multi" if allow_multiple else "dl_dlg_title_single"
        intro_key = "dl_dlg_intro_multi" if allow_multiple else "dl_dlg_intro_single"

        self.title_label = SubtitleLabel(self._i18n.tr(title_key), self.widget)
        self.viewLayout.addLayout(
            create_icon_row(FluentIcon.LINK, self.title_label, self.widget, size=20, spacing=10)
        )
        self.intro_label = CaptionLabel(self._i18n.tr(intro_key), self.widget)
        self.intro_label.setWordWrap(True)
        self.intro_label.setStyleSheet(f"color: {muted_fg}; font-size: 12px;")
        self.viewLayout.addWidget(self.intro_label)

        input_row = QHBoxLayout()
        input_row.setSpacing(8)
        if allow_multiple:
            self.url_input = PlainTextEdit(self.widget)
            self.url_input.setPlaceholderText(self._i18n.tr("dl_input_placeholder"))
            self.url_input.setFixedHeight(84)
        else:
            self.url_input = LineEdit(self.widget)
            self.url_input.setPlaceholderText(
                "https://steamcommunity.com/sharedfiles/filedetails/?id=2999473278"
            )
            self.url_input.setClearButtonEnabled(True)

        self.fetch_btn = PushButton(FluentIcon.SEARCH, self._i18n.tr("dl_dlg_btn_fetch"), self.widget)
        self.fetch_btn.clicked.connect(self._on_fetch_clicked)

        input_row.addWidget(self.url_input, 1)
        input_row.addWidget(self.fetch_btn, 0, Qt.AlignmentFlag.AlignTop if allow_multiple else Qt.AlignmentFlag.AlignVCenter)
        self.viewLayout.addLayout(input_row)

        self.preview_card = CardWidget(self.widget)
        self.preview_card.setStyleSheet(
            f"CardWidget {{ background-color: {card_bg}; border: 1px solid {border_fg}; border-radius: 8px; }}"
        )
        prev_lay = QHBoxLayout(self.preview_card)
        prev_lay.setContentsMargins(12, 10, 12, 10)
        prev_lay.setSpacing(12)

        self.cover_label = QLabel(self.preview_card)
        self.cover_label.setObjectName("dlDlgCoverThumb")
        self.cover_label.setFixedSize(112, 70)
        self.cover_label.setAlignment(Qt.AlignmentFlag.AlignCenter)
        self.cover_label.setText(self._i18n.tr("confirm_dlg_no_cover"))
        L4d2ThemeManager.install_surface_motion(
            self.cover_label,
            f"QLabel#dlDlgCoverThumb {{ background-color: {{bg}}; border: 1px solid {{border}}; "
            f"border-radius: 6px; color: {muted_fg}; font-size: 11px; }}",
            custom_colors=L4d2ThemeManager.image_surface_palette(is_dark),
            border_colors=L4d2ThemeManager.image_border_colors(is_dark),
        )

        meta_col = QVBoxLayout()
        meta_col.setSpacing(3)
        self.item_title_label = StrongBodyLabel("", self.preview_card)
        self.item_title_label.setWordWrap(True)
        self.item_meta_label = CaptionLabel("", self.preview_card)
        self.item_meta_label.setWordWrap(True)
        self.item_meta_label.setStyleSheet(f"color: {muted_fg}; font-size: 12px;")
        meta_col.addWidget(self.item_title_label)
        meta_col.addWidget(self.item_meta_label)
        meta_col.addStretch(1)

        prev_lay.addWidget(self.cover_label)
        prev_lay.addLayout(meta_col, 1)
        self.preview_card.setVisible(False)
        self.viewLayout.addWidget(self.preview_card)

        self.progress_bar = ProgressBar(self.widget)
        self.progress_bar.setRange(0, 100)
        self.progress_bar.setValue(0)
        self.progress_bar.setVisible(False)
        self.status_label = CaptionLabel(self._i18n.tr("dl_status_idle"), self.widget)
        self.status_label.setWordWrap(True)
        self.status_label.setStyleSheet(f"color: {muted_fg}; font-size: 12px;")
        self.viewLayout.addWidget(self.progress_bar)
        self.viewLayout.addWidget(self.status_label)

        confirm_key = "dl_dlg_btn_confirm_multi" if allow_multiple else "dl_dlg_btn_confirm_single"
        L4d2ThemeManager.style_dialog_yes_button(
            self.yesButton,
            self._i18n.tr(confirm_key),
            FluentIcon.DOWNLOAD,
        )
        L4d2ThemeManager.style_dialog_cancel_button(
            self.cancelButton,
            self._i18n.tr("dl_btn_cancel"),
            FluentIcon.CLOSE,
        )
        L4d2ThemeManager.apply_pointing_hand_cursors(self)
        L4d2ThemeManager.enable_card_hover(self.widget)

    def downloaded_paths(self) -> list[Path]:
        return [res.vpk_path for res in self._results]

    def downloaded_results(self) -> list[WorkshopDownloadResult]:
        return list(self._results)

    def _raw_text(self) -> str:
        if isinstance(self.url_input, PlainTextEdit):
            return self.url_input.toPlainText()
        return self.url_input.text()

    def _parse_ids(self) -> Optional[list[str]]:
        ids = extract_workshop_item_ids(self._raw_text())
        if not ids:
            InfoBar.warning(
                self._i18n.tr("dl_err_title"),
                self._i18n.tr("dl_err_invalid_id"),
                parent=self,
                position=InfoBarPosition.TOP,
            )
            return None
        return ids if self._allow_multiple else [ids[0]]

    def _set_busy(self, busy: bool) -> None:
        self._busy = busy
        self.url_input.setEnabled(not busy)
        self.fetch_btn.setEnabled(not busy)
        self.yesButton.setEnabled(not busy)

    def _on_fetch_clicked(self) -> None:
        if self._busy:
            return
        ids = self._parse_ids()
        if not ids:
            return
        self._set_busy(True)
        self.status_label.setText(self._i18n.tr("dl_status_fetching"))
        self.progress_bar.setVisible(False)

        self._fetch_thread = QThread(self)
        self._fetch_worker = WorkshopFetchWorker(ids)
        self._fetch_worker.moveToThread(self._fetch_thread)
        self._fetch_thread.started.connect(self._fetch_worker.run)
        self._fetch_worker.fetched.connect(self._on_fetched)
        self._fetch_worker.failed.connect(self._on_worker_failed)
        self._fetch_worker.done.connect(self._fetch_thread.quit)
        self._fetch_thread.finished.connect(self._cleanup_fetch_thread)
        self._fetch_thread.start()

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

        first_item, first_preview = pairs[0]
        if first_preview:
            bound_pix = bind_preview_media(self.cover_label, first_preview, 108, 66)
            if bound_pix is not None:
                self.cover_label.setText("")

        if len(pairs) == 1:
            self.item_title_label.setText(first_item.title)
            sep = "," if self._i18n.active_language == "en-US" else "."
            meta_parts = [
                f"ID {first_item.published_file_id}",
                format_bytes(first_item.file_size),
                format_timestamp(first_item.time_updated, self._i18n.active_language),
            ]
            if first_item.rating_stars is not None and first_item.rating_stars > 0:
                meta_parts.append(f"{'★' * first_item.rating_stars} ({format_count(first_item.num_ratings, sep)})")
            if first_item.subscriptions > 0:
                meta_parts.append(
                    self._i18n.tr("dl_dlg_subs", count=format_count(first_item.subscriptions, sep))
                )
            self.item_meta_label.setText("  •  ".join(meta_parts))
            self.status_label.setText(
                self._i18n.tr("dl_status_ready" if first_item.has_direct_url else "dl_status_no_direct")
            )
        else:
            total_size = sum(it.file_size for it, _ in pairs)
            titles = ", ".join(it.title for it, _ in pairs[:3])
            if len(pairs) > 3:
                titles = f"{titles} (+{len(pairs) - 3})"
            self.item_title_label.setText(f"{len(pairs)} mods — {format_bytes(total_size)}")
            self.item_meta_label.setText(titles)
            self.status_label.setText(self._i18n.tr("dl_status_ready"))

        self.preview_card.setVisible(True)

    def _on_worker_failed(self, key: str, kwargs: dict) -> None:
        self._set_busy(False)
        self.progress_bar.setVisible(False)
        msg = self._i18n.tr(key, **(kwargs or {}))
        self.status_label.setText(msg)
        if key != "dl_err_cancelled":
            InfoBar.error(
                self._i18n.tr("dl_err_title"),
                msg,
                parent=self,
                position=InfoBarPosition.TOP,
                duration=6000,
            )

    def validate(self) -> bool:
        if self._results:
            return True
        if self._busy:
            return False
        ids = self._parse_ids()
        if not ids:
            return False

        self._set_busy(True)
        self.progress_bar.setVisible(True)
        self.progress_bar.setValue(0)
        self.status_label.setText(self._i18n.tr("dl_status_fetching"))

        self._dl_thread = QThread(self)
        self._dl_worker = WorkshopDownloadWorker(
            item_ids=ids,
            target_dir=self._download_dir,
            addons_dir=self._addons_dir,
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
        return False

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
        self._results = list(results)
        self._set_busy(False)
        self.progress_bar.setValue(100)
        if not self._suppress_auto_accept:
            self.accept()

    def reject(self) -> None:
        self._suppress_auto_accept = True
        clear_preview_media(self.cover_label)
        self.shutdown_workers()
        super().reject()

    def shutdown_workers(self) -> None:
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
