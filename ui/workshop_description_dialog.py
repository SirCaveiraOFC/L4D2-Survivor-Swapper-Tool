from __future__ import annotations

from typing import Optional

from PySide6.QtCore import QObject, QThread, QUrl, Qt, Signal
from PySide6.QtGui import QDesktopServices, QImage, QTextDocument
from PySide6.QtWidgets import QHBoxLayout
from qfluentwidgets import (
    CaptionLabel,
    FluentIcon,
    MessageBoxBase,
    PushButton,
    SubtitleLabel,
    TextBrowser,
    isDarkTheme,
)

from core.i18n import LocalizationManager
from core.steam_bbcode import steam_bbcode_to_html
from core.workshop_downloader import fetch_preview_bytes
from ui.addon_ui_shared import create_icon_row, shutdown_worker_thread
from ui.theme import COLORS, L4d2ThemeManager


class _DescriptionImagesWorker(QObject):
    """Background worker fetching external [img] URLs for Steam Workshop descriptions."""

    imageLoaded = Signal(str, bytes)
    finishedAll = Signal()

    def __init__(self, urls: list[str]) -> None:
        super().__init__()
        self._urls = list(urls)
        self._cancelled = False

    def cancel(self) -> None:
        self._cancelled = True

    def run(self) -> None:
        for url in self._urls:
            if self._cancelled:
                break
            raw = fetch_preview_bytes(url, timeout=8.0)
            if self._cancelled:
                break
            if raw:
                self.imageLoaded.emit(url, raw)
        self.finishedAll.emit()


class WorkshopDescriptionDialog(MessageBoxBase):
    """Scrollable rich-text modal rendering full Steam Workshop BBCode descriptions."""

    def __init__(
        self,
        title: str,
        raw_description: str,
        subtitle: str = "",
        steam_url: str = "",
        i18n: Optional[LocalizationManager] = None,
        parent=None,
    ) -> None:
        super().__init__(parent)
        self._i18n = i18n or LocalizationManager("en-US")
        self._raw_description = raw_description
        self._steam_url = steam_url
        self._img_thread: Optional[QThread] = None
        self._img_worker: Optional[_DescriptionImagesWorker] = None

        self.widget.setMinimumWidth(780)
        self.widget.setMinimumHeight(560)

        self._is_dark = isDarkTheme()
        self._loaded_image_urls: set[str] = set()
        is_dark = self._is_dark
        muted = COLORS.dark_muted if is_dark else COLORS.light_muted
        canvas_bg = COLORS.dark_card if is_dark else COLORS.light_card
        border_fg = COLORS.dark_border if is_dark else COLORS.light_border

        self.title_label = SubtitleLabel(title or self._i18n.tr("dl_desc_dlg_title"), self.widget)
        self.title_label.setWordWrap(True)
        self.viewLayout.addLayout(
            create_icon_row(FluentIcon.DOCUMENT, self.title_label, self.widget, size=20, spacing=10)
        )

        if subtitle or steam_url:
            meta_row = QHBoxLayout()
            meta_row.setSpacing(10)
            self.subtitle_label = CaptionLabel(subtitle, self.widget)
            self.subtitle_label.setWordWrap(True)
            self.subtitle_label.setStyleSheet(f"color: {muted}; font-size: 12px;")
            meta_row.addWidget(self.subtitle_label, 1)
            if steam_url:
                self.open_steam_btn = PushButton(
                    FluentIcon.GLOBE,
                    self._i18n.tr("dl_btn_open_steam"),
                    self.widget,
                )
                self.open_steam_btn.clicked.connect(
                    lambda: QDesktopServices.openUrl(QUrl(self._steam_url))
                )
                meta_row.addWidget(self.open_steam_btn, 0)
            self.viewLayout.addLayout(meta_row)

        self._rendered_html, image_urls = steam_bbcode_to_html(
            raw_description,
            is_dark=is_dark,
            original_author_label=self._i18n.tr("dl_desc_original_author"),
            loaded_images=self._loaded_image_urls,
        )

        self.browser = TextBrowser(self.widget)
        self.browser.setOpenExternalLinks(True)
        self.browser.setReadOnly(True)
        self.browser.setMinimumHeight(400)
        self.browser.document().setDocumentMargin(14)
        self.browser.setStyleSheet(
            f"TextBrowser {{ background-color: {canvas_bg}; border: 1px solid {border_fg}; "
            f"border-radius: 8px; }}"
        )
        self.browser.setHtml(self._rendered_html)
        self.viewLayout.addWidget(self.browser, 1)

        self.hideYesButton()
        L4d2ThemeManager.style_dialog_cancel_button(
            self.cancelButton,
            self._i18n.tr("err_dlg_close"),
        )
        L4d2ThemeManager.apply_pointing_hand_cursors(self)

        if image_urls:
            self._start_image_loader(image_urls[:12])

    def _start_image_loader(self, urls: list[str]) -> None:
        self._img_thread = QThread(self)
        self._img_worker = _DescriptionImagesWorker(urls)
        self._img_worker.moveToThread(self._img_thread)
        self._img_thread.started.connect(self._img_worker.run)
        self._img_worker.imageLoaded.connect(self._on_inline_image_loaded)
        self._img_worker.finishedAll.connect(self._img_thread.quit)
        self._img_thread.finished.connect(self._cleanup_img_thread)
        self._img_thread.start()

    def _on_inline_image_loaded(self, url: str, raw: bytes) -> None:
        img = QImage()
        if not img.loadFromData(raw) or img.isNull():
            return
        max_img_w = 640
        if img.width() > max_img_w:
            img = img.scaledToWidth(max_img_w, Qt.TransformationMode.SmoothTransformation)
        self.browser.document().addResource(
            QTextDocument.ResourceType.ImageResource,
            QUrl(url),
            img,
        )
        self._loaded_image_urls.add(url)
        self._rendered_html, _ = steam_bbcode_to_html(
            self._raw_description,
            is_dark=self._is_dark,
            original_author_label=self._i18n.tr("dl_desc_original_author"),
            loaded_images=self._loaded_image_urls,
        )
        vbar = self.browser.verticalScrollBar()
        pos = vbar.value() if vbar is not None else 0
        self.browser.setHtml(self._rendered_html)
        if vbar is not None:
            vbar.setValue(pos)

    def _cleanup_img_thread(self) -> None:
        if self._img_worker is not None:
            self._img_worker.deleteLater()
            self._img_worker = None
        if self._img_thread is not None:
            self._img_thread.deleteLater()
            self._img_thread = None

    def shutdown_worker(self) -> None:
        shutdown_worker_thread(
            self._img_thread,
            self._img_worker,
            cancel_fn=self._img_worker.cancel if self._img_worker is not None else None,
            ui_signals=(self._img_worker.imageLoaded,) if self._img_worker is not None else (),
            timeout_ms=2000,
        )
        self._img_worker = None
        self._img_thread = None

    def reject(self) -> None:
        self.shutdown_worker()
        super().reject()

    def closeEvent(self, event) -> None:
        self.shutdown_worker()
        super().closeEvent(event)
