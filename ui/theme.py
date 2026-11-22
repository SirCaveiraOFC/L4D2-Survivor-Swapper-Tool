from __future__ import annotations

from dataclasses import dataclass
from typing import Optional

from PySide6.QtCore import (
    QEasingCurve,
    QEvent,
    QObject,
    QPoint,
    QRect,
    QRectF,
    QSize,
    QTimer,
    QVariantAnimation,
    Qt,
)
from PySide6.QtGui import QColor, QGuiApplication, QIcon, QIconEngine, QPainter, QPainterPath, QPixmap
from PySide6.QtWidgets import QAbstractButton, QAbstractScrollArea, QWidget
from qfluentwidgets import (
    CardWidget,
    ComboBox,
    FluentIcon,
    FluentIconBase,
    FluentStyleSheet,
    FluentWindow,
    LineEdit,
    PlainTextEdit,
    SimpleCardWidget,
    SwitchButton,
    TextEdit,
    Theme,
    isDarkTheme,
    setTheme,
    setThemeColor,
)

try:
    import winreg
except ImportError:
    winreg = None


@dataclass(frozen=True)
class L4d2Colors:
    """Left 4 Dead 2 visual identity color tokens (Yellow, Red, Black, White)."""

    amber: str = "#F5B700"
    amber_bright: str = "#FFD028"
    amber_deep: str = "#C98E00"
    red: str = "#D92B2B"
    red_hover: str = "#E53E3E"
    red_dark: str = "#991B1B"

    dark_window: str = "#0B0D10"
    dark_card: str = "#14181F"
    dark_card_alt: str = "#1B202A"
    dark_border: str = "#2C323D"
    dark_text: str = "#F5F6F8"
    dark_muted: str = "#A8B0BE"

    light_window: str = "#D8D2C5"
    light_card: str = "#FCFBF8"
    light_card_alt: str = "#EAE5DA"
    light_border: str = "#9F9788"
    light_text: str = "#111315"
    light_muted: str = "#383E48"


COLORS = L4d2Colors()


class _CursorSyncFilter(QObject):
    """Keeps control cursors aligned to PointingHandCursor whenever enabled state changes."""

    def eventFilter(self, obj: QObject, event: QEvent) -> bool:
        if event.type() == QEvent.Type.EnabledChange and isinstance(obj, QWidget):
            obj.setCursor(
                Qt.CursorShape.PointingHandCursor
                if obj.isEnabled()
                else Qt.CursorShape.ArrowCursor
            )
        return super().eventFilter(obj, event)


class _CardHoverOverlay(QWidget):
    """Paints a crisp rounded hover highlight border above fluent CardWidget/HeaderCardWidget."""

    def __init__(self, parent: QWidget) -> None:
        super().__init__(parent)
        self.setObjectName("l4d2CardHoverOverlay")
        self.setAttribute(Qt.WidgetAttribute.WA_TransparentForMouseEvents, True)
        self.setAttribute(Qt.WidgetAttribute.WA_NoSystemBackground, True)
        self.setAutoFillBackground(False)
        self._hover_t: float = 0.0
        self._press_t: float = 0.0
        self._hover_target: bool = False
        self._press_target: bool = False

        self._hover_anim = QVariantAnimation(self)
        self._hover_anim.setDuration(160)
        self._hover_anim.setEasingCurve(QEasingCurve.Type.OutCubic)
        self._hover_anim.valueChanged.connect(self._on_hover_value)
        self._hover_anim.finished.connect(self._on_anim_finished)

        self._press_anim = QVariantAnimation(self)
        self._press_anim.setDuration(90)
        self._press_anim.setEasingCurve(QEasingCurve.Type.OutCubic)
        self._press_anim.valueChanged.connect(self._on_press_value)
        self._press_anim.finished.connect(self._on_anim_finished)
        self.hide()

    def _on_hover_value(self, value: object) -> None:
        self._hover_t = float(value)
        self.update()

    def _on_press_value(self, value: object) -> None:
        self._press_t = float(value)
        self.update()

    def _on_anim_finished(self) -> None:
        if (
            not self._hover_target
            and not self._press_target
            and self._hover_t <= 0.005
            and self._press_t <= 0.005
        ):
            self.hide()

    def set_hovered(self, hovered: bool) -> None:
        parent = self.parentWidget()
        target = bool(hovered)
        self._hover_target = target
        if target and parent is not None:
            self.setGeometry(parent.rect())
            self.show()
            self.raise_()
        else:
            self._press_target = False
            self._press_anim.stop()
            self._press_anim.setStartValue(self._press_t)
            self._press_anim.setEndValue(0.0)
            self._press_anim.start()
        self._hover_anim.stop()
        self._hover_anim.setStartValue(self._hover_t)
        self._hover_anim.setEndValue(1.0 if target else 0.0)
        self._hover_anim.start()

    def set_pressed(self, pressed: bool) -> None:
        parent = self.parentWidget()
        target = bool(pressed)
        self._press_target = target
        if target and parent is not None:
            self.setGeometry(parent.rect())
            self.show()
            self.raise_()
        self._press_anim.stop()
        self._press_anim.setStartValue(self._press_t)
        self._press_anim.setEndValue(1.0 if target else 0.0)
        self._press_anim.start()

    def paintEvent(self, _event) -> None:
        if (
            self.width() <= 2
            or self.height() <= 2
            or (self._hover_t <= 0.005 and self._press_t <= 0.005)
        ):
            return
        parent = self.parentWidget()
        is_dark = isDarkTheme()
        radius = 6.0
        if parent is not None:
            if hasattr(parent, "getBorderRadius"):
                try:
                    radius = float(parent.getBorderRadius())
                except Exception:
                    radius = float(getattr(parent, "borderRadius", 6) or 6)
            else:
                radius = float(getattr(parent, "borderRadius", 6) or 6)
        painter = QPainter(self)
        painter.setRenderHint(QPainter.RenderHint.Antialiasing)
        c = 255 if is_dark else 0
        alpha = int(round(12.0 * self._hover_t + 8.0 * self._press_t))
        fill = QColor(c, c, c, alpha)
        rect = QRectF(self.rect()).adjusted(1.0, 1.0, -1.0, -1.0)
        painter.setPen(Qt.PenStyle.NoPen)
        painter.setBrush(fill)
        painter.drawRoundedRect(rect, radius, radius)


