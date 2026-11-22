from __future__ import annotations

from pathlib import Path, PurePosixPath
import textwrap
from typing import Callable, Optional

from PySide6.QtCore import (
    QBuffer,
    QByteArray,
    QEasingCurve,
    QIODevice,
    QPointF,
    QRectF,
    QSize,
    QTimer,
    QVariantAnimation,
    Qt,
    Signal,
)
from PySide6.QtGui import (
    QColor,
    QDragEnterEvent,
    QDragLeaveEvent,
    QDropEvent,
    QFont,
    QFontMetrics,
    QImage,
    QImageReader,
    QLinearGradient,
    QMouseEvent,
    QMovie,
    QPainter,
    QPainterPath,
    QPen,
    QPixmap,
    QPolygonF,
)
from PySide6.QtWidgets import (
    QApplication,
    QFileDialog,
    QFrame,
    QGridLayout,
    QHBoxLayout,
    QLabel,
    QPushButton,
    QSizePolicy,
    QVBoxLayout,
    QWidget,
)
from qfluentwidgets import (
    BodyLabel,
    CaptionLabel,
    CardWidget,
    CheckBox,
    FlowLayout,
    FluentIcon,
    HeaderCardWidget,
    IconWidget,
    InfoBadge,
    InfoLevel,
    MessageBoxBase,
    ProgressBar,
    PushButton,
    StrongBodyLabel,
    SubtitleLabel,
    SwitchButton,
    TextEdit,
    Theme,
    ToolTipFilter,
    ToolTipPosition,
    isDarkTheme,
)

from core.app_meta import APP_META
from core.archive_service import ArchiveSourceManager
from core.i18n import LocalizationManager
from core.models import DetectedModInfo, SurvivorId
from core.survivors import SurvivorRegistry
from core.vtf_decoder import VguiPreviewItem, extract_vgui_previews
from ui.theme import COLORS, L4d2ThemeManager, lerp_color


def add_card_header_icon(card: HeaderCardWidget, icon: FluentIcon, size: int = 16) -> IconWidget:
    """Insert a theme-aware icon before a HeaderCardWidget title."""
    icon_widget = IconWidget(icon, card.headerView)
    icon_widget.setFixedSize(size, size)
    card.headerLayout.setSpacing(8)
    card.headerLayout.insertWidget(0, icon_widget, 0, Qt.AlignmentFlag.AlignVCenter)
    return icon_widget


def _l4d1_hand_silhouette() -> QPainterPath:
    hand = QPainterPath()
    hand.moveTo(9.4, 21.0)
    hand.cubicTo(9.1, 18.8, 8.6, 17.2, 7.2, 16.0)
    hand.cubicTo(5.6, 15.6, 4.1, 15.0, 3.2, 13.7)
    hand.cubicTo(2.4, 12.6, 3.2, 11.0, 4.7, 11.6)
    hand.cubicTo(5.5, 12.0, 5.9, 12.8, 7.8, 13.7)

    hand.cubicTo(6.9, 11.4, 5.9, 8.6, 5.1, 6.2)
    hand.cubicTo(4.6, 4.7, 6.6, 4.0, 7.3, 5.5)
    hand.cubicTo(8.2, 7.6, 9.1, 9.6, 9.9, 11.1)

    hand.cubicTo(10.3, 8.6, 10.6, 5.8, 10.8, 3.3)
    hand.cubicTo(10.9, 1.8, 13.3, 1.9, 13.2, 3.4)
    hand.cubicTo(13.0, 5.9, 12.9, 8.5, 13.2, 11.1)

    hand.cubicTo(14.5, 9.0, 15.8, 6.8, 17.1, 4.8)
    hand.cubicTo(18.0, 3.4, 20.1, 4.5, 19.2, 5.9)
    hand.cubicTo(18.0, 7.9, 16.9, 10.1, 16.0, 12.3)

    hand.cubicTo(15.7, 13.1, 15.3, 13.6, 14.8, 14.0)
    hand.cubicTo(13.8, 14.6, 13.8, 15.3, 14.5, 15.9)
    hand.cubicTo(13.8, 16.7, 14.0, 17.4, 14.7, 18.1)
    hand.cubicTo(14.6, 19.1, 14.6, 20.1, 14.6, 21.0)
    hand.closeSubpath()
    return hand


def _l4d2_hand_silhouette() -> QPainterPath:
    hand = QPainterPath()
    hand.moveTo(9.4, 21.0)
    hand.cubicTo(9.1, 18.8, 8.6, 17.1, 7.3, 15.9)
    hand.cubicTo(5.9, 15.2, 4.7, 14.6, 3.8, 13.9)
    hand.cubicTo(2.8, 13.1, 3.6, 11.4, 5.0, 12.0)
    hand.cubicTo(6.1, 12.5, 7.0, 13.1, 7.9, 13.5)

    hand.cubicTo(7.1, 12.1, 6.4, 11.0, 5.9, 9.8)
    hand.cubicTo(5.3, 8.4, 7.2, 7.4, 8.1, 8.7)
    hand.cubicTo(8.8, 9.8, 9.5, 10.7, 10.2, 11.4)

    hand.cubicTo(10.3, 9.7, 10.4, 8.3, 10.2, 7.0)
    hand.cubicTo(10.1, 5.8, 10.3, 4.5, 10.3, 3.3)
    hand.cubicTo(10.3, 1.8, 12.8, 1.8, 12.8, 3.3)
    hand.cubicTo(12.8, 4.5, 13.1, 5.8, 12.9, 7.0)
    hand.cubicTo(12.7, 8.3, 12.7, 9.6, 13.0, 10.9)

    hand.cubicTo(14.0, 9.2, 15.0, 7.7, 15.6, 6.3)
    hand.cubicTo(16.1, 5.4, 16.4, 4.5, 16.7, 3.6)
    hand.cubicTo(17.2, 2.2, 19.6, 3.0, 19.0, 4.5)
    hand.cubicTo(18.5, 5.6, 18.2, 6.7, 17.6, 7.9)
    hand.cubicTo(17.0, 9.2, 16.3, 10.5, 16.0, 12.1)

    hand.cubicTo(15.7, 13.0, 15.3, 13.5, 14.8, 13.9)
    hand.cubicTo(13.8, 14.5, 13.8, 15.2, 14.5, 15.8)
    hand.cubicTo(13.8, 16.6, 14.0, 17.3, 14.7, 18.0)
    hand.cubicTo(14.6, 19.1, 14.6, 20.1, 14.6, 21.0)
    hand.closeSubpath()
    return hand


_HAND_PALETTES = {
    "L4D1": ("#22C55E", "#15803D", "#DCFCE7"),
    "L4D2": (COLORS.amber, "#A66F00", "#FFF5BD"),
}

_HAND_HIGHLIGHT_QUAD_CURVES = {
    "L4D1": (
        ((4.1, 12.5), (5.2, 13.8), (7.1, 14.7)),
        ((6.1, 5.7), (7.2, 8.2), (8.4, 10.7)),
        ((11.8, 3.1), (11.5, 6.4), (11.3, 9.8)),
        ((17.9, 5.4), (16.4, 7.8), (14.8, 10.4)),
    ),
    "L4D2": (
        ((6.7, 9.0), (7.7, 10.4), (8.7, 11.6)),
        ((4.4, 12.6), (5.6, 13.2), (6.8, 13.8)),
    ),
}

_HAND_HIGHLIGHT_CUBIC_CURVES = {
    "L4D1": (),
    "L4D2": (
        ((11.1, 3.0), (11.0, 5.0), (11.3, 7.0), (11.1, 9.4)),
        ((17.5, 3.8), (16.9, 5.6), (16.0, 7.5), (14.9, 9.7)),
    ),
}

_HAND_KNUCKLE_CUTS = {
    "L4D1": (((9.9, 11.1), (10.3, 12.9)), ((13.2, 11.1), (12.9, 12.8))),
    "L4D2": (((10.2, 11.4), (10.6, 13.0)), ((13.0, 10.9), (12.8, 12.8))),
}


class HandIconWidget(QWidget):
    """Shaded Left 4 Dead crew hand icon using L4D1 green and L4D2 amber silhouettes."""

    def __init__(
        self,
        parent: Optional[QWidget] = None,
        size: int = 19,
        generation: str = "L4D2",
    ) -> None:
        super().__init__(parent)
        self._generation = "L4D1" if generation.upper() == "L4D1" else "L4D2"
        self.setFixedSize(size, size)

    def paintEvent(self, _event) -> None:
        painter = QPainter(self)
        painter.setRenderHint(QPainter.RenderHint.Antialiasing)
        is_dark = isDarkTheme()
        base_hex, deep_hex, hi_hex = _HAND_PALETTES[self._generation]
        base_col = QColor(base_hex)
        deep_col = QColor(deep_hex)
        hi_col = QColor(hi_hex)
        rim_base = QColor(COLORS.dark_text if is_dark else COLORS.light_text)
        rim_alpha = 110 if is_dark else 135
        cut_col = QColor(COLORS.dark_card if is_dark else COLORS.light_card)

        scale = min(self.width(), self.height()) / 24.0
        painter.scale(scale, scale)

        path = _l4d1_hand_silhouette() if self._generation == "L4D1" else _l4d2_hand_silhouette()
        painter.save()
        painter.setClipPath(path)

        grad = QLinearGradient(10.0, 3.0, 13.0, 21.0)
        grad.setColorAt(0.0, base_col)
        grad.setColorAt(0.6, base_col)
        grad.setColorAt(1.0, deep_col)
        painter.fillRect(0, 0, 24, 24, grad)

        painter.setPen(
            QPen(
                QColor(hi_col.red(), hi_col.green(), hi_col.blue(), 215),
                0.85,
                Qt.PenStyle.SolidLine,
                Qt.PenCapStyle.RoundCap,
                Qt.PenJoinStyle.RoundJoin,
            )
        )
        painter.setBrush(Qt.BrushStyle.NoBrush)

        for start, c1, c2, end in _HAND_HIGHLIGHT_CUBIC_CURVES[self._generation]:
            bone = QPainterPath()
            bone.moveTo(*start)
            bone.cubicTo(*c1, *c2, *end)
            painter.drawPath(bone)

        for start, ctrl, end in _HAND_HIGHLIGHT_QUAD_CURVES[self._generation]:
            bone = QPainterPath()
            bone.moveTo(*start)
            bone.quadTo(*ctrl, *end)
            painter.drawPath(bone)

        painter.restore()

        painter.setPen(
            QPen(
                QColor(rim_base.red(), rim_base.green(), rim_base.blue(), rim_alpha),
                0.55,
                Qt.PenStyle.SolidLine,
                Qt.PenCapStyle.RoundCap,
                Qt.PenJoinStyle.RoundJoin,
            )
        )
        painter.setBrush(Qt.BrushStyle.NoBrush)
        painter.drawPath(path)

        painter.setPen(QPen(cut_col, 0.7, Qt.PenStyle.SolidLine, Qt.PenCapStyle.RoundCap))
        for p1, p2 in _HAND_KNUCKLE_CUTS[self._generation]:
            painter.drawLine(QPointF(*p1), QPointF(*p2))


