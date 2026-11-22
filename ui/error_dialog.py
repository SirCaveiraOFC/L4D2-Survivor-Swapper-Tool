from __future__ import annotations

from typing import Optional

from PySide6.QtCore import QTimer
from PySide6.QtWidgets import QWidget
from qfluentwidgets import (
    BodyLabel,
    FluentIcon,
    MessageBoxBase,
    PushButton,
    SubtitleLabel,
    TextEdit,
    isDarkTheme,
)

from core.i18n import LocalizationManager
from ui.theme import COLORS, L4d2ThemeManager
from ui.widgets import copy_text_with_feedback, create_icon_row


class ErrorDetailsDialog(MessageBoxBase):
    """Scrollable modal error viewer with one-click clipboard copy for full logs."""

    def __init__(
        self,
        title: str,
        summary: str,
        details: str = "",
        i18n: Optional[LocalizationManager] = None,
        parent: Optional[QWidget] = None,
    ) -> None:
        super().__init__(parent)
        self._i18n = i18n or LocalizationManager("en-US")
        self._full_text = (details or summary).strip()

        self.widget.setMinimumWidth(680)

        self.title_label = SubtitleLabel(title, self.widget)
        self.intro_label = BodyLabel(self._i18n.tr("err_dlg_intro"), self.widget)
        self.intro_label.setWordWrap(True)

        self.summary_label = BodyLabel(summary, self.widget)
        self.summary_label.setWordWrap(True)

        self.details_view = TextEdit(self.widget)
        self.details_view.setReadOnly(True)
        self.details_view.setMinimumHeight(230)
        self.details_view.setPlainText(self._full_text)

        is_dark = isDarkTheme()
        bg = COLORS.dark_card_alt if is_dark else "#FFFFFF"
        border = COLORS.red if is_dark else "#B85C5C"
        text = COLORS.dark_text if is_dark else COLORS.light_text
        self.details_view.setStyleSheet(
            f"TextEdit {{ background-color: {bg}; color: {text}; "
            f"border: 1px solid {border}; border-radius: 6px; padding: 6px; }}"
        )

        self.viewLayout.addLayout(
            create_icon_row(FluentIcon.CLOSE, self.title_label, self.widget, size=18, spacing=10)
        )
        self.viewLayout.addWidget(self.intro_label)
        if summary.strip() and summary.strip() != self._full_text:
            self.viewLayout.addWidget(self.summary_label)
        self.viewLayout.addWidget(self.details_view)

        self.hideYesButton()
        self.copy_btn = PushButton(FluentIcon.COPY, self._i18n.tr("err_dlg_copy"), self.buttonGroup)
        self.buttonLayout.insertWidget(0, self.copy_btn)
        L4d2ThemeManager.style_dialog_cancel_button(
            self.cancelButton,
            self._i18n.tr("err_dlg_close"),
        )

        self._copy_reset_timer = QTimer(self)
        self._copy_reset_timer.setSingleShot(True)
        self._copy_reset_timer.timeout.connect(self._restore_copy_label)
        self.copy_btn.clicked.connect(self._on_copy)

        L4d2ThemeManager.apply_pointing_hand_cursors(self)

    def full_error_text(self) -> str:
        return self._full_text

    def _restore_copy_label(self) -> None:
        self.copy_btn.setText(self._i18n.tr("err_dlg_copy"))

    def _on_copy(self) -> None:
        copy_text_with_feedback(
            self.copy_btn,
            self._full_text,
            self._i18n.tr("btn_copied"),
            self._copy_reset_timer,
        )