class _CardHoverFilter(QObject):
    """Tracks pointer enter/leave, press, and resize events on fluent cards for hover transitions."""

    def eventFilter(self, obj: QObject, event: QEvent) -> bool:
        if isinstance(obj, QWidget):
            overlay = obj.findChild(
                _CardHoverOverlay,
                "l4d2CardHoverOverlay",
                Qt.FindChildOption.FindDirectChildrenOnly,
            )
            if overlay is not None:
                etype = event.type()
                if etype == QEvent.Type.Enter:
                    if obj.isEnabled():
                        overlay.set_hovered(True)
                elif etype in (QEvent.Type.Leave, QEvent.Type.Hide):
                    overlay.set_hovered(False)
                elif etype == QEvent.Type.MouseButtonPress and getattr(event, "button", lambda: None)() == Qt.MouseButton.LeftButton:
                    if obj.isEnabled():
                        overlay.set_pressed(True)
                elif etype == QEvent.Type.MouseButtonRelease:
                    overlay.set_pressed(False)
                elif etype in (QEvent.Type.Resize, QEvent.Type.Show):
                    overlay.setGeometry(obj.rect())
                    if overlay.isVisible():
                        overlay.raise_()
                elif etype == QEvent.Type.ChildAdded and overlay.isVisible():
                    overlay.raise_()
        return super().eventFilter(obj, event)


class _InputFocusOverlay(QWidget):
    """Paints an animated center-out crimson bottom focus bar on focused inputs."""

    def __init__(self, parent: QWidget) -> None:
        super().__init__(parent)
        self.setObjectName("l4d2InputFocusOverlay")
        self.setAttribute(Qt.WidgetAttribute.WA_TransparentForMouseEvents, True)
        self.setAttribute(Qt.WidgetAttribute.WA_NoSystemBackground, True)
        self.setAutoFillBackground(False)
        self._focus_t: float = 0.0
        self._focus_target: bool = False

        self._anim = QVariantAnimation(self)
        self._anim.setDuration(220)
        self._anim.setEasingCurve(QEasingCurve.Type.OutCubic)
        self._anim.valueChanged.connect(self._on_anim_value)
        self._anim.finished.connect(self._on_anim_finished)
        self.hide()

    def _on_anim_value(self, value: object) -> None:
        self._focus_t = float(value)
        self.update()

    def _on_anim_finished(self) -> None:
        if not self._focus_target and self._focus_t <= 0.005:
            self.hide()

    def set_focused(self, focused: bool, immediate: bool = False) -> None:
        """Animate or immediately snap the crimson focus underline in or out."""
        parent = self.parentWidget()
        target = bool(focused)
        self._focus_target = target
        if target and parent is not None:
            self.setGeometry(parent.rect())
            self.show()
            self.raise_()
        if immediate:
            self._anim.stop()
            self._focus_t = 1.0 if target else 0.0
            if not target:
                self.hide()
            self.update()
            return
        self._anim.stop()
        self._anim.setDuration(220 if target else 160)
        self._anim.setStartValue(self._focus_t)
        self._anim.setEndValue(1.0 if target else 0.0)
        self._anim.start()

    def paintEvent(self, _event) -> None:
        if self.width() <= 4 or self.height() <= 4 or self._focus_t <= 0.005:
            return
        parent = self.parentWidget()
        margins = parent.contentsMargins() if parent is not None else self.contentsMargins()
        left = float(margins.left())
        w = float(self.width() - margins.left() - margins.right())
        h = float(self.height())
        if w <= 2.0 or h <= 4.0:
            return

        outer = QPainterPath()
        outer.addRoundedRect(QRectF(left, h - 10.0, w, 10.0), 5.0, 5.0)
        cut = QPainterPath()
        cut.addRect(QRectF(left, h - 10.0, w, 7.8))
        bar_path = outer.subtracted(cut)

        cx = left + w * 0.5
        half_w = max(2.0, w * 0.5 * self._focus_t)

        color = lerp_color(QColor(COLORS.red_hover), QColor(COLORS.red), self._focus_t)
        color.setAlpha(int(round(255.0 * min(1.0, 0.25 + 0.75 * self._focus_t))))

        painter = QPainter(self)
        painter.setRenderHint(QPainter.RenderHint.Antialiasing)
        painter.setClipRect(QRectF(cx - half_w, h - 10.0, half_w * 2.0, 10.0))
        painter.setPen(Qt.PenStyle.NoPen)
        painter.fillPath(bar_path, color)


class _InputFocusFilter(QObject):
    """Synchronizes focus-in, focus-out, resize, and visibility events for input overlays."""

    def eventFilter(self, obj: QObject, event: QEvent) -> bool:
        if isinstance(obj, QWidget):
            overlay = obj.findChild(
                _InputFocusOverlay,
                "l4d2InputFocusOverlay",
                Qt.FindChildOption.FindDirectChildrenOnly,
            )
            if overlay is not None:
                etype = event.type()
                if etype == QEvent.Type.FocusIn:
                    if obj.isEnabled():
                        overlay.set_focused(True)
                elif etype == QEvent.Type.FocusOut:
                    overlay.set_focused(False)
                elif etype == QEvent.Type.Hide:
                    overlay.set_focused(False, immediate=True)
                elif etype in (QEvent.Type.Resize, QEvent.Type.Show):
                    overlay.setGeometry(obj.rect())
                    if overlay.isVisible():
                        overlay.raise_()
                elif etype == QEvent.Type.ChildAdded and overlay.isVisible():
                    overlay.raise_()
                elif etype == QEvent.Type.EnabledChange and not obj.isEnabled():
                    overlay.set_focused(False, immediate=True)
        return super().eventFilter(obj, event)