def create_icon_row(
    icon: FluentIcon | QWidget,
    widget: QWidget,
    parent: QWidget,
    size: int = 20,
    spacing: int = 10,
) -> QHBoxLayout:
    """Create a horizontal header row pairing a Fluent icon or widget with a label."""
    row = QHBoxLayout()
    row.setContentsMargins(0, 0, 0, 0)
    row.setSpacing(spacing)
    icon_widget = icon if isinstance(icon, QWidget) else IconWidget(icon, parent)
    icon_widget.setFixedSize(size, size)
    row.addWidget(icon_widget, 0, Qt.AlignmentFlag.AlignVCenter)
    row.addWidget(widget, 1, Qt.AlignmentFlag.AlignVCenter)
    return row


def copy_text_with_feedback(
    btn: PushButton,
    text: str,
    copied_label: str,
    reset_timer: QTimer,
    duration_ms: int = 1800,
) -> bool:
    """Copy non-empty text to clipboard and show temporary confirmation text on btn."""
    clipboard = QApplication.clipboard()
    if not text or clipboard is None:
        return False
    clipboard.setText(text)
    reset_timer.stop()
    btn.setText(copied_label)
    reset_timer.start(duration_ms)
    return True


class ClickableImageLabel(QLabel):
    """QLabel emitting clicked signal on left click when a preview image is shown."""

    clicked = Signal()

    def mousePressEvent(self, event: QMouseEvent) -> None:
        if event.button() == Qt.MouseButton.LeftButton:
            self.clicked.emit()
        super().mousePressEvent(event)


def clear_preview_media(label: QLabel) -> None:
    """Stop and release any animated QMovie and backing QBuffer bound to label."""
    old_movie = getattr(label, "_gif_movie", None)
    if old_movie is not None:
        old_movie.stop()
        label.setMovie(None)
        old_movie.deleteLater()
        setattr(label, "_gif_movie", None)
    old_buf = getattr(label, "_gif_buffer", None)
    if old_buf is not None:
        old_buf.close()
        old_buf.deleteLater()
        setattr(label, "_gif_buffer", None)


def bind_preview_media(
    label: QLabel,
    raw_bytes: Optional[bytes],
    max_w: int,
    max_h: int,
) -> Optional[QPixmap]:
    """Bind a static QPixmap or looping animated GIF/WebP QMovie to label cleanly."""
    clear_preview_media(label)
    if not raw_bytes:
        return None

    is_gif = raw_bytes[:6] in (b"GIF87a", b"GIF89a")
    qba = QByteArray(raw_bytes)
    probe_buf = QBuffer(qba)
    probe_buf.open(QIODevice.OpenModeFlag.ReadOnly)
    reader = QImageReader(probe_buf, b"gif" if is_gif else b"")
    orig_size = reader.size()
    is_animated = is_gif or (reader.supportsAnimation() and reader.imageCount() > 1)
    probe_buf.close()

    pix = QPixmap()
    if not pix.loadFromData(raw_bytes) or pix.isNull():
        return None

    if is_animated:
        buf = QBuffer(label)
        buf.setData(qba)
        buf.open(QIODevice.OpenModeFlag.ReadOnly)
        movie = QMovie(buf, b"gif" if is_gif else b"", label)
        if movie.isValid() and movie.frameCount() != 1:
            base_size = orig_size if orig_size.isValid() and not orig_size.isEmpty() else pix.size()
            scaled = base_size.scaled(max_w, max_h, Qt.AspectRatioMode.KeepAspectRatio)
            if not scaled.isEmpty():
                movie.setScaledSize(scaled)
            movie.setCacheMode(QMovie.CacheMode.CacheAll)
            setattr(label, "_gif_buffer", buf)
            setattr(label, "_gif_movie", movie)
            label.setPixmap(QPixmap())
            label.setMovie(movie)
            movie.start()
            return pix
        buf.close()
        buf.deleteLater()
        movie.deleteLater()

    label.setPixmap(
        pix.scaled(
            max_w,
            max_h,
            Qt.AspectRatioMode.KeepAspectRatio,
            Qt.TransformationMode.SmoothTransformation,
        )
    )
    return pix


class ImageZoomDialog(MessageBoxBase):
    """Lightbox modal displaying a full-resolution static or animated preview image."""

    def __init__(
        self,
        title: str,
        pixmap: Optional[QPixmap] = None,
        i18n: Optional[LocalizationManager] = None,
        parent: Optional[QWidget] = None,
        raw_bytes: Optional[bytes] = None,
    ) -> None:
        super().__init__(parent)
        self._i18n = i18n or LocalizationManager("en-US")
        self.widget.setMinimumWidth(680)

        self.title_label = SubtitleLabel(title, self.widget)
        self.viewLayout.addLayout(
            create_icon_row(FluentIcon.PHOTO, self.title_label, self.widget, size=20, spacing=10)
        )

        is_dark = isDarkTheme()
        bg = COLORS.dark_window if is_dark else "#D8D2C5"
        border = COLORS.dark_border if is_dark else COLORS.light_border

        self.zoom_image_label = QLabel(self.widget)
        self.zoom_image_label.setObjectName("zoomPreviewImage")
        self.zoom_image_label.setFixedSize(640, 480)
        self.zoom_image_label.setAlignment(Qt.AlignmentFlag.AlignCenter)
        L4d2ThemeManager.install_surface_motion(
            self.zoom_image_label,
            f"QLabel#zoomPreviewImage {{ background-color: {bg}; border: 1px solid {{border}}; "
            f"border-radius: 8px; padding: 6px; }}",
            border_colors=L4d2ThemeManager.image_border_colors(is_dark),
        )
        bound = bind_preview_media(self.zoom_image_label, raw_bytes, 628, 468) if raw_bytes else None
        if bound is None and pixmap is not None and not pixmap.isNull():
            scaled = pixmap.scaled(
                628,
                468,
                Qt.AspectRatioMode.KeepAspectRatio,
                Qt.TransformationMode.SmoothTransformation,
            )
            self.zoom_image_label.setPixmap(scaled)
        self.viewLayout.addWidget(self.zoom_image_label)

        self.hideYesButton()
        L4d2ThemeManager.style_dialog_cancel_button(
            self.cancelButton,
            self._i18n.tr("err_dlg_close"),
        )
        L4d2ThemeManager.apply_pointing_hand_cursors(self)

    def reject(self) -> None:
        clear_preview_media(self.zoom_image_label)
        super().reject()

    def closeEvent(self, event) -> None:
        clear_preview_media(self.zoom_image_label)
        super().closeEvent(event)


def create_labeled_switch(text: str, checked: bool, parent: Optional[QWidget] = None) -> SwitchButton:
    """Create a SwitchButton that keeps its descriptive label visible in both on and off states."""
    switch = SwitchButton(text, parent)
    set_switch_label(switch, text)
    switch.setChecked(checked)
    switch.setCursor(Qt.CursorShape.PointingHandCursor)
    return switch


def set_switch_label(switch: SwitchButton, text: str) -> None:
    """Update both off/on text labels on a SwitchButton cleanly."""
    switch.setOffText(text)
    switch.setOnText(text)


def _style_help_badge(badge: QLabel) -> None:
    is_dark = isDarkTheme()
    border = "#485163" if is_dark else "#9E9585"
    fg = COLORS.amber if is_dark else "#2B3038"
    L4d2ThemeManager.install_surface_motion(
        badge,
        f"QLabel {{ background-color: {{bg}}; color: {fg}; border: 1px solid {border}; "
        f"border-radius: 9px; font-weight: 700; font-size: 11px; }}",
        tone="badge",
    )


def create_help_badge(tooltip: str = "", parent: Optional[QWidget] = None) -> QLabel:
    """Create a standalone circular (?) badge with an instant Fluent tooltip."""
    help_badge = QLabel("?", parent)
    help_badge.setFixedSize(18, 18)
    help_badge.setAlignment(Qt.AlignmentFlag.AlignCenter)
    help_badge.setCursor(Qt.CursorShape.PointingHandCursor)
    help_badge.installEventFilter(
        ToolTipFilter(help_badge, showDelay=100, position=ToolTipPosition.TOP)
    )
    update_help_badge(help_badge, tooltip)
    return help_badge


def wrap_tooltip_text(text: str, width: int = 48) -> str:
    """Wrap long single-line tooltip copy across balanced lines for compact Fluent tooltips."""
    cleaned = (text or "").strip()
    if not cleaned:
        return ""
    wrapped_paragraphs: list[str] = []
    for paragraph in cleaned.splitlines():
        stripped = paragraph.strip()
        if not stripped:
            wrapped_paragraphs.append("")
        elif len(stripped) <= width:
            wrapped_paragraphs.append(stripped)
        else:
            wrapped_paragraphs.append(
                textwrap.fill(
                    stripped,
                    width=width,
                    break_long_words=False,
                    break_on_hyphens=False,
                )
            )
    return "\n".join(wrapped_paragraphs)


def update_help_badge(help_badge: QLabel, tooltip: str) -> None:
    """Refresh wrapped tooltip copy and theme colors on a circular (?) help badge."""
    help_badge.setToolTip(wrap_tooltip_text(tooltip))
    _style_help_badge(help_badge)


def _pack_control_with_help(
    control: QWidget,
    tooltip: str,
    parent: Optional[QWidget] = None,
) -> tuple[QWidget, QLabel]:
    container = QWidget(parent)
    container.setStyleSheet("background: transparent;")
    row = QHBoxLayout(container)
    row.setContentsMargins(0, 0, 0, 0)
    row.setSpacing(6)

    control.setParent(container)
    help_badge = create_help_badge(tooltip, container)

    row.addWidget(control)
    row.addWidget(help_badge, 0, Qt.AlignmentFlag.AlignVCenter)
    row.addStretch(1)
    return container, help_badge


def create_switch_with_help(
    text: str,
    checked: bool,
    tooltip: str,
    parent: Optional[QWidget] = None,
) -> tuple[QWidget, SwitchButton, QLabel]:
    """Create a SwitchButton paired with an inline circular (?) help icon and Fluent tooltip."""
    switch = create_labeled_switch(text, checked, parent)
    container, help_badge = _pack_control_with_help(switch, tooltip, parent)
    return container, switch, help_badge


def update_switch_help(
    switch: SwitchButton,
    help_badge: QLabel,
    text: str,
    tooltip: str,
) -> None:
    """Refresh label, tooltip copy, and theme styling on a switch + help icon pair."""
    set_switch_label(switch, text)
    update_help_badge(help_badge, tooltip)


def create_checkbox_with_help(
    text: str,
    checked: bool,
    tooltip: str,
    parent: Optional[QWidget] = None,
) -> tuple[QWidget, CheckBox, QLabel]:
    """Create a CheckBox paired with an inline circular (?) help icon and Fluent tooltip."""
    checkbox = CheckBox(text, parent)
    checkbox.setChecked(checked)
    checkbox.setCursor(Qt.CursorShape.PointingHandCursor)
    container, help_badge = _pack_control_with_help(checkbox, tooltip, parent)
    return container, checkbox, help_badge


def update_checkbox_help(
    checkbox: CheckBox,
    help_badge: QLabel,
    text: str,
    tooltip: str,
) -> None:
    """Refresh label, tooltip copy, and theme styling on a checkbox + help icon pair."""
    checkbox.setText(text)
    update_help_badge(help_badge, tooltip)


class InlineWarningBanner(QFrame):
    """Compact amber warning card used inline for origin mismatches and _light notices."""

    def __init__(self, parent: Optional[QWidget] = None) -> None:
        super().__init__(parent)
        self.setObjectName("inlineWarningBanner")
        self.setAttribute(Qt.WidgetAttribute.WA_StyledBackground, True)
        row = QHBoxLayout(self)
        row.setContentsMargins(12, 8, 12, 8)
        row.setSpacing(8)

        self.icon_widget = IconWidget(FluentIcon.INFO, self)
        self.icon_widget.setFixedSize(16, 16)
        self.message_label = BodyLabel("", self)
        self.message_label.setWordWrap(True)
        self.message_label.setSizePolicy(QSizePolicy.Policy.Expanding, QSizePolicy.Policy.Minimum)

        row.addWidget(self.icon_widget, 0, Qt.AlignmentFlag.AlignTop)
        row.addWidget(self.message_label, 1)
        self.setVisible(False)
        self.refresh_theme()

    def set_warning(self, text: str) -> None:
        clean = (text or "").strip()
        self.message_label.setText(clean)
        self.refresh_theme()
        self.setVisible(bool(clean))

    def refresh_theme(self) -> None:
        is_dark = isDarkTheme()
        fg = COLORS.amber_bright if is_dark else "#5C4000"
        border = COLORS.amber_deep
        custom = (
            (QColor(245, 183, 0, 28), QColor(245, 183, 0, 44), QColor(245, 183, 0, 62))
            if is_dark
            else (QColor("#FFF7DF"), QColor("#FCEEC3"), QColor("#F7E39F"))
        )
        L4d2ThemeManager.install_surface_motion(
            self,
            f"QFrame#inlineWarningBanner {{ background-color: {{bg}}; border: 1px solid {border}; border-radius: 6px; }}",
            custom_colors=custom,
        )
        self.message_label.setStyleSheet(f"QLabel {{ color: {fg}; background: transparent; }}")


_lerp_color = lerp_color


class HazardStripeBar(QWidget):
    """Compact diagonal Biohazard Amber & Obsidian Black warning stripe."""

    def __init__(self, height: int = 8, parent: Optional[QWidget] = None) -> None:
        super().__init__(parent)
        self.setFixedHeight(height)

    def paintEvent(self, event) -> None:
        painter = QPainter(self)
        painter.setRenderHints(QPainter.Antialiasing)

        rect = self.rect()
        path = QPainterPath()
        path.addRoundedRect(QRectF(rect), 3, 3)
        painter.setClipPath(path)

        painter.fillRect(rect, QColor("#111315"))
        stripe_w = 14
        step = stripe_w * 2
        amber = QColor(COLORS.amber)

        painter.setPen(Qt.NoPen)
        painter.setBrush(amber)
        h = rect.height()
        x = -h - step
        while x < rect.width() + h + step:
            poly = QPolygonF(
                [
                    QPointF(x + h, 0),
                    QPointF(x + h + stripe_w, 0),
                    QPointF(x + stripe_w, h),
                    QPointF(x, h),
                ]
            )
            painter.drawPolygon(poly)
            x += step


class L4d2HeroBanner(CardWidget):
    """Clean L4D2 header banner with version pill, workflow steps, and hazard stripe."""

    def __init__(
        self,
        i18n: Optional[LocalizationManager] = None,
        parent: Optional[QWidget] = None,
    ) -> None:
        super().__init__(parent)
        self.setObjectName("l4d2HeroCard")
        self.setAttribute(Qt.WidgetAttribute.WA_Hover, True)
        self._hovered = False
        self._hover_t: float = 0.0
        self._press_t: float = 0.0
        self._hover_anim = QVariantAnimation(self)
        self._hover_anim.setDuration(160)
        self._hover_anim.setEasingCurve(QEasingCurve.Type.OutCubic)
        self._hover_anim.valueChanged.connect(self._on_hover_val)
        self._press_anim = QVariantAnimation(self)
        self._press_anim.setDuration(90)
        self._press_anim.setEasingCurve(QEasingCurve.Type.OutCubic)
        self._press_anim.valueChanged.connect(self._on_press_val)
        self._i18n = i18n or LocalizationManager("en-US")

        root = QVBoxLayout(self)
        root.setContentsMargins(22, 16, 22, 12)
        root.setSpacing(8)

        top_row = QHBoxLayout()
        top_row.setSpacing(10)

        self.hero_icon = IconWidget(FluentIcon.SYNC, self)
        self.hero_icon.setFixedSize(20, 20)
        self.title_label = SubtitleLabel("", self)
        self.title_label.setObjectName("heroTitleLabel")
        self.version_pill = QLabel(APP_META.version_tag, self)
        self.version_pill.setObjectName("heroVersionPill")

        top_row.addWidget(self.hero_icon, 0, Qt.AlignmentFlag.AlignVCenter)
        top_row.addWidget(self.title_label)
        top_row.addWidget(self.version_pill)
        top_row.addStretch(1)
        root.addLayout(top_row)

        self.subtitle_label = BodyLabel("", self)
        self.subtitle_label.setObjectName("heroSubtitleLabel")
        self.subtitle_label.setWordWrap(True)
        root.addWidget(self.subtitle_label)

        self.steps_panel = FlowPanel(h_space=8, v_space=6, parent=self)
        self.step1_pill = QLabel("", self.steps_panel)
        self.step2_pill = QLabel("", self.steps_panel)
        self.step3_pill = QLabel("", self.steps_panel)
        for pill in (self.step1_pill, self.step2_pill, self.step3_pill):
            L4d2ThemeManager.style_step_pill(pill)
            self.steps_panel.flow.addWidget(pill)
        self.steps_panel.sync_height(fallback_width=720)
        root.addWidget(self.steps_panel)

        self.hazard_stripe = HazardStripeBar(height=7, parent=self)
        root.addWidget(self.hazard_stripe)

        self.retranslate_ui(self._i18n)

    def _on_hover_val(self, val: object) -> None:
        self._hover_t = float(val)
        self.update()

    def _on_press_val(self, val: object) -> None:
        self._press_t = float(val)
        self.update()

    def enterEvent(self, event) -> None:
        self._hovered = True
        self._hover_anim.stop()
        self._hover_anim.setStartValue(self._hover_t)
        self._hover_anim.setEndValue(1.0)
        self._hover_anim.start()
        super().enterEvent(event)

    def leaveEvent(self, event) -> None:
        self._hovered = False
        self._hover_anim.stop()
        self._hover_anim.setStartValue(self._hover_t)
        self._hover_anim.setEndValue(0.0)
        self._hover_anim.start()
        if self._press_t > 0.0:
            self._press_anim.stop()
            self._press_anim.setStartValue(self._press_t)
            self._press_anim.setEndValue(0.0)
            self._press_anim.start()
        super().leaveEvent(event)

    def mousePressEvent(self, event: QMouseEvent) -> None:
        if event.button() == Qt.MouseButton.LeftButton:
            self._press_anim.stop()
            self._press_anim.setStartValue(self._press_t)
            self._press_anim.setEndValue(1.0)
            self._press_anim.start()
        super().mousePressEvent(event)

    def mouseReleaseEvent(self, event: QMouseEvent) -> None:
        self._press_anim.stop()
        self._press_anim.setStartValue(self._press_t)
        self._press_anim.setEndValue(0.0)
        self._press_anim.start()
        super().mouseReleaseEvent(event)

    def paintEvent(self, e) -> None:
        painter = QPainter(self)
        painter.setRenderHints(QPainter.Antialiasing)
        is_dark = isDarkTheme()

        idle_bg, hover_bg, press_bg = L4d2ThemeManager.surface_palette(is_dark, "card")
        bg = lerp_color(lerp_color(idle_bg, hover_bg, self._hover_t), press_bg, self._press_t)
        border = QColor(COLORS.dark_border if is_dark else COLORS.light_border)

        rect = QRectF(self.rect()).adjusted(1, 1, -1, -1)
        painter.setPen(QPen(border, 1.2))
        painter.setBrush(bg)
        painter.drawRoundedRect(rect, 8, 8)

        clip = QPainterPath()
        clip.addRoundedRect(rect, 8, 8)
        painter.setClipPath(clip)
        painter.fillRect(QRectF(rect.left(), rect.top(), 5, rect.height()), QColor(COLORS.red))

    def retranslate_ui(self, i18n: LocalizationManager) -> None:
        self._i18n = i18n
        self.title_label.setText(i18n.tr("hero_title"))
        self.version_pill.setText(APP_META.version_tag)
        self.subtitle_label.setText(i18n.tr("hero_subtitle"))
        self.step1_pill.setText(i18n.tr("hero_step_1"))
        self.step2_pill.setText(i18n.tr("hero_step_2"))
        self.step3_pill.setText(i18n.tr("hero_step_3"))
        self.steps_panel.sync_height(fallback_width=720)
        L4d2ThemeManager.apply_label_colors(self)