class _WindowRepaintFilter(QObject):
    """Synchronizes layout and full-subtree repaints across resize and multi-monitor moves."""

    def __init__(self, window: QWidget) -> None:
        super().__init__(window)
        self.setObjectName("l4d2WindowRepaintFilter")
        self._window = window
        self._refreshing = False
        self._pending_relayout = False
        self._last_size = window.size()
        self._last_dpr = float(window.devicePixelRatioF())
        self._connected_handle = None
        self._connected_screen = None
        self._screen_change_event = getattr(QEvent.Type, "ScreenChangeInternal", None)

        self._immediate_timer = QTimer(self)
        self._immediate_timer.setSingleShot(True)
        self._immediate_timer.setInterval(0)
        self._immediate_timer.timeout.connect(self._flush_refresh)

        self._settle_timer = QTimer(self)
        self._settle_timer.setSingleShot(True)
        self._settle_timer.setInterval(60)
        self._settle_timer.timeout.connect(self._flush_settled)

        self._state_settle_timer = QTimer(self)
        self._state_settle_timer.setSingleShot(True)
        self._state_settle_timer.setInterval(160)
        self._state_settle_timer.timeout.connect(self._flush_settled)

        stacked = getattr(window, "stackedWidget", None)
        if stacked is not None and hasattr(stacked, "currentChanged"):
            stacked.currentChanged.connect(lambda _idx: self.trigger(relayout=True))

        window.installEventFilter(self)
        self._bind_screen_signals()

    def _bind_screen_signals(self) -> None:
        handle = self._window.windowHandle()
        if handle is not None and handle is not self._connected_handle:
            self._connected_handle = handle
            handle.screenChanged.connect(self._on_screen_changed)
        current_screen = self._window.screen() if hasattr(self._window, "screen") else None
        if current_screen is not None and current_screen is not self._connected_screen:
            if self._connected_screen is not None:
                try:
                    self._connected_screen.logicalDotsPerInchChanged.disconnect(self._on_dpi_changed)
                except (RuntimeError, TypeError):
                    pass
            self._connected_screen = current_screen
            try:
                current_screen.logicalDotsPerInchChanged.connect(self._on_dpi_changed)
            except (RuntimeError, TypeError):
                pass

    def _on_screen_changed(self, _screen=None) -> None:
        self._bind_screen_signals()
        self.trigger(relayout=True, settle=True, slow_settle=True)

    def _on_dpi_changed(self, _dpi: float = 0.0) -> None:
        self.trigger(relayout=True, settle=True, slow_settle=True)

    def trigger(self, relayout: bool = False, settle: bool = False, slow_settle: bool = False) -> None:
        if self._refreshing:
            return
        if relayout:
            self._pending_relayout = True
        self._immediate_timer.start()
        if settle:
            self._settle_timer.start()
        if slow_settle:
            self._state_settle_timer.start()

    def _run_refresh(self, relayout: bool) -> None:
        if self._refreshing or not self._window.isVisible():
            return
        self._refreshing = True
        try:
            self._bind_screen_signals()
            L4d2ThemeManager.refresh_window_tree(self._window, relayout=relayout)
            self._last_size = self._window.size()
            self._last_dpr = float(self._window.devicePixelRatioF())
        finally:
            self._refreshing = False

    def _flush_refresh(self) -> None:
        relayout = self._pending_relayout
        self._pending_relayout = False
        self._run_refresh(relayout)

    def _flush_settled(self) -> None:
        self._pending_relayout = False
        self._run_refresh(True)

    def eventFilter(self, obj: QObject, event: QEvent) -> bool:
        if obj is self._window and not self._refreshing:
            etype = event.type()
            if etype == QEvent.Type.Close:
                self._immediate_timer.stop()
                self._settle_timer.stop()
                self._state_settle_timer.stop()
            elif etype == QEvent.Type.Show:
                self._bind_screen_signals()
                self.trigger(relayout=True, settle=True)
            elif etype == QEvent.Type.Resize:
                self.trigger(relayout=True, settle=True)
            elif etype == QEvent.Type.Move:
                screen = self._window.screen() if hasattr(self._window, "screen") else None
                dpr = float(self._window.devicePixelRatioF())
                if screen is not self._connected_screen or abs(dpr - self._last_dpr) > 0.001:
                    self._bind_screen_signals()
                    self.trigger(relayout=True, settle=True, slow_settle=True)
            elif etype in (QEvent.Type.WindowStateChange, QEvent.Type.WindowActivate):
                self.trigger(relayout=True, settle=True, slow_settle=(etype == QEvent.Type.WindowStateChange))
            elif self._screen_change_event is not None and etype == self._screen_change_event:
                self._bind_screen_signals()
                self.trigger(relayout=True, settle=True, slow_settle=True)
        return super().eventFilter(obj, event)


def lerp_color(c1: QColor, c2: QColor, t: float) -> QColor:
    """Linearly interpolate between two QColors for t in [0.0, 1.0]."""
    clamped = max(0.0, min(1.0, float(t)))
    return QColor(
        int(c1.red() + (c2.red() - c1.red()) * clamped),
        int(c1.green() + (c2.green() - c1.green()) * clamped),
        int(c1.blue() + (c2.blue() - c1.blue()) * clamped),
        int(c1.alpha() + (c2.alpha() - c1.alpha()) * clamped),
    )


class _SurfaceMotionController(QObject):
    """Animates smooth background hover and press transitions via QVariantAnimation."""

    def __init__(self, target: QWidget) -> None:
        super().__init__(target)
        self.setObjectName("l4d2SurfaceMotion")
        self._target = target
        self._hover_t: float = 0.0
        self._press_t: float = 0.0
        self._idle_bg = QColor("#181C24")
        self._hover_bg = QColor("#252116")
        self._press_bg = QColor("#302918")
        self._idle_border: Optional[QColor] = None
        self._hover_border: Optional[QColor] = None
        self._press_border: Optional[QColor] = None
        self._template = ""

        self._hover_anim = QVariantAnimation(self)
        self._hover_anim.setDuration(160)
        self._hover_anim.setEasingCurve(QEasingCurve.Type.OutCubic)
        self._hover_anim.valueChanged.connect(self._on_hover_value)

        self._press_anim = QVariantAnimation(self)
        self._press_anim.setDuration(90)
        self._press_anim.setEasingCurve(QEasingCurve.Type.OutCubic)
        self._press_anim.valueChanged.connect(self._on_press_value)

        target.setAttribute(Qt.WidgetAttribute.WA_Hover, True)
        target.installEventFilter(self)

    def configure(
        self,
        idle_bg: QColor,
        hover_bg: QColor,
        press_bg: QColor,
        style_template: str,
        border_colors: Optional[tuple[QColor, QColor, QColor]] = None,
    ) -> None:
        self._idle_bg = QColor(idle_bg)
        self._hover_bg = QColor(hover_bg)
        self._press_bg = QColor(press_bg)
        if border_colors is not None:
            self._idle_border = QColor(border_colors[0])
            self._hover_border = QColor(border_colors[1])
            self._press_border = QColor(border_colors[2])
        else:
            self._idle_border = None
            self._hover_border = None
            self._press_border = None
        self._template = style_template
        self._apply()

    def _on_hover_value(self, value: object) -> None:
        self._hover_t = float(value)
        self._apply()

    def _on_press_value(self, value: object) -> None:
        self._press_t = float(value)
        self._apply()

    def _apply(self) -> None:
        if not self._template:
            return
        qss = self._template
        if "{bg}" in qss:
            base = lerp_color(self._idle_bg, self._hover_bg, self._hover_t)
            current = lerp_color(base, self._press_bg, self._press_t)
            rgba = f"rgba({current.red()}, {current.green()}, {current.blue()}, {current.alpha()})"
            qss = qss.replace("{bg}", rgba)
        if (
            "{border}" in qss
            and self._idle_border is not None
            and self._hover_border is not None
            and self._press_border is not None
        ):
            b_base = lerp_color(self._idle_border, self._hover_border, self._hover_t)
            b_curr = lerp_color(b_base, self._press_border, self._press_t)
            b_rgba = f"rgba({b_curr.red()}, {b_curr.green()}, {b_curr.blue()}, {b_curr.alpha()})"
            qss = qss.replace("{border}", b_rgba)
        self._target.setStyleSheet(qss)

    def _animate_hover(self, end_val: float) -> None:
        self._hover_anim.stop()
        self._hover_anim.setStartValue(self._hover_t)
        self._hover_anim.setEndValue(end_val)
        self._hover_anim.start()

    def _animate_press(self, end_val: float) -> None:
        self._press_anim.stop()
        self._press_anim.setStartValue(self._press_t)
        self._press_anim.setEndValue(end_val)
        self._press_anim.start()

    def eventFilter(self, obj: QObject, event: QEvent) -> bool:
        if obj is self._target:
            etype = event.type()
            if etype == QEvent.Type.Enter:
                if self._target.isEnabled():
                    self._animate_hover(1.0)
            elif etype in (QEvent.Type.Leave, QEvent.Type.Hide):
                self._animate_hover(0.0)
                if self._press_t > 0.0:
                    self._animate_press(0.0)
            elif etype == QEvent.Type.MouseButtonPress and getattr(event, "button", lambda: None)() == Qt.MouseButton.LeftButton:
                if self._target.isEnabled():
                    self._animate_press(1.0)
            elif etype == QEvent.Type.MouseButtonRelease:
                self._animate_press(0.0)
            elif etype == QEvent.Type.EnabledChange and not self._target.isEnabled():
                self._hover_anim.stop()
                self._press_anim.stop()
                self._hover_t = 0.0
                self._press_t = 0.0
                self._apply()
        return super().eventFilter(obj, event)