class FlowPanel(QWidget):
    """Responsive wrapping container keeping FlowLayout height synchronized cleanly."""

    heightChanged = Signal(int)

    def __init__(
        self,
        h_space: int = 6,
        v_space: int = 6,
        parent: Optional[QWidget] = None,
        is_tight: bool = True,
    ) -> None:
        super().__init__(parent)
        self.flow = FlowLayout(self, needAni=False, isTight=is_tight)
        self.flow.setContentsMargins(0, 0, 0, 0)
        self.flow.setHorizontalSpacing(h_space)
        self.flow.setVerticalSpacing(v_space)
        sp = QSizePolicy(QSizePolicy.Policy.Expanding, QSizePolicy.Policy.Minimum)
        sp.setHeightForWidth(True)
        self.setSizePolicy(sp)
        self._resize_sync_timer = QTimer(self)
        self._resize_sync_timer.setSingleShot(True)
        self._resize_sync_timer.setInterval(0)
        self._resize_sync_timer.timeout.connect(self._on_resize_sync_timeout)

    def hasHeightForWidth(self) -> bool:
        return True

    def heightForWidth(self, width: int) -> int:
        return self.flow.heightForWidth(max(1, width))

    def sizeHint(self) -> QSize:
        w = self.width() if (self.isVisible() and self.width() > 160) else 320
        h = max(0, self.flow.heightForWidth(w)) if self.flow.count() > 0 else 0
        return QSize(min(max(120, w), 260), h)

    def minimumSizeHint(self) -> QSize:
        return QSize(120, self.minimumHeight())

    def sync_height(self, fallback_width: int = 720) -> int:
        w = self.width() if (self.isVisible() and self.width() > 160) else fallback_width
        h = max(0, self.flow.heightForWidth(w)) if self.flow.count() > 0 else 0
        self.flow.invalidate()
        self.flow.activate()
        if h != self.minimumHeight():
            self.setMinimumHeight(h)
            self.updateGeometry()
            self.heightChanged.emit(h)
        return h

    def _on_resize_sync_timeout(self) -> None:
        if self.isVisible() and self.width() > 160 and self.flow.count() > 0:
            self.sync_height(self.width())

    def resizeEvent(self, event) -> None:
        super().resizeEvent(event)
        if self.isVisible() and self.width() > 160 and self.flow.count() > 0:
            self._resize_sync_timer.start()