class _OpticalIconEngine(QIconEngine):
    """Renders a FluentIcon scaled and optically centered relative to button label text."""

    def __init__(
        self,
        base_icon: FluentIconBase,
        theme: Theme = Theme.AUTO,
        color: Optional[QColor] = None,
        glyph_size: float = 12.0,
        x_offset: float = 0.0,
        y_offset: float = 1.0,
    ) -> None:
        super().__init__()
        self._base_icon = base_icon
        self._theme = theme
        self._color = color
        self._glyph_size = glyph_size
        self._x_offset = x_offset
        self._y_offset = y_offset

    def _resolve_theme(self) -> Theme:
        if self._theme != Theme.AUTO:
            return self._theme
        return Theme.DARK if isDarkTheme() else Theme.LIGHT

    def actualSize(self, size: QSize, mode: QIcon.Mode, state: QIcon.State) -> QSize:
        return size

    def clone(self) -> QIconEngine:
        return _OpticalIconEngine(
            self._base_icon,
            theme=self._theme,
            color=self._color,
            glyph_size=self._glyph_size,
            x_offset=self._x_offset,
            y_offset=self._y_offset,
        )

    def paint(
        self,
        painter: QPainter,
        rect: QRect,
        mode: QIcon.Mode,
        state: QIcon.State,
    ) -> None:
        painter.save()
        painter.setRenderHints(
            QPainter.RenderHint.Antialiasing | QPainter.RenderHint.SmoothPixmapTransform
        )
        if mode == QIcon.Mode.Disabled:
            painter.setOpacity(0.42)
        gx = rect.x() + (rect.width() - self._glyph_size) / 2.0 + self._x_offset
        gy = rect.y() + (rect.height() - self._glyph_size) / 2.0 + self._y_offset
        target = QRectF(gx, gy, self._glyph_size, self._glyph_size)
        theme = self._resolve_theme()
        if self._color is not None:
            colored = self._base_icon.icon(theme, color=self._color)
            colored.paint(painter, target.toRect(), Qt.AlignmentFlag.AlignCenter, state)
        else:
            self._base_icon.render(painter, target, theme=theme)
        painter.restore()

    def pixmap(self, size: QSize, mode: QIcon.Mode, state: QIcon.State) -> QPixmap:
        return self.scaledPixmap(size, mode, state, 1.0)

    def scaledPixmap(self, size: QSize, mode: QIcon.Mode, state: QIcon.State, scale: float) -> QPixmap:
        ratio = max(1.0, float(scale))
        pm = QPixmap(max(1, round(size.width() * ratio)), max(1, round(size.height() * ratio)))
        pm.setDevicePixelRatio(ratio)
        pm.fill(Qt.GlobalColor.transparent)
        painter = QPainter(pm)
        self.paint(painter, QRect(0, 0, size.width(), size.height()), mode, state)
        painter.end()
        return pm


class _OpticalButtonIcon(FluentIconBase):
    """Decorator keeping FluentIcons proportional and vertically balanced inside text buttons."""

    def __init__(
        self,
        base_icon: FluentIconBase,
        glyph_size: float = 12.0,
        x_offset: float = 0.0,
        y_offset: float = 1.0,
    ) -> None:
        self.base_icon = base_icon
        self.glyph_size = glyph_size
        self.x_offset = x_offset
        self.y_offset = y_offset

    def path(self, theme: Theme = Theme.AUTO) -> str:
        return self.base_icon.path(theme)

    def icon(self, theme: Theme = Theme.AUTO, color: Optional[QColor] = None) -> QIcon:
        resolved_color = QColor(color) if color is not None else None
        return QIcon(
            _OpticalIconEngine(
                self.base_icon,
                theme=theme,
                color=resolved_color,
                glyph_size=self.glyph_size,
                x_offset=self.x_offset,
                y_offset=self.y_offset,
            )
        )

    def render(self, painter, rect, theme: Theme = Theme.AUTO, indexes=None, **attributes) -> None:
        gx = rect.x() + (rect.width() - self.glyph_size) / 2.0 + self.x_offset
        gy = rect.y() + (rect.height() - self.glyph_size) / 2.0 + self.y_offset
        target = QRectF(gx, gy, self.glyph_size, self.glyph_size)
        self.base_icon.render(painter, target, theme=theme, indexes=indexes, **attributes)


class L4d2ThemeManager:
    """Detects PC system theme and applies cohesive Left 4 Dead 2 styling across Fluent widgets."""

    THEME_SYSTEM = "System"
    THEME_DARK = "Dark"
    THEME_LIGHT = "Light"

    _LIGHT_STACK_QSS = """
        StackedWidget {
            background-color: #DCD6C8;
            border: 1px solid #9F9788;
            border-right: none;
            border-bottom: none;
            border-top-left-radius: 10px;
        }
        CardWidget, HeaderCardWidget {
            background-color: #FCFBF8;
            border: 1px solid #A8A090;
            border-radius: 8px;
        }
        CardWidget:hover, HeaderCardWidget:hover {
            background-color: #F2EEE4;
            border: 1px solid #A8A090;
        }
        HeaderCardWidget > QWidget#headerView {
            background-color: #EAE4D7;
            border: 1px solid #9F9788;
            border-top-left-radius: 7px;
            border-top-right-radius: 7px;
        }
        HeaderCardWidget > QWidget#view {
            background-color: #FCFBF8;
            border: 1px solid #9F9788;
            border-top: none;
            border-bottom-left-radius: 7px;
            border-bottom-right-radius: 7px;
        }
        HeaderCardWidget QLabel#headerLabel {
            color: #111315;
            font-weight: 700;
        }
        BodyLabel, StrongBodyLabel, SubtitleLabel, TitleLabel {
            color: #111315;
        }
        CaptionLabel {
            color: #383E48;
        }
        LineEdit, TextEdit, PlainTextEdit, ComboBox {
            background-color: #FFFFFF;
            color: #111315;
            border: 1px solid #9F9788;
            border-bottom: 2px solid #787164;
            border-radius: 5px;
        }
        LineEdit:hover, TextEdit:hover, PlainTextEdit:hover, ComboBox:hover {
            background-color: #FFFFFF;
            border: 1px solid #C98E00;
            border-bottom: 2px solid #C98E00;
        }
        LineEdit:focus, TextEdit:focus, PlainTextEdit:focus {
            background-color: #FFFFFF;
            border: 1px solid #C98E00;
            border-bottom: 2px solid #C98E00;
        }
        PushButton {
            background-color: #F4F1EA;
            color: #111315;
            border: 1px solid #9F9788;
            border-bottom: 2px solid #787164;
            border-radius: 5px;
        }
        PushButton:hover {
            background-color: #EAE3D0;
            border: 1px solid #C98E00;
            border-bottom: 2px solid #9E7000;
        }
        PushButton:pressed {
            background-color: #DFD6BE;
        }
        PushButton:disabled {
            background-color: #E7E3D9;
            color: #767065;
            border: 1px solid #BFB8AA;
        }
        PrimaryPushButton {
            background-color: #D92B2B;
            color: #FFFFFF;
            border: 1px solid #991B1B;
            border-bottom: 2px solid #7A1414;
            border-radius: 5px;
        }
        PrimaryPushButton:hover {
            background-color: #E53E3E;
            border: 1px solid #991B1B;
        }
        PrimaryPushButton:pressed {
            background-color: #991B1B;
        }
        PrimaryPushButton:disabled {
            background-color: #D99B9B;
            color: #FAF6F6;
            border: 1px solid #B57A7A;
        }
    """

    @staticmethod
    def detect_system_theme() -> str:
        """Detect Windows or Qt dark/light preference ('Dark' or 'Light')."""
        if winreg is not None:
            try:
                key_path = r"Software\Microsoft\Windows\CurrentVersion\Themes\Personalize"
                with winreg.OpenKey(winreg.HKEY_CURRENT_USER, key_path) as key:
                    value, _ = winreg.QueryValueEx(key, "AppsUseLightTheme")
                    return L4d2ThemeManager.THEME_LIGHT if int(value) == 1 else L4d2ThemeManager.THEME_DARK
            except OSError:
                pass

        app = QGuiApplication.instance()
        if app is not None:
            scheme = QGuiApplication.styleHints().colorScheme()
            if scheme == Qt.ColorScheme.Light:
                return L4d2ThemeManager.THEME_LIGHT
            if scheme == Qt.ColorScheme.Dark:
                return L4d2ThemeManager.THEME_DARK

        return L4d2ThemeManager.THEME_DARK

    @classmethod
    def resolve_theme(cls, preference: str) -> str:
        """Resolve 'System'/'Auto'/'Dark'/'Light' to concrete 'Dark' or 'Light'."""
        cleaned = (preference or cls.THEME_SYSTEM).strip().lower()
        if cleaned == "light":
            return cls.THEME_LIGHT
        if cleaned == "dark":
            return cls.THEME_DARK
        return cls.detect_system_theme()

    @classmethod
    def apply_window_theme(cls, window: Optional[FluentWindow], preference: str) -> bool:
        """Apply resolved Fluent theme, L4D2 crimson/amber accents, and custom window canvas."""
        resolved = cls.resolve_theme(preference)
        is_dark = resolved == cls.THEME_DARK

        target_theme = Theme.DARK if is_dark else Theme.LIGHT
        for _ in range(3):
            try:
                setTheme(target_theme, lazy=False)
                break
            except RuntimeError:
                continue
        setThemeColor(QColor(COLORS.red), lazy=False)

        if window is not None:
            if hasattr(window, "setMicaEffectEnabled"):
                window.setMicaEffectEnabled(False)
            bg = QColor(COLORS.dark_window if is_dark else COLORS.light_window)
            window.setCustomBackgroundColor(
                QColor(COLORS.light_window),
                QColor(COLORS.dark_window),
            )
            window.backgroundColorAni.stop()
            window.setBackgroundColor(bg)
            cls._apply_titlebar_theme(window, is_dark)
            stacked = getattr(window, "stackedWidget", None)
            if stacked is not None:
                stacked.setStyleSheet("" if is_dark else cls._LIGHT_STACK_QSS)
            for card in window.findChildren(QWidget):
                if hasattr(card, "_normalBackgroundColor") and hasattr(card, "setBackgroundColor"):
                    card.setBackgroundColor(card._normalBackgroundColor())
            cls.apply_label_colors(window)
            cls.apply_pointing_hand_cursors(window)
            cls.enable_card_hover(window)
            cls.refresh_window_tree(window, relayout=False)

        return is_dark

    @staticmethod
    def install_window_repaint_guard(window: Optional[QWidget]) -> Optional[_WindowRepaintFilter]:
        """Attach automatic layout/backing-store repaint sync on resize and monitor changes."""
        if window is None:
            return None
        existing = window.findChild(
            _WindowRepaintFilter,
            "l4d2WindowRepaintFilter",
            Qt.FindChildOption.FindDirectChildrenOnly,
        )
        if existing is not None:
            return existing
        return _WindowRepaintFilter(window)

    @staticmethod
    def sync_title_bar_bounds(window: Optional[QWidget]) -> None:
        """Keep FluentWindow title bar aligned after nav offset so min/max/close stay inside bounds."""
        if window is None:
            return
        title_bar = getattr(window, "titleBar", None)
        if title_bar is None:
            return
        expected_w = max(0, window.width() - title_bar.x())
        if title_bar.width() != expected_w:
            title_bar.resize(expected_w, title_bar.height())
        title_bar.raise_()
        QWidget.update(title_bar)

    @staticmethod
    def refresh_window_tree(window: Optional[QWidget], relayout: bool = False) -> None:
        """Invalidate dynamic layouts and mark the active subtree dirty to avoid stale paint regions."""
        if window is None:
            return
        L4d2ThemeManager.sync_title_bar_bounds(window)
        nav = getattr(window, "navigationInterface", None)
        if nav is not None:
            QWidget.update(nav)

        stacked = getattr(window, "stackedWidget", None)
        current = (
            stacked.currentWidget()
            if stacked is not None and hasattr(stacked, "currentWidget")
            else window
        )
        if stacked is not None and current is not None and current is not window:
            stacked_view = getattr(stacked, "view", None)
            ani = getattr(stacked_view, "_ani", None)
            if ani is None or ani.state() == 0:
                if current.pos() != QPoint(0, 0):
                    current.move(0, 0)

        active_root = current or window
        if relayout:
            for overlay in (
                active_root.findChildren(_CardHoverOverlay, "l4d2CardHoverOverlay")
                + active_root.findChildren(_InputFocusOverlay, "l4d2InputFocusOverlay")
            ):
                parent = overlay.parentWidget()
                if parent is not None:
                    overlay.setGeometry(parent.rect())
            for child in active_root.findChildren(QWidget):
                if not child.isVisible():
                    continue
                if hasattr(child, "sync_height") and callable(child.sync_height):
                    child.sync_height(child.width())
                elif hasattr(child, "_sync_flow_height") and callable(child._sync_flow_height):
                    child._sync_flow_height()
                elif hasattr(child, "_sync_card_height") and callable(child._sync_card_height):
                    child._sync_card_height()
            if isinstance(active_root, QAbstractScrollArea):
                inner = active_root.widget()
                if inner is not None and inner.layout() is not None:
                    inner.layout().invalidate()
                inner_vp = active_root.viewport()
                if inner_vp is not None:
                    inner_vp.updateGeometry()
            elif active_root.layout() is not None:
                active_root.layout().invalidate()
            active_root.updateGeometry()

        QWidget.update(window)
        if stacked is not None:
            QWidget.update(stacked)
        if isinstance(active_root, QAbstractScrollArea):
            vp = active_root.viewport()
            if vp is not None:
                QWidget.update(vp)
            inner = active_root.widget()
            if inner is not None:
                QWidget.update(inner)
        QWidget.update(active_root)
        for child in active_root.findChildren(QWidget):
            if child.isVisible():
                QWidget.update(child)

    @staticmethod
    def _apply_titlebar_theme(window: FluentWindow, is_dark: bool) -> None:
        title_bar = getattr(window, "titleBar", None)
        if title_bar is None:
            return

        FluentStyleSheet.FLUENT_WINDOW.apply(
            title_bar,
            theme=Theme.DARK if is_dark else Theme.LIGHT,
        )
        fg_hex = COLORS.dark_text if is_dark else COLORS.light_text
        fg = QColor(fg_hex)
        hover_bg = QColor(255, 255, 255, 28) if is_dark else QColor(0, 0, 0, 22)
        pressed_bg = QColor(255, 255, 255, 48) if is_dark else QColor(0, 0, 0, 42)
        hover_css = "rgba(255, 255, 255, 28)" if is_dark else "rgba(0, 0, 0, 22)"
        pressed_css = "rgba(255, 255, 255, 48)" if is_dark else "rgba(0, 0, 0, 42)"

        for btn_name, selector in (("minBtn", "MinimizeButton"), ("maxBtn", "MaximizeButton")):
            btn = getattr(title_bar, btn_name, None)
            if btn is not None:
                btn.setStyleSheet(
                    f"{selector} {{"
                    f"  qproperty-normalColor: {fg_hex};"
                    f"  qproperty-hoverColor: {fg_hex};"
                    f"  qproperty-pressedColor: {fg_hex};"
                    f"  qproperty-normalBackgroundColor: transparent;"
                    f"  qproperty-hoverBackgroundColor: {hover_css};"
                    f"  qproperty-pressedBackgroundColor: {pressed_css};"
                    f"}}"
                )
                btn.setNormalColor(fg)
                btn.setHoverColor(fg)
                btn.setPressedColor(fg)
                btn.setHoverBackgroundColor(hover_bg)
                btn.setPressedBackgroundColor(pressed_bg)

        close_btn = getattr(title_bar, "closeBtn", None)
        if close_btn is not None:
            close_btn.setStyleSheet(
                f"CloseButton {{"
                f"  qproperty-normalColor: {fg_hex};"
                f"  qproperty-hoverColor: #FFFFFF;"
                f"  qproperty-pressedColor: #FFFFFF;"
                f"  qproperty-normalBackgroundColor: transparent;"
                f"  qproperty-hoverBackgroundColor: {COLORS.red};"
                f"  qproperty-pressedBackgroundColor: {COLORS.red_dark};"
                f"}}"
            )
            close_btn.setNormalColor(fg)
            close_btn.setHoverColor(QColor("#FFFFFF"))
            close_btn.setPressedColor(QColor("#FFFFFF"))
            close_btn.setHoverBackgroundColor(QColor(COLORS.red))
            close_btn.setPressedBackgroundColor(QColor(COLORS.red_dark))

        title_lbl = getattr(title_bar, "titleLabel", None)
        if title_lbl is not None:
            title_lbl.setStyleSheet(
                f"QLabel#titleLabel {{ color: {fg_hex}; "
                f"background: transparent; font-weight: 600; padding: 0 6px; }}"
            )

    @staticmethod
    def surface_palette(is_dark: bool, tone: str = "neutral") -> tuple[QColor, QColor, QColor]:
        """Return (idle, hover, press) theme-matched background QColors matching table row highlights."""
        if tone == "card":
            if is_dark:
                return QColor("#161A21"), QColor("#20252F"), QColor("#272D39")
            return QColor("#FCFBF8"), QColor("#F2EFE7"), QColor("#E8E3D8")
        if tone == "amber":
            if is_dark:
                return QColor("#201C12"), QColor("#2A251B"), QColor("#332D20")
            return QColor("#FDECA8"), QColor("#F4DF90"), QColor("#E9D17A")
        if tone == "version":
            if is_dark:
                return QColor("#1F242D"), QColor("#29303D"), QColor("#333B4B")
            return QColor("#E7E1D3"), QColor("#DCD5C4"), QColor("#D1C8B5")
        if tone == "badge":
            if is_dark:
                return QColor("#252B36"), QColor("#2F3745"), QColor("#384152")
            return QColor("#E6E0D2"), QColor("#DBD4C3"), QColor("#CFC7B4")
        if is_dark:
            return QColor("#181C24"), QColor("#222731"), QColor("#2A303C")
        return QColor("#EAE5D9"), QColor("#DFD9CA"), QColor("#D4CEBD")

    @staticmethod
    def image_surface_palette(is_dark: bool) -> tuple[QColor, QColor, QColor]:
        """Return (idle, hover, press) background colors for preview image frames."""
        idle = QColor(COLORS.dark_window if is_dark else "#D8D2C5")
        if is_dark:
            hover = lerp_color(idle, QColor("#FFFFFF"), 0.04)
            press = lerp_color(idle, QColor("#FFFFFF"), 0.08)
        else:
            hover = lerp_color(idle, QColor("#FFFFFF"), 0.14)
            press = lerp_color(idle, QColor("#000000"), 0.06)
        return idle, hover, press

    @staticmethod
    def image_border_colors(is_dark: bool) -> tuple[QColor, QColor, QColor]:
        """Return (idle, hover, press) amber outline colors matching Meus Mods thumbnails."""
        idle = QColor(COLORS.dark_border if is_dark else COLORS.light_border)
        hover = QColor(COLORS.amber)
        press = QColor(COLORS.amber_bright if is_dark else COLORS.amber_deep)
        return idle, hover, press

    @staticmethod
    def install_surface_motion(
        widget: QWidget,
        style_template: str,
        tone: str = "neutral",
        custom_colors: Optional[tuple[QColor, QColor, QColor]] = None,
        border_colors: Optional[tuple[QColor, QColor, QColor]] = None,
    ) -> _SurfaceMotionController:
        """Attach or update smooth hover and press animations on widget."""
        ctrl = widget.findChild(
            _SurfaceMotionController,
            "l4d2SurfaceMotion",
            Qt.FindChildOption.FindDirectChildrenOnly,
        )
        if ctrl is None:
            ctrl = _SurfaceMotionController(widget)
        if custom_colors is not None:
            idle_bg, hover_bg, press_bg = custom_colors
        else:
            idle_bg, hover_bg, press_bg = L4d2ThemeManager.surface_palette(isDarkTheme(), tone)
        ctrl.configure(idle_bg, hover_bg, press_bg, style_template, border_colors=border_colors)
        return ctrl

    @staticmethod
    def apply_label_colors(root: QWidget) -> None:
        """Apply L4D2 version pill and step pill styling reliably across standard QLabels."""
        is_dark = isDarkTheme()

        version_qss = (
            f"QLabel#heroVersionPill {{"
            f"  background-color: {{bg}};"
            f"  color: {COLORS.amber if is_dark else '#111315'};"
            f"  border: 1px solid {COLORS.amber if is_dark else '#9E7000'};"
            f"  border-radius: 4px;"
            f"  padding: 2px 8px;"
            f"  font-size: 11px;"
            f"  font-weight: 700;"
            f"}}"
        )
        for pill in root.findChildren(QWidget, "heroVersionPill"):
            pill.setAttribute(Qt.WidgetAttribute.WA_StyledBackground, True)
            L4d2ThemeManager.install_surface_motion(pill, version_qss, tone="version")

        step_qss = (
            f"QLabel#heroStepPill {{"
            f"  background-color: {{bg}};"
            f"  color: {COLORS.amber_bright if is_dark else '#111315'};"
            f"  border: 1px solid {COLORS.amber if is_dark else '#A87600'};"
            f"  border-radius: 4px;"
            f"  padding: 3px 9px;"
            f"  font-size: 12px;"
            f"  font-weight: 600;"
            f"}}"
        )
        for pill in root.findChildren(QWidget, "heroStepPill"):
            pill.setAttribute(Qt.WidgetAttribute.WA_StyledBackground, True)
            L4d2ThemeManager.install_surface_motion(pill, step_qss, tone="amber")

        crew_qss = (
            f"QLabel#crewSectionBadge {{"
            f"  color: {COLORS.amber if is_dark else COLORS.red_dark};"
            f"  font-size: 12px;"
            f"  font-weight: 700;"
            f"  letter-spacing: 0.6px;"
            f"  border: none;"
            f"  background: transparent;"
            f"}}"
        )
        for badge in root.findChildren(QWidget, "crewSectionBadge"):
            badge.setStyleSheet(crew_qss)

        l4d1_crew_qss = (
            f"QLabel#crewL4d1Badge {{"
            f"  color: {'#4ADE80' if is_dark else '#15803D'};"
            f"  font-size: 12px;"
            f"  font-weight: 700;"
            f"  letter-spacing: 0.6px;"
            f"  border: none;"
            f"  background: transparent;"
            f"}}"
        )
        for badge in root.findChildren(QWidget, "crewL4d1Badge"):
            badge.setStyleSheet(l4d1_crew_qss)

        L4d2ThemeManager.enable_card_hover(root)
        L4d2ThemeManager.enable_input_focus_animation(root)

    _TEXT_INPUT_DARK_FOCUS_QSS = (
        '\nTextEdit[l4d2FocusManaged="true"]:focus, '
        'PlainTextEdit[l4d2FocusManaged="true"]:focus '
        "{ border-bottom: 1px solid rgba(255, 255, 255, 0.22); }\n"
    )
    _TEXT_INPUT_LIGHT_FOCUS_QSS = (
        '\nTextEdit[l4d2FocusManaged="true"]:focus, '
        'PlainTextEdit[l4d2FocusManaged="true"]:focus '
        "{ background-color: #FFFFFF; border: 1px solid #C98E00; border-bottom: 2px solid #C98E00; }\n"
    )

    @classmethod
    def _get_cached_filter(cls, attr_name: str, filter_cls: type[QObject]):
        app = QGuiApplication.instance()
        filt = getattr(cls, attr_name, None)
        if filt is not None:
            try:
                filt.objectName()
                return filt
            except RuntimeError:
                filt = None
        filt = filter_cls(app)
        setattr(cls, attr_name, filt)
        return filt

    @classmethod
    def _get_cursor_filter(cls) -> _CursorSyncFilter:
        return cls._get_cached_filter("_cursor_filter", _CursorSyncFilter)

    @classmethod
    def _get_hover_filter(cls) -> _CardHoverFilter:
        return cls._get_cached_filter("_hover_filter", _CardHoverFilter)

    @classmethod
    def _get_input_focus_filter(cls) -> _InputFocusFilter:
        return cls._get_cached_filter("_input_focus_filter", _InputFocusFilter)

    @classmethod
    def enable_input_focus_animation(cls, root: QWidget) -> None:
        """Install animated center-out crimson focus underlines on editable LineEdit/TextEdit inputs."""
        if root is None:
            return
        focus_filter = cls._get_input_focus_filter()
        is_dark = isDarkTheme()
        candidates: list[QWidget] = []
        if isinstance(root, (LineEdit, TextEdit, PlainTextEdit)):
            candidates.append(root)
        seen: set[int] = set()
        for widget in list(candidates) + list(root.findChildren(QWidget)):
            if not isinstance(widget, (LineEdit, TextEdit, PlainTextEdit)):
                continue
            key = id(widget)
            if key in seen:
                continue
            seen.add(key)
            if isinstance(widget, LineEdit):
                widget.setCustomFocusedBorderColor(QColor(0, 0, 0, 0), QColor(0, 0, 0, 0))
            else:
                layer = getattr(widget, "layer", None)
                if layer is not None:
                    widget.removeEventFilter(layer)
                    layer.setAttribute(Qt.WidgetAttribute.WA_DontShowOnScreen, True)
                    layer.hide()
                if not widget.isReadOnly():
                    widget.setProperty("l4d2FocusManaged", True)
                    suffix = (
                        cls._TEXT_INPUT_DARK_FOCUS_QSS
                        if is_dark
                        else cls._TEXT_INPUT_LIGHT_FOCUS_QSS
                    )
                    qss = (
                        widget.styleSheet()
                        .replace(cls._TEXT_INPUT_DARK_FOCUS_QSS, "")
                        .replace(cls._TEXT_INPUT_LIGHT_FOCUS_QSS, "")
                    )
                    widget.setStyleSheet(f"{qss}{suffix}")
            if widget.isReadOnly():
                continue
            overlay = widget.findChild(
                _InputFocusOverlay,
                "l4d2InputFocusOverlay",
                Qt.FindChildOption.FindDirectChildrenOnly,
            )
            created = overlay is None
            if overlay is None:
                overlay = _InputFocusOverlay(widget)
                overlay.setGeometry(widget.rect())
            if not widget.property("_l4d2_input_focus_hooked"):
                widget.setProperty("_l4d2_input_focus_hooked", True)
                widget.installEventFilter(focus_filter)
            if created and widget.hasFocus():
                overlay.set_focused(True, immediate=True)

    @classmethod
    def enable_card_hover(cls, root: QWidget) -> None:
        """Install translucent amber hover border overlays on CardWidget/HeaderCardWidget instances."""
        if root is None:
            return
        hover_filter = cls._get_hover_filter()
        candidates: list[QWidget] = []
        if isinstance(root, (CardWidget, SimpleCardWidget)):
            candidates.append(root)
        seen: set[int] = set()
        for card in list(candidates) + list(root.findChildren(CardWidget)):
            key = id(card)
            if key in seen:
                continue
            seen.add(key)
            if card.objectName() in {"l4d2HeroCard", "dropZoneCard"}:
                continue
            card.setAttribute(Qt.WidgetAttribute.WA_Hover, True)
            overlay = card.findChild(
                _CardHoverOverlay,
                "l4d2CardHoverOverlay",
                Qt.FindChildOption.FindDirectChildrenOnly,
            )
            if overlay is None:
                overlay = _CardHoverOverlay(card)
                overlay.setGeometry(card.rect())
            if not card.property("_l4d2_card_hover_hooked"):
                card.setProperty("_l4d2_card_hover_hooked", True)
                card.installEventFilter(hover_filter)

    @classmethod
    def style_dialog_yes_button(
        cls,
        button: QAbstractButton,
        text: str,
        fluent_icon: FluentIconBase = FluentIcon.ACCEPT,
    ) -> None:
        """Apply proportional optical icon sizing and label text to dialog confirm buttons."""
        button.setText(text)
        button.setCursor(Qt.CursorShape.PointingHandCursor)
        button.setIconSize(QSize(14, 15))
        button.setIcon(
            _OpticalButtonIcon(
                fluent_icon,
                glyph_size=12.0,
                x_offset=0.0,
                y_offset=1.0,
            )
        )

    @classmethod
    def style_dialog_cancel_button(
        cls,
        button: QAbstractButton,
        text: str,
        fluent_icon: FluentIconBase = FluentIcon.CLOSE,
    ) -> None:
        """Apply proportional icon sizing, breathing space, and label text to dialog cancel buttons."""
        button.setText(text)
        button.setCursor(Qt.CursorShape.PointingHandCursor)
        button.setIconSize(QSize(17, 15))
        button.setIcon(
            _OpticalButtonIcon(
                fluent_icon,
                glyph_size=11.0,
                x_offset=-2.0,
                y_offset=1.5,
            ).icon(Theme.AUTO)
        )

    @classmethod
    def apply_pointing_hand_cursors(cls, root: QWidget) -> None:
        """Ensure clickable buttons, switches, combos, and nav items stay synced with PointingHandCursor."""
        cursor_filter = cls._get_cursor_filter()
        for widget in root.findChildren(QWidget):
            if isinstance(widget, (QAbstractButton, SwitchButton, ComboBox)):
                cursor = Qt.CursorShape.PointingHandCursor if widget.isEnabled() else Qt.CursorShape.ArrowCursor
                widget.setCursor(cursor)
                if not widget.property("_l4d2_cursor_hooked"):
                    widget.setProperty("_l4d2_cursor_hooked", True)
                    widget.installEventFilter(cursor_filter)
            elif "Navigation" in type(widget).__name__:
                widget.setCursor(Qt.CursorShape.PointingHandCursor)
        cls.enable_input_focus_animation(root)

    @staticmethod
    def style_step_pill(label: QWidget) -> None:
        """Register workflow step pill objectName and apply theme-matched styling."""
        label.setObjectName("heroStepPill")
        L4d2ThemeManager.apply_label_colors(label.parentWidget() or label)