class _CheckerboardImageLabel(ClickableImageLabel):
    """Clickable thumbnail label painting a subtle checkerboard behind transparent VTF textures."""

    def paintEvent(self, event) -> None:
        painter = QPainter(self)
        is_dark = isDarkTheme()
        tile = 8
        c1 = QColor("#1A1F28" if is_dark else "#DCD6C8")
        c2 = QColor("#252B36" if is_dark else "#EAE4D7")
        for y in range(0, self.height(), tile):
            for x in range(0, self.width(), tile):
                color = c1 if ((x // tile + y // tile) % 2 == 0) else c2
                painter.fillRect(x, y, tile, tile, color)
        painter.end()
        super().paintEvent(event)


class VguiPreviewStrip(QWidget):
    """Detailed preview grid for decoded VGUI .vtf/.vmt textures inside the loaded mod."""

    def __init__(
        self,
        i18n: Optional[LocalizationManager] = None,
        parent: Optional[QWidget] = None,
    ) -> None:
        super().__init__(parent)
        self._i18n = i18n or LocalizationManager("en-US")
        self._items: list[VguiPreviewItem] = []

        root = QVBoxLayout(self)
        root.setContentsMargins(0, 4, 0, 0)
        root.setSpacing(8)

        header = QHBoxLayout()
        header.setSpacing(6)
        self.icon_lbl = IconWidget(FluentIcon.PHOTO, self)
        self.icon_lbl.setFixedSize(14, 14)
        self.title_lbl = StrongBodyLabel("", self)
        header.addWidget(self.icon_lbl, 0, Qt.AlignmentFlag.AlignVCenter)
        header.addWidget(self.title_lbl)
        header.addStretch(1)
        root.addLayout(header)

        self.cards_grid = QGridLayout()
        self.cards_grid.setSpacing(8)
        root.addLayout(self.cards_grid)
        self.setVisible(False)

    def set_items(self, items: list[VguiPreviewItem]) -> None:
        self._items = list(items)
        self._rebuild()

    def retranslate_ui(self, i18n: LocalizationManager) -> None:
        self._i18n = i18n
        self._rebuild()

    def _clear_grid(self) -> None:
        while self.cards_grid.count():
            child = self.cards_grid.takeAt(0)
            w = child.widget()
            if w is not None:
                w.hide()
                w.setParent(None)
                w.deleteLater()

    def _slot_label(self, role: Optional[str]) -> str:
        mapping = {
            "lobby_icon": "vgui_slot_lobby",
            "in_game_icon": "vgui_slot_ingame",
            "incap_icon": "vgui_slot_incap",
        }
        return self._i18n.tr(mapping.get(role or "", "vgui_slot_other"))

    def _rebuild(self) -> None:
        self._clear_grid()
        if not self._items:
            self.setVisible(False)
            return

        self.setVisible(True)
        self.title_lbl.setText(self._i18n.tr_plural("vgui_preview_title", len(self._items)))
        is_dark = isDarkTheme()
        card_bg = COLORS.dark_card_alt if is_dark else COLORS.light_card_alt
        border = COLORS.dark_border if is_dark else COLORS.light_border

        max_cols = 3
        for idx, item in enumerate(self._items):
            card = QWidget(self)
            card.setObjectName("vguiSlotCard")
            L4d2ThemeManager.install_surface_motion(
                card,
                f"QWidget#vguiSlotCard {{ background-color: {{bg}}; "
                f"border: 1px solid {border}; border-radius: 6px; }}",
                tone="neutral",
            )
            row = QHBoxLayout(card)
            row.setContentsMargins(8, 8, 10, 8)
            row.setSpacing(10)

            thumb = _CheckerboardImageLabel(card)
            thumb.setObjectName("vguiThumbLabel")
            thumb.setFixedSize(64, 64)
            thumb.setAlignment(Qt.AlignmentFlag.AlignCenter)
            L4d2ThemeManager.install_surface_motion(
                thumb,
                "QLabel#vguiThumbLabel { border: 1px solid {border}; border-radius: 4px; }",
                border_colors=L4d2ThemeManager.image_border_colors(is_dark),
            )

            full_pixmap = QPixmap()
            if item.rgba_bytes and item.width > 0 and item.height > 0:
                img = QImage(
                    item.rgba_bytes,
                    item.width,
                    item.height,
                    item.width * 4,
                    QImage.Format.Format_RGBA8888,
                ).copy()
                full_pixmap = QPixmap.fromImage(img)

            if not full_pixmap.isNull():
                thumb.setPixmap(
                    full_pixmap.scaled(
                        60,
                        60,
                        Qt.AspectRatioMode.KeepAspectRatio,
                        Qt.TransformationMode.SmoothTransformation,
                    )
                )
                thumb.setCursor(Qt.CursorShape.PointingHandCursor)
                thumb.setToolTip(self._i18n.tr("vgui_zoom_tip"))
                badge = QLabel(thumb)
                badge.setFixedSize(16, 16)
                badge.move(64 - 18, 64 - 18)
                badge.setAlignment(Qt.AlignmentFlag.AlignCenter)
                badge.setAttribute(Qt.WidgetAttribute.WA_TransparentForMouseEvents, True)
                badge.setPixmap(FluentIcon.ZOOM_IN.icon(Theme.DARK).pixmap(10, 10))
                badge.setStyleSheet(
                    f"QLabel {{ background-color: rgba(15, 18, 24, 200); "
                    f"border: 1px solid {COLORS.amber}; border-radius: 3px; }}"
                )
                thumb.clicked.connect(
                    lambda pm=full_pixmap, it=item: self._open_zoom(pm, it)
                )
            else:
                thumb.setText("VTF")

            meta_box = QVBoxLayout()
            meta_box.setContentsMargins(0, 0, 0, 0)
            meta_box.setSpacing(2)
            role_lbl = StrongBodyLabel(self._slot_label(item.slot_role), card)
            file_name = PurePosixPath(item.vtf_path).name
            file_lbl = CaptionLabel(file_name, card)

            info_parts: list[str] = []
            if item.vtf_info is not None:
                v = item.vtf_info
                info_parts.append(f"{v.width}×{v.height}")
                info_parts.append(v.format_name)
                info_parts.append(
                    self._i18n.tr("vgui_alpha_yes" if v.has_alpha else "vgui_alpha_no")
                )
            spec_lbl = CaptionLabel(" · ".join(info_parts), card)

            extra_parts: list[str] = []
            if item.vtf_info is not None:
                extra_parts.append(
                    self._i18n.tr_plural("vgui_mips", item.vtf_info.mipmap_count)
                )
            if item.vmt_shader:
                extra_parts.append(item.vmt_shader)
            if item.vmt_basetexture:
                extra_parts.append(f"$basetexture: {item.vmt_basetexture}")
            extra_lbl = CaptionLabel(" · ".join(extra_parts), card)
            extra_lbl.setWordWrap(True)

            meta_box.addWidget(role_lbl)
            meta_box.addWidget(file_lbl)
            meta_box.addWidget(spec_lbl)
            if extra_parts:
                meta_box.addWidget(extra_lbl)
            meta_box.addStretch(1)

            row.addWidget(thumb)
            row.addLayout(meta_box, 1)
            self.cards_grid.addWidget(card, idx // max_cols, idx % max_cols)

    def _open_zoom(self, pixmap: QPixmap, item: VguiPreviewItem) -> None:
        title = f"{self._slot_label(item.slot_role)} — {PurePosixPath(item.vtf_path).name}"
        dlg = ImageZoomDialog(title=title, pixmap=pixmap, i18n=self._i18n, parent=self.window())
        dlg.exec()


class DropZoneCard(CardWidget):
    """Drag-and-drop mod selector card supporting .vpk, .zip/.rar/.7z archives, and extracted folders."""

    sourceSelected = Signal(Path)
    workshopRequested = Signal()
    workshopUrlRequested = Signal()

    def __init__(
        self,
        i18n: Optional[LocalizationManager] = None,
        parent: Optional[QWidget] = None,
    ) -> None:
        super().__init__(parent)
        self.setObjectName("dropZoneCard")
        self.setAcceptDrops(True)
        self._i18n = i18n or LocalizationManager("en-US")
        self._current_path: Optional[Path] = None
        self._last_info: Optional[DetectedModInfo] = None
        self._drag_over: bool = False
        self._hovered: bool = False
        self._hover_t: float = 0.0
        self._press_t: float = 0.0
        self._hover_anim = QVariantAnimation(self)
        self._hover_anim.setDuration(160)
        self._hover_anim.setEasingCurve(QEasingCurve.Type.OutCubic)
        self._hover_anim.valueChanged.connect(self._on_hover_val)
        self._press_anim = QVariantAnimation(self)
        self._press_anim.setDuration(90)
        self._press_anim.setEasingCurve(QEasingCurve.Type.OutCubic)
        self._press_anim.valueChanged.connect(self._on_press_val)
        self.setAttribute(Qt.WidgetAttribute.WA_Hover, True)

        root_layout = QVBoxLayout(self)
        root_layout.setContentsMargins(20, 16, 20, 16)
        root_layout.setSpacing(10)

        header_row = QHBoxLayout()
        header_row.setSpacing(8)
        self.title_icon = IconWidget(FluentIcon.ZIP_FOLDER, self)
        self.title_icon.setFixedSize(16, 16)
        self.title_label = StrongBodyLabel("", self)
        header_row.addWidget(self.title_icon, 0, Qt.AlignmentFlag.AlignVCenter)
        header_row.addWidget(self.title_label)
        header_row.addStretch(1)
        root_layout.addLayout(header_row)

        self.browse_btns_panel = FlowPanel(h_space=8, v_space=8, parent=self)
        self.browse_vpk_btn = PushButton(FluentIcon.DOCUMENT, "", self.browse_btns_panel)
        self.browse_dir_btn = PushButton(FluentIcon.FOLDER, "", self.browse_btns_panel)
        self.browse_workshop_btn = PushButton(FluentIcon.GAME, "", self.browse_btns_panel)
        self.link_workshop_btn = PushButton(FluentIcon.LINK, "", self.browse_btns_panel)
        for b in (
            self.browse_vpk_btn,
            self.browse_dir_btn,
            self.browse_workshop_btn,
            self.link_workshop_btn,
        ):
            b.setCursor(Qt.CursorShape.PointingHandCursor)
            self.browse_btns_panel.flow.addWidget(b)
        self.browse_btns_panel.sync_height(fallback_width=640)
        root_layout.addWidget(self.browse_btns_panel)

        self.path_label = BodyLabel("", self)
        self.path_label.setWordWrap(True)
        root_layout.addWidget(self.path_label)

        self.badges_layout = QHBoxLayout()
        self.badges_layout.setSpacing(8)
        self.badges_layout.addStretch(1)
        root_layout.addLayout(self.badges_layout)

        self.vgui_strip = VguiPreviewStrip(i18n=self._i18n, parent=self)
        root_layout.addWidget(self.vgui_strip)

        self.browse_vpk_btn.clicked.connect(self._on_browse_vpk)
        self.browse_dir_btn.clicked.connect(self._on_browse_dir)
        self.browse_workshop_btn.clicked.connect(self.workshopRequested.emit)
        self.link_workshop_btn.clicked.connect(self.workshopUrlRequested.emit)
        self.retranslate_ui(self._i18n)

    def _on_hover_val(self, val: object) -> None:
        self._hover_t = float(val)
        self.update()

    def _on_press_val(self, val: object) -> None:
        self._press_t = float(val)
        self.update()

    def enterEvent(self, event) -> None:
        self._hovered = True
        self._hover_anim.stop()
        self._hover_anim.setStartValue(self._hover_t)
        self._hover_anim.setEndValue(1.0)
        self._hover_anim.start()
        super().enterEvent(event)

    def leaveEvent(self, event) -> None:
        self._hovered = False
        self._hover_anim.stop()
        self._hover_anim.setStartValue(self._hover_t)
        self._hover_anim.setEndValue(0.0)
        self._hover_anim.start()
        if self._press_t > 0.0:
            self._press_anim.stop()
            self._press_anim.setStartValue(self._press_t)
            self._press_anim.setEndValue(0.0)
            self._press_anim.start()
        super().leaveEvent(event)

    def mousePressEvent(self, event: QMouseEvent) -> None:
        if event.button() == Qt.MouseButton.LeftButton:
            self._press_anim.stop()
            self._press_anim.setStartValue(self._press_t)
            self._press_anim.setEndValue(1.0)
            self._press_anim.start()
        super().mousePressEvent(event)

    def mouseReleaseEvent(self, event: QMouseEvent) -> None:
        self._press_anim.stop()
        self._press_anim.setStartValue(self._press_t)
        self._press_anim.setEndValue(0.0)
        self._press_anim.start()
        super().mouseReleaseEvent(event)

    def paintEvent(self, e) -> None:
        painter = QPainter(self)
        painter.setRenderHints(QPainter.Antialiasing)
        is_dark = isDarkTheme()

        if self._drag_over:
            bg = QColor("#241F12" if is_dark else "#FFF8E1")
            border_color = QColor(COLORS.amber_bright if is_dark else COLORS.red)
            pen_width = 2.2
        else:
            idle_bg, hover_bg, press_bg = L4d2ThemeManager.surface_palette(is_dark, "card")
            bg = lerp_color(lerp_color(idle_bg, hover_bg, self._hover_t), press_bg, self._press_t)
            border_color = QColor(COLORS.amber if is_dark else COLORS.amber_deep)
            pen_width = 1.6

        rect = QRectF(self.rect()).adjusted(2, 2, -2, -2)
        pen = QPen(border_color, pen_width, Qt.DashLine)
        painter.setPen(pen)
        painter.setBrush(bg)
        painter.drawRoundedRect(rect, 8, 8)

    def dragEnterEvent(self, event: QDragEnterEvent) -> None:
        if event.mimeData().hasUrls():
            for url in event.mimeData().urls():
                local = Path(url.toLocalFile())
                if ArchiveSourceManager.is_supported_drop_path(local):
                    self._drag_over = True
                    self.update()
                    event.acceptProposedAction()
                    return
        event.ignore()

    def dragLeaveEvent(self, event: QDragLeaveEvent) -> None:
        self._drag_over = False
        self.update()
        super().dragLeaveEvent(event)

    def dropEvent(self, event: QDropEvent) -> None:
        self._drag_over = False
        self.update()
        for url in event.mimeData().urls():
            local = Path(url.toLocalFile())
            if ArchiveSourceManager.is_supported_drop_path(local):
                self.sourceSelected.emit(local)
                event.acceptProposedAction()
                return

    def set_detected_info(
        self,
        info: DetectedModInfo,
        display_path: Optional[str] = None,
        vgui_items: Optional[list[VguiPreviewItem]] = None,
    ) -> None:
        self._last_info = info
        self._current_path = info.source_path
        self.path_label.setText(display_path or str(info.source_path))
        self._rebuild_badges(info)
        if vgui_items is None:
            vgui_items = (
                extract_vgui_previews(info.source_path, info.detected_origin)
                if info.has_vgui
                else []
            )
        self.vgui_strip.set_items(vgui_items)

    def clear(self) -> None:
        """Reset loaded mod display, badges, and VGUI previews back to idle placeholder."""
        self._last_info = None
        self._current_path = None
        self._drag_over = False
        self._clear_badges()
        self.path_label.setText(self._i18n.tr("drop_placeholder"))
        self.vgui_strip.set_items([])
        self.update()

    def _rebuild_badges(self, info: DetectedModInfo) -> None:
        self._clear_badges()
        if info.detected_origin:
            origin_name = SurvivorRegistry.get(info.detected_origin).display_name
            self._add_badge(self._i18n.tr("badge_origin", origin=origin_name), InfoLevel.SUCCESS)
        else:
            self._add_badge(self._i18n.tr("badge_origin_unknown"), InfoLevel.WARNING)

        self._add_badge(
            self._i18n.tr("badge_arms_yes" if info.has_arms else "badge_arms_no"),
            InfoLevel.INFOAMTION,
        )
        self._add_badge(
            self._i18n.tr("badge_vgui_yes" if info.has_vgui else "badge_vgui_no"),
            InfoLevel.INFOAMTION,
        )
        if info.has_physics:
            self._add_badge(self._i18n.tr("badge_physics_yes"), InfoLevel.INFOAMTION)
        if info.has_light_models:
            self._add_badge(
                self._i18n.tr("badge_light_models", count=len(info.light_models)),
                InfoLevel.WARNING,
            )
        self.badges_layout.addStretch(1)

    def retranslate_ui(self, i18n: LocalizationManager) -> None:
        self._i18n = i18n
        self.title_label.setText(i18n.tr("drop_title"))
        self.browse_vpk_btn.setText(i18n.tr("drop_browse_vpk"))
        self.browse_dir_btn.setText(i18n.tr("drop_browse_dir"))
        self.browse_workshop_btn.setText(i18n.tr("drop_browse_workshop"))
        self.link_workshop_btn.setText(i18n.tr("drop_browse_link"))
        self.vgui_strip.retranslate_ui(i18n)
        if self._last_info is not None:
            self._rebuild_badges(self._last_info)
        else:
            self.path_label.setText(i18n.tr("drop_placeholder"))

    def _clear_badges(self) -> None:
        while self.badges_layout.count():
            item = self.badges_layout.takeAt(0)
            widget = item.widget()
            if widget is not None:
                widget.hide()
                widget.setParent(None)
                widget.deleteLater()

    def _add_badge(self, text: str, level: InfoLevel) -> None:
        badge = InfoBadge(text, self, level=level)
        self.badges_layout.addWidget(badge)

    def _on_browse_vpk(self) -> None:
        path_str, _ = QFileDialog.getOpenFileName(
            self,
            self._i18n.tr("dlg_select_vpk_title"),
            "",
            self._i18n.tr("dlg_select_vpk_filter"),
        )
        if path_str:
            self.sourceSelected.emit(Path(path_str))

    def _on_browse_dir(self) -> None:
        dir_str = QFileDialog.getExistingDirectory(self, self._i18n.tr("dlg_select_dir_title"))
        if dir_str:
            self.sourceSelected.emit(Path(dir_str))


_FEMALE_SURVIVORS = frozenset({SurvivorId.ZOEY, SurvivorId.ROCHELLE})


def survivor_gender(survivor_id: SurvivorId) -> str:
    """Return 'female' for Zoey/Rochelle and 'male' for the remaining L4D1/L4D2 crew."""
    return "female" if survivor_id in _FEMALE_SURVIVORS else "male"


def draw_person_glyph(
    painter: QPainter,
    x: float,
    y: float,
    size: float,
    color: QColor,
    female: bool,
) -> None:
    """Paint the minimalist head-and-shoulders male or female silhouette glyph."""
    painter.save()
    painter.translate(x, y)
    scale = size / 24.0
    painter.scale(scale, scale)
    painter.setPen(
        QPen(
            color,
            1.85,
            Qt.PenStyle.SolidLine,
            Qt.PenCapStyle.RoundCap,
            Qt.PenJoinStyle.RoundJoin,
        )
    )
    painter.setBrush(Qt.BrushStyle.NoBrush)
    if female:
        painter.drawEllipse(QPointF(12.0, 8.2), 3.0, 3.0)
        hair = QPainterPath()
        hair.moveTo(6.6, 13.0)
        hair.cubicTo(6.3, 9.6, 7.6, 4.0, 12.0, 3.6)
        hair.cubicTo(16.4, 4.0, 17.7, 9.6, 17.4, 13.0)
        painter.drawPath(hair)
        shoulders = QPainterPath()
        shoulders.moveTo(6.2, 20.2)
        shoulders.cubicTo(6.5, 16.6, 8.8, 14.6, 12.0, 14.6)
        shoulders.cubicTo(15.2, 14.6, 17.5, 16.6, 17.8, 20.2)
        painter.drawPath(shoulders)
    else:
        painter.drawEllipse(QPointF(12.0, 7.5), 3.5, 3.5)
        shoulders = QPainterPath()
        shoulders.moveTo(5.2, 20.0)
        shoulders.cubicTo(5.2, 16.0, 8.2, 13.8, 12.0, 13.8)
        shoulders.cubicTo(15.8, 13.8, 18.8, 16.0, 18.8, 20.0)
        painter.drawPath(shoulders)
    painter.restore()


class SurvivorSelectButton(QPushButton):
    """Animated, uniformly bordered L4D2 survivor target button with smooth hover & selection states."""

    def __init__(
        self,
        text: str = "",
        parent: Optional[QWidget] = None,
        gender: Optional[str] = None,
    ) -> None:
        super().__init__(text, parent)
        self.setCheckable(True)
        self.setMinimumHeight(48)
        self.setCursor(Qt.CursorShape.PointingHandCursor)

        self._gender: Optional[str] = gender
        self._hover_t: float = 0.0
        self._press_t: float = 0.0
        self._check_t: float = 1.0 if self.isChecked() else 0.0
        self._is_origin: bool = False

        self._hover_anim = QVariantAnimation(self)
        self._hover_anim.setDuration(150)
        self._hover_anim.setEasingCurve(QEasingCurve.Type.OutCubic)
        self._hover_anim.valueChanged.connect(self._on_hover_anim_value)

        self._press_anim = QVariantAnimation(self)
        self._press_anim.setDuration(90)
        self._press_anim.setEasingCurve(QEasingCurve.Type.OutCubic)
        self._press_anim.valueChanged.connect(self._on_press_anim_value)

        self._check_anim = QVariantAnimation(self)
        self._check_anim.setDuration(170)
        self._check_anim.setEasingCurve(QEasingCurve.Type.OutCubic)
        self._check_anim.valueChanged.connect(self._on_check_anim_value)

        self.toggled.connect(self._animate_checked)

    def _on_hover_anim_value(self, value: float) -> None:
        self._hover_t = float(value)
        self.update()

    def _on_press_anim_value(self, value: float) -> None:
        self._press_t = float(value)
        self.update()

    def _on_check_anim_value(self, value: float) -> None:
        self._check_t = float(value)
        self.update()

    def _animate_checked(self, checked: bool) -> None:
        self._check_anim.stop()
        self._check_anim.setStartValue(self._check_t)
        self._check_anim.setEndValue(1.0 if checked else 0.0)
        self._check_anim.start()

    def set_origin_blocked(self, is_origin: bool) -> None:
        """Mark button as the locked source survivor (red dashed) vs inherited/locked target."""
        if self._is_origin == is_origin:
            return
        self._is_origin = is_origin
        self.update()

    def setChecked(self, checked: bool) -> None:
        super().setChecked(checked)
        if self.signalsBlocked() or not self.isEnabled():
            self._check_anim.stop()
            self._check_t = 1.0 if checked else 0.0
            self.update()

    def setEnabled(self, enabled: bool) -> None:
        super().setEnabled(enabled)
        self.setCursor(
            Qt.CursorShape.PointingHandCursor if enabled else Qt.CursorShape.ArrowCursor
        )
        if not enabled:
            self._hover_anim.stop()
            self._hover_t = 0.0
        self.update()

    def enterEvent(self, e) -> None:
        super().enterEvent(e)
        if self.isEnabled():
            self._hover_anim.stop()
            self._hover_anim.setStartValue(self._hover_t)
            self._hover_anim.setEndValue(1.0)
            self._hover_anim.start()

    def leaveEvent(self, e) -> None:
        super().leaveEvent(e)
        self._hover_anim.stop()
        self._hover_anim.setStartValue(self._hover_t)
        self._hover_anim.setEndValue(0.0)
        self._hover_anim.start()
        if self._press_t > 0.0:
            self._press_anim.stop()
            self._press_anim.setStartValue(self._press_t)
            self._press_anim.setEndValue(0.0)
            self._press_anim.start()

    def mousePressEvent(self, e: QMouseEvent) -> None:
        if e.button() == Qt.MouseButton.LeftButton and self.isEnabled():
            self._press_anim.stop()
            self._press_anim.setStartValue(self._press_t)
            self._press_anim.setEndValue(1.0)
            self._press_anim.start()
        super().mousePressEvent(e)

    def mouseReleaseEvent(self, e: QMouseEvent) -> None:
        self._press_anim.stop()
        self._press_anim.setStartValue(self._press_t)
        self._press_anim.setEndValue(0.0)
        self._press_anim.start()
        super().mouseReleaseEvent(e)

    def _draw_label_and_icon(
        self,
        painter: QPainter,
        rect: QRectF,
        font: QFont,
        text_color: QColor,
    ) -> None:
        painter.setFont(font)
        painter.setPen(text_color)
        label_text = self.text()
        if self._gender not in ("male", "female") or rect.width() < 110.0:
            painter.drawText(rect, Qt.AlignmentFlag.AlignCenter, label_text)
            return

        icon_size = 15.0
        gap = 6.0
        text_w = float(QFontMetrics(font).horizontalAdvance(label_text))
        total_w = icon_size + gap + text_w
        start_x = max(rect.left() + 10.0, rect.center().x() - total_w / 2.0)
        icon_y = rect.center().y() - icon_size / 2.0
        draw_person_glyph(
            painter,
            start_x,
            icon_y,
            icon_size,
            text_color,
            female=(self._gender == "female"),
        )
        text_rect = QRectF(
            start_x + icon_size + gap,
            rect.top(),
            max(10.0, rect.right() - (start_x + icon_size + gap) - 8.0),
            rect.height(),
        )
        painter.drawText(
            text_rect,
            Qt.AlignmentFlag.AlignVCenter | Qt.AlignmentFlag.AlignLeft,
            label_text,
        )

    def paintEvent(self, e) -> None:
        painter = QPainter(self)
        painter.setRenderHints(QPainter.Antialiasing)
        is_dark = isDarkTheme()

        rect = QRectF(self.rect()).adjusted(1.5, 1.5, -1.5, -1.5)
        radius = 8.0

        if not self.isEnabled():
            if self._is_origin:
                bg = QColor("#1D1214" if is_dark else "#F9ECEC")
                border_color = QColor(COLORS.red)
                text_color = QColor("#F87171" if is_dark else COLORS.red_dark)
                pen = QPen(border_color, 1.4, Qt.DashLine)
            elif self.isChecked():
                bg = QColor("#36280E" if is_dark else "#F6E3AD")
                border_color = QColor("#A6771B" if is_dark else "#B5841A")
                text_color = QColor("#F5C85B" if is_dark else "#4E3806")
                pen = QPen(border_color, 1.4, Qt.SolidLine)
            else:
                bg = QColor("#181B21" if is_dark else "#ECE8DF")
                border_color = QColor("#2D333E" if is_dark else "#C7C0B3")
                text_color = QColor("#6E7684" if is_dark else "#837D72")
                pen = QPen(border_color, 1.2, Qt.SolidLine)

            painter.setPen(pen)
            painter.setBrush(bg)
            painter.drawRoundedRect(rect, radius, radius)

            font = QFont(self.font())
            font.setBold(self._is_origin or self.isChecked())
            self._draw_label_and_icon(painter, rect, font, text_color)

            if not self._is_origin and self.isChecked():
                painter.drawText(
                    rect.adjusted(0, 0, -8, 0),
                    Qt.AlignmentFlag.AlignVCenter | Qt.AlignmentFlag.AlignRight,
                    "✓",
                )
            return

        idle_bg = QColor(COLORS.dark_card_alt if is_dark else COLORS.light_card)
        hover_bg = QColor("#222731" if is_dark else "#EFEBE1")
        press_bg = QColor("#2A303C" if is_dark else "#E5DFD2")
        idle_border = QColor(COLORS.dark_border if is_dark else COLORS.light_border)
        hover_border = QColor("#3D4555" if is_dark else "#8E8677")
        idle_text = QColor(COLORS.dark_text if is_dark else COLORS.light_text)

        unchecked_bg = _lerp_color(_lerp_color(idle_bg, hover_bg, self._hover_t), press_bg, self._press_t)
        unchecked_border = _lerp_color(idle_border, hover_border, self._hover_t)

        checked_idle_bg = QColor(COLORS.amber)
        checked_hover_bg = QColor(COLORS.amber_bright)
        checked_bg = _lerp_color(
            _lerp_color(checked_idle_bg, checked_hover_bg, self._hover_t),
            QColor("#D99B00"),
            self._press_t,
        )
        checked_border = _lerp_color(QColor(COLORS.red), QColor(COLORS.red_hover), self._hover_t)
        checked_text = QColor("#111315")

        bg = _lerp_color(unchecked_bg, checked_bg, self._check_t)
        border = _lerp_color(unchecked_border, checked_border, self._check_t)
        text_color = _lerp_color(idle_text, checked_text, self._check_t)
        border_width = 1.4 + 0.35 * self._hover_t + 0.5 * self._check_t

        painter.setPen(QPen(border, border_width))
        painter.setBrush(bg)
        painter.drawRoundedRect(rect, radius, radius)

        font = QFont(self.font())
        font.setWeight(QFont.Weight.Bold if self._check_t > 0.5 else QFont.Weight.DemiBold)
        self._draw_label_and_icon(painter, rect, font, text_color)

        if self._check_t > 0.15:
            check_color = QColor("#111315")
            check_color.setAlpha(int(220 * self._check_t))
            painter.setPen(check_color)
            check_rect = rect.adjusted(0, 0, -10, 0)
            painter.drawText(
                check_rect,
                Qt.AlignmentFlag.AlignVCenter | Qt.AlignmentFlag.AlignRight,
                "✓",
            )


class SurvivorCrewsPanel(FlowPanel):
    """Two categorized 2x2 sub-cards grouping L4D1 and L4D2 survivors compactly."""

    def __init__(
        self,
        button_min_width: int = 148,
        button_min_height: int = 40,
        fallback_width: int = 680,
        on_toggled: Optional[Callable[[], None]] = None,
        i18n: Optional[LocalizationManager] = None,
        parent: Optional[QWidget] = None,
    ) -> None:
        super().__init__(h_space=12, v_space=10, parent=parent, is_tight=True)
        self.setObjectName("survivorCrewsPanel")
        self._i18n = i18n or LocalizationManager("en-US")
        self._fallback_width = fallback_width
        self._button_min_width = button_min_width
        self._button_min_height = button_min_height
        self._on_toggled = on_toggled
        self.buttons: dict[SurvivorId, SurvivorSelectButton] = {}

        self.l4d1_card, self.l4d1_section_label = self._build_crew_card("L4D1", "crewL4d1Badge")
        self.l4d2_card, self.l4d2_section_label = self._build_crew_card("L4D2", "crewSectionBadge")
        self.flow.addWidget(self.l4d1_card)
        self.flow.addWidget(self.l4d2_card)
        self.retranslate_ui(self._i18n)

    def _build_crew_card(self, generation: str, badge_object_name: str) -> tuple[QFrame, StrongBodyLabel]:
        card = QFrame(self)
        card.setObjectName("crewGroupCard")
        card.setSizePolicy(QSizePolicy.Policy.Preferred, QSizePolicy.Policy.Minimum)
        lay = QVBoxLayout(card)
        lay.setContentsMargins(12, 9, 12, 11)
        lay.setSpacing(8)

        section_label = StrongBodyLabel("", card)
        section_label.setObjectName(badge_object_name)
        lay.addLayout(
            create_icon_row(
                HandIconWidget(card, size=18, generation=generation),
                section_label,
                card,
                size=18,
                spacing=7,
            )
        )

        grid = QGridLayout()
        grid.setContentsMargins(0, 0, 0, 0)
        grid.setSpacing(8)
        specs = [s for s in SurvivorRegistry.all() if s.generation == generation]
        for idx, spec in enumerate(specs):
            btn = SurvivorSelectButton(
                spec.display_name,
                card,
                gender=survivor_gender(spec.id),
            )
            btn.setMinimumWidth(self._button_min_width)
            btn.setMinimumHeight(self._button_min_height)
            if self._on_toggled is not None:
                btn.toggled.connect(lambda _checked: self._on_toggled())
            self.buttons[spec.id] = btn
            grid.addWidget(btn, idx // 2, idx % 2)
        lay.addLayout(grid)
        return card, section_label

    def retranslate_ui(self, i18n: LocalizationManager) -> None:
        self._i18n = i18n
        is_dark = isDarkTheme()
        border = COLORS.dark_border if is_dark else COLORS.light_border
        card_qss = (
            f"QFrame#crewGroupCard {{ background-color: {{bg}}; border: 1px solid {border}; border-radius: 7px; }}"
        )
        for card in (self.l4d1_card, self.l4d2_card):
            L4d2ThemeManager.install_surface_motion(card, card_qss, tone="neutral")
        self.l4d1_section_label.setText(i18n.tr("crew_l4d1_label"))
        self.l4d2_section_label.setText(i18n.tr("crew_l4d2_label"))
        L4d2ThemeManager.apply_label_colors(self)
        self.l4d1_card.updateGeometry()
        self.l4d2_card.updateGeometry()
        self.sync_height(fallback_width=max(self._fallback_width, self.width()))


class SurvivorGridPicker(HeaderCardWidget):
    """Visual 8-survivor selector grouped clearly into L4D1 and L4D2 crews."""

    selectionChanged = Signal(list)

    def __init__(
        self,
        i18n: Optional[LocalizationManager] = None,
        parent: Optional[QWidget] = None,
    ) -> None:
        super().__init__(parent)
        self._i18n = i18n or LocalizationManager("en-US")
        self._origin: Optional[SurvivorId] = None
        add_card_header_icon(self, FluentIcon.PEOPLE)

        container = QWidget(self)
        vbox = QVBoxLayout(container)
        vbox.setContentsMargins(0, 0, 0, 0)
        vbox.setSpacing(12)

        self.hint_label = CaptionLabel("", self)
        vbox.addWidget(self.hint_label)

        self.quick_panel = FlowPanel(h_space=8, v_space=6, parent=container)
        self.btn_all = PushButton(FluentIcon.TILES, "", self.quick_panel)
        self.btn_l4d1 = PushButton(FluentIcon.PEOPLE, "", self.quick_panel)
        self.btn_l4d2 = PushButton(FluentIcon.PEOPLE, "", self.quick_panel)
        self.btn_clear = PushButton(FluentIcon.ERASE_TOOL, "", self.quick_panel)
        for btn in (self.btn_all, self.btn_l4d1, self.btn_l4d2, self.btn_clear):
            btn.setCursor(Qt.CursorShape.PointingHandCursor)
            self.quick_panel.flow.addWidget(btn)
        self.quick_panel.sync_height(fallback_width=640)
        vbox.addWidget(self.quick_panel)

        self.crews_panel = SurvivorCrewsPanel(
            button_min_width=148,
            button_min_height=40,
            fallback_width=680,
            on_toggled=self._emit_selection,
            i18n=self._i18n,
            parent=container,
        )
        self._buttons = self.crews_panel.buttons
        self.l4d1_card = self.crews_panel.l4d1_card
        self.l4d2_card = self.crews_panel.l4d2_card
        self.l4d1_section_label = self.crews_panel.l4d1_section_label
        self.l4d2_section_label = self.crews_panel.l4d2_section_label
        vbox.addWidget(self.crews_panel)

        self.viewLayout.addWidget(container)

        self.btn_all.clicked.connect(lambda: self._select_group(None))
        self.btn_l4d1.clicked.connect(lambda: self._select_group("L4D1"))
        self.btn_l4d2.clicked.connect(lambda: self._select_group("L4D2"))
        self.btn_clear.clicked.connect(self.clear_selection)

        self.retranslate_ui(self._i18n)

    def set_origin_survivor(self, origin: Optional[SurvivorId]) -> None:
        self._origin = origin
        self._refresh_button_labels()
        self._emit_selection()

    def _refresh_button_labels(self) -> None:
        origin_tag = self._i18n.tr("origin_tag")
        for sid, btn in self._buttons.items():
            spec = SurvivorRegistry.get(sid)
            is_origin = self._origin is not None and sid == self._origin
            btn.set_origin_blocked(is_origin)
            btn.setEnabled(not is_origin)
            if is_origin:
                btn.setText(f"{spec.display_name}  ·  {origin_tag}")
                if btn.isChecked():
                    btn.blockSignals(True)
                    btn.setChecked(False)
                    btn.blockSignals(False)
            else:
                btn.setText(spec.display_name)

    def retranslate_ui(self, i18n: LocalizationManager) -> None:
        self._i18n = i18n
        self.setTitle(i18n.tr("dest_card_title"))
        self.hint_label.setText(i18n.tr("dest_hint"))
        self.btn_all.setText(i18n.tr("btn_all_others"))
        self.btn_l4d1.setText(i18n.tr("btn_l4d1_crew"))
        self.btn_l4d2.setText(i18n.tr("btn_l4d2_crew"))
        self.btn_clear.setText(i18n.tr("btn_clear"))
        self.quick_panel.sync_height(max(520, self.quick_panel.width()))
        self.crews_panel.retranslate_ui(i18n)
        self._refresh_button_labels()
        L4d2ThemeManager.apply_label_colors(self)

    def selected_survivors(self) -> list[SurvivorId]:
        return [sid for sid, btn in self._buttons.items() if btn.isEnabled() and btn.isChecked()]

    def clear_selection(self) -> None:
        for btn in self._buttons.values():
            btn.blockSignals(True)
            btn.setChecked(False)
            btn.blockSignals(False)
        self._emit_selection()

    def _select_group(self, generation: Optional[str]) -> None:
        for sid, btn in self._buttons.items():
            spec = SurvivorRegistry.get(sid)
            should_check = (
                btn.isEnabled()
                and (generation is None or spec.generation == generation)
            )
            btn.blockSignals(True)
            btn.setChecked(should_check)
            btn.blockSignals(False)
        self._emit_selection()

    def _emit_selection(self) -> None:
        self.selectionChanged.emit(self.selected_survivors())


class ProgressLogCard(HeaderCardWidget):
    """Displays step progress bar and collapsible technical output logs."""

    def __init__(
        self,
        i18n: Optional[LocalizationManager] = None,
        parent: Optional[QWidget] = None,
    ) -> None:
        super().__init__(parent)
        self._i18n = i18n or LocalizationManager("en-US")
        self._has_custom_status = False
        add_card_header_icon(self, FluentIcon.COMMAND_PROMPT)

        container = QWidget(self)
        layout = QVBoxLayout(container)
        layout.setContentsMargins(0, 0, 0, 0)
        layout.setSpacing(8)

        status_row = QHBoxLayout()
        status_row.setSpacing(10)
        self.percent_label = StrongBodyLabel("0%", self)
        self.status_label = BodyLabel("", self)
        self.copy_log_btn = PushButton(FluentIcon.COPY, "", self)
        self.copy_log_btn.setEnabled(False)
        self.copy_log_btn.setCursor(Qt.CursorShape.PointingHandCursor)
        self.toggle_log_btn = PushButton(FluentIcon.VIEW, "", self)
        self.toggle_log_btn.setCheckable(True)
        self.toggle_log_btn.setCursor(Qt.CursorShape.PointingHandCursor)
        status_row.addWidget(self.percent_label)
        status_row.addWidget(self.status_label, 1)
        status_row.addWidget(self.copy_log_btn)
        status_row.addWidget(self.toggle_log_btn)
        layout.addLayout(status_row)

        self.progress_bar = ProgressBar(self)
        self.progress_bar.setRange(0, 100)
        self.progress_bar.setValue(0)
        layout.addWidget(self.progress_bar)

        self.log_view = TextEdit(self)
        self.log_view.setReadOnly(True)
        self.log_view.setMinimumHeight(180)
        self.log_view.setVisible(False)
        layout.addWidget(self.log_view)

        self._copy_reset_timer = QTimer(self)
        self._copy_reset_timer.setSingleShot(True)
        self._copy_reset_timer.timeout.connect(self._restore_copy_btn_label)

        self.copy_log_btn.clicked.connect(self._on_copy_log)
        self.toggle_log_btn.toggled.connect(self._on_toggle_logs)
        self.viewLayout.addWidget(container)
        self.retranslate_ui(self._i18n)

    def reset(self) -> None:
        self._has_custom_status = True
        self._copy_reset_timer.stop()
        self.progress_bar.setValue(0)
        self.percent_label.setText("0%")
        self.status_label.setText(self._i18n.tr("progress_starting"))
        self.log_view.clear()
        self.copy_log_btn.setEnabled(False)
        self._restore_copy_btn_label()

    def reset_idle(self) -> None:
        """Clear logs and return progress display to the idle ready state."""
        self._has_custom_status = False
        self._copy_reset_timer.stop()
        self.progress_bar.setValue(0)
        self.percent_label.setText("0%")
        self.status_label.setText(self._i18n.tr("progress_ready"))
        self.log_view.clear()
        self.copy_log_btn.setEnabled(False)
        self._restore_copy_btn_label()

    def update_progress(self, percent: int, message: str) -> None:
        self._has_custom_status = True
        pct = max(0, min(100, percent))
        self.progress_bar.setValue(pct)
        self.percent_label.setText(f"{pct}%")
        self.status_label.setText(message)
        self.append_log(f"[{pct:3d}%] {message}")

    def append_log(self, text: str) -> None:
        if text.strip():
            self.log_view.append(text)
            self.copy_log_btn.setEnabled(True)

    def retranslate_ui(self, i18n: LocalizationManager) -> None:
        self._i18n = i18n
        self.setTitle(i18n.tr("progress_title"))
        if not self._has_custom_status:
            self.status_label.setText(i18n.tr("progress_ready"))
        if not self._copy_reset_timer.isActive():
            self._restore_copy_btn_label()
        self._sync_toggle_log_btn()

    def _restore_copy_btn_label(self) -> None:
        self.copy_log_btn.setText(self._i18n.tr("btn_copy_log"))

    def _sync_toggle_log_btn(self) -> None:
        checked = self.toggle_log_btn.isChecked()
        self.toggle_log_btn.setIcon(FluentIcon.HIDE if checked else FluentIcon.VIEW)
        self.toggle_log_btn.setText(
            self._i18n.tr("btn_hide_log") if checked else self._i18n.tr("btn_show_log")
        )

    def _on_copy_log(self) -> None:
        copy_text_with_feedback(
            self.copy_log_btn,
            self.log_view.toPlainText(),
            self._i18n.tr("btn_copied"),
            self._copy_reset_timer,
        )

    def _on_toggle_logs(self, checked: bool) -> None:
        self.log_view.setVisible(checked)
        self._sync_toggle_log_btn()
