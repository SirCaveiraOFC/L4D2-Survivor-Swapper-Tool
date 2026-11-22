from __future__ import annotations

from dataclasses import dataclass
from html import escape
from typing import Optional

from PySide6.QtCore import Qt
from PySide6.QtGui import QColor, QKeyEvent, QPainter, QPixmap
from PySide6.QtWidgets import (
    QFrame,
    QGridLayout,
    QHBoxLayout,
    QLabel,
    QVBoxLayout,
    QWidget,
)
from qfluentwidgets import (
    CaptionLabel,
    CardWidget,
    FluentIcon,
    MessageBoxBase,
    PushButton,
    StrongBodyLabel,
    SubtitleLabel,
    isDarkTheme,
)

from core.i18n import LocalizationManager
from core.models import SurvivorId
from core.survivors import SurvivorRegistry
from ui.addon_ui_shared import create_icon_row
from ui.theme import COLORS, L4d2ThemeManager
from ui.widgets import draw_person_glyph, survivor_gender


@dataclass(frozen=True)
class ConversionConfirmEntry:
    """Summary snapshot describing a single queued or individual survivor conversion."""

    title: str
    source_filename: str
    author: str
    version: str
    origin: SurvivorId
    destinations: list[SurvivorId]
    output_files: list[str]
    output_dir: str
    cover_bytes: Optional[bytes] = None
    include_arms: bool = True
    include_vgui: bool = True
    include_weapons: Optional[bool] = None
    sanitize_origin: bool = True
    install_to_addons: bool = False


class _PersonGlyphBadge(QWidget):
    """Paints the shared vector male or female silhouette glyph beside survivor labels."""

    def __init__(
        self,
        female: bool,
        color: QColor,
        size: int = 14,
        parent: Optional[QWidget] = None,
    ) -> None:
        super().__init__(parent)
        self._female = female
        self._color = QColor(color)
        self._size = size
        self.setFixedSize(size, size)

    def paintEvent(self, event) -> None:
        painter = QPainter(self)
        painter.setRenderHint(QPainter.RenderHint.Antialiasing)
        draw_person_glyph(painter, 0.0, 0.0, float(self._size), self._color, female=self._female)


class _SurvivorRoutePill(QFrame):
    """Rounded pill pairing the character's male/female icon with their display name."""

    def __init__(
        self,
        survivor_id: SurvivorId,
        label_text: str,
        bg: str,
        border: str,
        fg: str,
        parent: Optional[QWidget] = None,
    ) -> None:
        super().__init__(parent)
        self.setObjectName("confirmRoutePill")
        tone = "amber" if bg.lower() in {"#201c12", "#fdeca8"} else "neutral"
        L4d2ThemeManager.install_surface_motion(
            self,
            f"QFrame#confirmRoutePill {{"
            f"  background-color: {{bg}};"
            f"  border: 1px solid {border};"
            f"  border-radius: 5px;"
            f"}}",
            tone=tone,
        )
        row = QHBoxLayout(self)
        row.setContentsMargins(9, 4, 10, 4)
        row.setSpacing(5)

        glyph = _PersonGlyphBadge(
            female=(survivor_gender(survivor_id) == "female"),
            color=QColor(fg),
            size=14,
            parent=self,
        )
        lbl = QLabel(label_text, self)
        lbl.setStyleSheet(
            f"QLabel {{ color: {fg}; font-size: 12px; font-weight: 700; border: none; background: transparent; }}"
        )
        row.addWidget(glyph, 0, Qt.AlignmentFlag.AlignVCenter)
        row.addWidget(lbl, 0, Qt.AlignmentFlag.AlignVCenter)


def _clear_layout_widgets(layout) -> None:
    while layout.count():
        item = layout.takeAt(0)
        widget = item.widget()
        if widget is not None:
            widget.hide()
            widget.setParent(None)
            widget.deleteLater()
        elif item.layout() is not None:
            _clear_layout_widgets(item.layout())


class ConversionConfirmDialog(MessageBoxBase):
    """Pre-conversion confirmation modal displaying summary cards and multi-item navigation."""

    def __init__(
        self,
        entries: list[ConversionConfirmEntry],
        i18n: Optional[LocalizationManager] = None,
        parent: Optional[QWidget] = None,
    ) -> None:
        super().__init__(parent)
        self._entries = list(entries)
        self._i18n = i18n or LocalizationManager("en-US")
        self._index = 0
        self.widget.setMinimumWidth(660)

        is_dark = isDarkTheme()
        text_fg = COLORS.dark_text if is_dark else COLORS.light_text
        muted_fg = COLORS.dark_muted if is_dark else COLORS.light_muted
        border_fg = COLORS.dark_border if is_dark else COLORS.light_border
        card_bg = COLORS.dark_card if is_dark else COLORS.light_card
        alt_bg = COLORS.dark_card_alt if is_dark else COLORS.light_card_alt
        amber_border = COLORS.amber if is_dark else "#9E7000"
        amber_fg = COLORS.amber_bright if is_dark else "#111315"
        totals_bg = "#201C12" if is_dark else "#FDECA8"

        total_vpks = sum(len(e.output_files) for e in self._entries)
        multi_jobs = len(self._entries) > 1

        title_row = QHBoxLayout()
        title_row.setContentsMargins(0, 0, 0, 0)
        title_row.setSpacing(10)
        self.title_label = SubtitleLabel(self._i18n.tr("confirm_dlg_title"), self.widget)
        title_row.addLayout(
            create_icon_row(FluentIcon.INFO, self.title_label, self.widget, size=20, spacing=10),
            1,
        )

        jobs_txt = self._i18n.tr_plural("confirm_dlg_jobs", len(self._entries))
        vpks_txt = self._i18n.tr_plural("confirm_dlg_vpks", total_vpks)
        totals_text = f"{jobs_txt} · {vpks_txt}" if multi_jobs else vpks_txt
        self.totals_pill = QLabel(totals_text, self.widget)
        self.totals_pill.setAlignment(Qt.AlignmentFlag.AlignCenter)
        self.totals_pill.setStyleSheet(
            f"QLabel {{"
            f"  background-color: {totals_bg};"
            f"  border: 1px solid {amber_border};"
            f"  color: {amber_fg};"
            f"  border-radius: 5px;"
            f"  padding: 3px 10px;"
            f"  font-size: 12px;"
            f"  font-weight: 700;"
            f"}}"
        )
        title_row.addWidget(self.totals_pill)
        self.viewLayout.addLayout(title_row)

        subtitle_key = "confirm_dlg_subtitle_multi" if multi_jobs else "confirm_dlg_subtitle_single"
        self.subtitle_label = CaptionLabel(self._i18n.tr(subtitle_key), self.widget)
        self.subtitle_label.setStyleSheet(f"color: {muted_fg}; font-size: 12px;")
        self.subtitle_label.setWordWrap(True)
        self.viewLayout.addWidget(self.subtitle_label)

        self.nav_bar = QFrame(self.widget)
        self.nav_bar.setObjectName("confirmNavBar")
        L4d2ThemeManager.install_surface_motion(
            self.nav_bar,
            f"QFrame#confirmNavBar {{ background-color: {{bg}}; border: 1px solid {border_fg}; border-radius: 7px; }}",
            tone="neutral",
        )
        nav_lay = QHBoxLayout(self.nav_bar)
        nav_lay.setContentsMargins(8, 6, 8, 6)
        nav_lay.setSpacing(8)

        self.prev_btn = PushButton(FluentIcon.LEFT_ARROW, self._i18n.tr("confirm_dlg_prev"), self.nav_bar)
        self.prev_btn.setFixedHeight(30)
        self.prev_btn.clicked.connect(self._go_prev)

        self.next_btn = PushButton(FluentIcon.RIGHT_ARROW, self._i18n.tr("confirm_dlg_next"), self.nav_bar)
        self.next_btn.setFixedHeight(30)
        self.next_btn.setLayoutDirection(Qt.LayoutDirection.RightToLeft)
        self.next_btn.clicked.connect(self._go_next)

        counter_col = QVBoxLayout()
        counter_col.setContentsMargins(0, 0, 0, 0)
        counter_col.setSpacing(1)
        self.pager_label = StrongBodyLabel("", self.nav_bar)
        self.pager_label.setAlignment(Qt.AlignmentFlag.AlignCenter)
        self.pager_label.setStyleSheet(
            f"color: {COLORS.amber if is_dark else COLORS.red_dark}; font-size: 13px; border: none; background: transparent;"
        )
        self.breadcrumb_label = CaptionLabel("", self.nav_bar)
        self.breadcrumb_label.setTextFormat(Qt.TextFormat.RichText)
        self.breadcrumb_label.setAlignment(Qt.AlignmentFlag.AlignCenter)
        self.breadcrumb_label.setStyleSheet("font-size: 11px; border: none; background: transparent;")
        counter_col.addWidget(self.pager_label)
        counter_col.addWidget(self.breadcrumb_label)

        nav_lay.addWidget(self.prev_btn)
        nav_lay.addLayout(counter_col, 1)
        nav_lay.addWidget(self.next_btn)
        self.nav_bar.setVisible(multi_jobs)
        self.viewLayout.addWidget(self.nav_bar)

        self.summary_card = CardWidget(self.widget)
        self.summary_card.setStyleSheet(
            f"CardWidget {{ background-color: {card_bg}; border: 1px solid {border_fg}; border-radius: 8px; }}"
        )
        card_lay = QVBoxLayout(self.summary_card)
        card_lay.setContentsMargins(16, 14, 16, 14)
        card_lay.setSpacing(12)

        top_info = QHBoxLayout()
        top_info.setSpacing(14)
        self.cover_label = QLabel(self.summary_card)
        self.cover_label.setObjectName("confirmCoverThumb")
        self.cover_label.setFixedSize(116, 72)
        self.cover_label.setAlignment(Qt.AlignmentFlag.AlignCenter)
        L4d2ThemeManager.install_surface_motion(
            self.cover_label,
            f"QLabel#confirmCoverThumb {{ border: 1px solid {{border}}; border-radius: 6px; "
            f"background-color: {{bg}}; color: {muted_fg}; font-size: 11px; }}",
            custom_colors=L4d2ThemeManager.image_surface_palette(is_dark),
            border_colors=L4d2ThemeManager.image_border_colors(is_dark),
        )

        meta_col = QVBoxLayout()
        meta_col.setSpacing(4)
        self.mod_title_label = SubtitleLabel("", self.summary_card)
        self.mod_title_label.setStyleSheet(f"color: {text_fg}; font-size: 15px;")
        self.mod_title_label.setWordWrap(True)
        self.mod_meta_label = CaptionLabel("", self.summary_card)
        self.mod_meta_label.setStyleSheet(f"color: {muted_fg}; font-size: 12px;")
        self.mod_meta_label.setWordWrap(True)
        self.mod_out_label = CaptionLabel("", self.summary_card)
        self.mod_out_label.setStyleSheet(f"color: {muted_fg}; font-size: 12px;")
        self.mod_out_label.setWordWrap(True)
        meta_col.addWidget(self.mod_title_label)
        meta_col.addWidget(self.mod_meta_label)
        meta_col.addWidget(self.mod_out_label)
        meta_col.addStretch(1)

        top_info.addWidget(self.cover_label, 0, Qt.AlignmentFlag.AlignTop)
        top_info.addLayout(meta_col, 1)
        card_lay.addLayout(top_info)

        divider = QFrame(self.summary_card)
        divider.setFrameShape(QFrame.Shape.HLine)
        divider.setFixedHeight(1)
        divider.setStyleSheet(f"background-color: {border_fg}; border: none;")
        card_lay.addWidget(divider)

        self.route_box = QFrame(self.summary_card)
        self.route_box.setObjectName("confirmRouteBox")
        L4d2ThemeManager.install_surface_motion(
            self.route_box,
            f"QFrame#confirmRouteBox {{ background-color: {{bg}}; border: 1px solid {border_fg}; border-radius: 7px; }}",
            tone="neutral",
        )
        route_lay = QVBoxLayout(self.route_box)
        route_lay.setContentsMargins(12, 10, 12, 10)
        route_lay.setSpacing(8)

        route_top = QHBoxLayout()
        route_top.setSpacing(8)
        self.origin_tag = CaptionLabel(self._i18n.tr("confirm_dlg_origin_tag"), self.route_box)
        self.origin_tag.setStyleSheet(f"color: {muted_fg}; font-weight: 700; font-size: 10px; border: none;")
        self.origin_holder = QHBoxLayout()
        self.origin_holder.setContentsMargins(0, 0, 0, 0)

        arrow = QLabel("➜", self.route_box)
        arrow.setStyleSheet(
            f"color: {COLORS.amber if is_dark else COLORS.red}; font-size: 15px; font-weight: 700; border: none;"
        )
        self.dests_tag = CaptionLabel(self._i18n.tr("confirm_dlg_dests_tag"), self.route_box)
        self.dests_tag.setStyleSheet(f"color: {muted_fg}; font-weight: 700; font-size: 10px; border: none;")

        self.dests_grid = QGridLayout()
        self.dests_grid.setContentsMargins(0, 0, 0, 0)
        self.dests_grid.setHorizontalSpacing(6)
        self.dests_grid.setVerticalSpacing(6)

        route_top.addWidget(self.origin_tag, 0, Qt.AlignmentFlag.AlignVCenter)
        route_top.addLayout(self.origin_holder)
        route_top.addWidget(arrow, 0, Qt.AlignmentFlag.AlignVCenter)
        route_top.addWidget(self.dests_tag, 0, Qt.AlignmentFlag.AlignVCenter)
        route_top.addLayout(self.dests_grid, 1)
        route_lay.addLayout(route_top)

        self.outputs_label = CaptionLabel("", self.route_box)
        self.outputs_label.setWordWrap(True)
        self.outputs_label.setStyleSheet(f"color: {text_fg}; font-size: 12px; border: none;")
        route_lay.addWidget(self.outputs_label)
        card_lay.addWidget(self.route_box)

        opts_title = StrongBodyLabel(self._i18n.tr("confirm_dlg_options_hdr"), self.summary_card)
        opts_title.setStyleSheet(f"color: {text_fg}; font-size: 12px;")
        card_lay.addWidget(opts_title)

        self.opts_grid = QGridLayout()
        self.opts_grid.setContentsMargins(0, 0, 0, 0)
        self.opts_grid.setHorizontalSpacing(18)
        self.opts_grid.setVerticalSpacing(4)
        card_lay.addLayout(self.opts_grid)

        self.viewLayout.addWidget(self.summary_card)

        self.note_banner = QFrame(self.widget)
        note_lay = QHBoxLayout(self.note_banner)
        note_lay.setContentsMargins(10, 7, 10, 7)
        note_lay.setSpacing(8)
        self.note_icon = QLabel("ℹ", self.note_banner)
        self.note_text = CaptionLabel("", self.note_banner)
        self.note_text.setWordWrap(True)
        note_lay.addWidget(self.note_icon)
        note_lay.addWidget(self.note_text, 1)
        self.viewLayout.addWidget(self.note_banner)

        start_btn_text = self._i18n.tr_plural("confirm_dlg_btn_start", len(self._entries))
        L4d2ThemeManager.style_dialog_yes_button(self.yesButton, start_btn_text, FluentIcon.PLAY)
        L4d2ThemeManager.style_dialog_cancel_button(
            self.cancelButton,
            self._i18n.tr("confirm_dlg_btn_cancel"),
            FluentIcon.CLOSE,
        )

        self._render_current_entry()
        L4d2ThemeManager.apply_pointing_hand_cursors(self)
        L4d2ThemeManager.enable_card_hover(self.widget)

    @property
    def current_index(self) -> int:
        return self._index

    def _go_prev(self) -> None:
        if self._index > 0:
            self._index -= 1
            self._render_current_entry()

    def _go_next(self) -> None:
        if self._index < len(self._entries) - 1:
            self._index += 1
            self._render_current_entry()

    def keyPressEvent(self, event: QKeyEvent) -> None:
        if len(self._entries) > 1:
            if event.key() == Qt.Key.Key_Left:
                self._go_prev()
                return
            if event.key() == Qt.Key.Key_Right:
                self._go_next()
                return
        super().keyPressEvent(event)

    def _build_option_badge(self, label: str, enabled: bool) -> QWidget:
        is_dark = isDarkTheme()
        row_w = QWidget(self.summary_card)
        row = QHBoxLayout(row_w)
        row.setContentsMargins(0, 2, 0, 2)
        row.setSpacing(6)
        dot = QLabel("✓" if enabled else "—", row_w)
        dot.setFixedSize(18, 18)
        dot.setAlignment(Qt.AlignmentFlag.AlignCenter)
        if enabled:
            dot.setStyleSheet(
                f"QLabel {{"
                f"  background-color: {'rgba(34, 197, 94, 0.18)' if is_dark else '#DCFCE7'};"
                f"  color: {'#4ADE80' if is_dark else '#15803D'};"
                f"  border: 1px solid {'rgba(74, 222, 128, 0.45)' if is_dark else '#86EFAC'};"
                f"  border-radius: 9px; font-weight: 700; font-size: 11px;"
                f"}}"
            )
        else:
            dot.setStyleSheet(
                f"QLabel {{"
                f"  background-color: {'rgba(168, 176, 190, 0.12)' if is_dark else '#E7E3D9'};"
                f"  color: {COLORS.dark_muted if is_dark else COLORS.light_muted};"
                f"  border: 1px solid {COLORS.dark_border if is_dark else COLORS.light_border};"
                f"  border-radius: 9px; font-weight: 700; font-size: 11px;"
                f"}}"
            )
        fg = (COLORS.dark_text if is_dark else COLORS.light_text) if enabled else (
            COLORS.dark_muted if is_dark else COLORS.light_muted
        )
        txt = CaptionLabel(label, row_w)
        txt.setStyleSheet(f"color: {fg}; font-size: 12px;")
        row.addWidget(dot)
        row.addWidget(txt)
        row.addStretch(1)
        return row_w

    def _update_breadcrumb(self) -> None:
        total = len(self._entries)
        if total <= 1:
            return
        is_dark = isDarkTheme()
        text_fg = COLORS.dark_text if is_dark else COLORS.light_text
        muted_fg = COLORS.dark_muted if is_dark else COLORS.light_muted

        window_size = 3
        start = max(0, min(self._index - 1, total - window_size))
        end = min(total, start + window_size)
        parts: list[str] = []
        if start > 0:
            parts.append(f"<span style='color:{muted_fg};'>…</span>")
        for idx in range(start, end):
            short_title = self._entries[idx].title
            if len(short_title) > 22:
                short_title = f"{short_title[:20]}…"
            label = escape(f"{idx + 1}. {short_title}")
            if idx == self._index:
                parts.append(f"<span style='color:{text_fg}; font-weight:700;'>{label}</span>")
            else:
                parts.append(f"<span style='color:{muted_fg};'>{label}</span>")
        if end < total:
            parts.append(f"<span style='color:{muted_fg};'>…</span>")
        sep = f"<span style='color:{muted_fg};'>&nbsp;&nbsp;•&nbsp;&nbsp;</span>"
        self.breadcrumb_label.setText(sep.join(parts))

    def _render_current_entry(self) -> None:
        if not self._entries:
            return
        entry = self._entries[self._index]
        is_dark = isDarkTheme()
        text_fg = COLORS.dark_text if is_dark else COLORS.light_text
        muted_fg = COLORS.dark_muted if is_dark else COLORS.light_muted
        border_fg = COLORS.dark_border if is_dark else COLORS.light_border
        amber_border = COLORS.amber if is_dark else "#9E7000"
        amber_fg = COLORS.amber_bright if is_dark else "#111315"
        dest_bg = "#261F10" if is_dark else "#FDECA8"
        orig_bg = "#151922" if is_dark else "#E7E1D3"

        self.prev_btn.setEnabled(self._index > 0)
        self.next_btn.setEnabled(self._index < len(self._entries) - 1)
        self.pager_label.setText(
            self._i18n.tr("confirm_dlg_pager", index=self._index + 1, total=len(self._entries))
        )
        self._update_breadcrumb()

        pix = QPixmap()
        if entry.cover_bytes and pix.loadFromData(entry.cover_bytes) and not pix.isNull():
            self.cover_label.setPixmap(
                pix.scaled(
                    self.cover_label.size(),
                    Qt.AspectRatioMode.KeepAspectRatio,
                    Qt.TransformationMode.SmoothTransformation,
                )
            )
            self.cover_label.setText("")
        else:
            self.cover_label.setPixmap(QPixmap())
            self.cover_label.setText(self._i18n.tr("confirm_dlg_no_cover"))

        self.mod_title_label.setText(entry.title)
        meta_parts = [self._i18n.tr("confirm_dlg_file_prefix", name=entry.source_filename)]
        if entry.author:
            meta_parts.append(self._i18n.tr("confirm_dlg_author_prefix", author=entry.author))
        if entry.version:
            meta_parts.append(self._i18n.tr("confirm_dlg_version_prefix", version=entry.version))
        self.mod_meta_label.setText("   •   ".join(meta_parts))
        self.mod_out_label.setText(self._i18n.tr("confirm_dlg_output_dir", path=entry.output_dir))

        _clear_layout_widgets(self.origin_holder)
        origin_spec = SurvivorRegistry.get(entry.origin)
        self.origin_holder.addWidget(
            _SurvivorRoutePill(
                survivor_id=entry.origin,
                label_text=f"{origin_spec.display_name} ({origin_spec.generation})",
                bg=orig_bg,
                border=border_fg,
                fg=text_fg,
                parent=self.route_box,
            )
        )

        _clear_layout_widgets(self.dests_grid)
        max_cols = 4
        for idx, dest_id in enumerate(entry.destinations):
            row_i, col_i = divmod(idx, max_cols)
            dest_spec = SurvivorRegistry.get(dest_id)
            pill = _SurvivorRoutePill(
                survivor_id=dest_id,
                label_text=dest_spec.display_name,
                bg=dest_bg,
                border=amber_border,
                fg=amber_fg,
                parent=self.route_box,
            )
            self.dests_grid.addWidget(pill, row_i, col_i)
        self.dests_grid.setColumnStretch(max_cols, 1)

        files_text = "  •  ".join(entry.output_files)
        self.outputs_label.setText(
            self._i18n.tr("confirm_dlg_outputs_hdr", count=len(entry.output_files), names=files_text)
        )

        _clear_layout_widgets(self.opts_grid)
        opts: list[tuple[str, bool]] = [
            (self._i18n.tr("confirm_dlg_opt_arms"), entry.include_arms),
            (self._i18n.tr("confirm_dlg_opt_vgui"), entry.include_vgui),
            (self._i18n.tr("confirm_dlg_opt_sanitize"), entry.sanitize_origin),
            (self._i18n.tr("confirm_dlg_opt_install"), entry.install_to_addons),
        ]
        if entry.include_weapons is not None:
            opts.append((self._i18n.tr("confirm_dlg_opt_weapons"), entry.include_weapons))
        for idx, (lbl_txt, is_enabled) in enumerate(opts):
            self.opts_grid.addWidget(self._build_option_badge(lbl_txt, is_enabled), idx // 2, idx % 2)

        if entry.install_to_addons:
            custom = (
                (QColor(245, 183, 0, 20), QColor(245, 183, 0, 36), QColor(245, 183, 0, 52))
                if is_dark
                else (QColor("#FEF6D8"), QColor("#FCEAB2"), QColor("#F8DC88"))
            )
            brd = "rgba(245, 183, 0, 0.35)" if is_dark else "#C98E00"
            ico_fg = COLORS.amber if is_dark else "#9E7000"
            note_key = "confirm_dlg_note_addons_install"
        else:
            custom = (
                (QColor(168, 176, 190, 20), QColor(255, 255, 255, 22), QColor(255, 255, 255, 34))
                if is_dark
                else (QColor("#EFECE4"), QColor("#E4DFD2"), QColor("#DAD4C4"))
            )
            brd = border_fg
            ico_fg = muted_fg
            note_key = "confirm_dlg_note_output_only"

        self.note_banner.setObjectName("confirmNoteBanner")
        L4d2ThemeManager.install_surface_motion(
            self.note_banner,
            f"QFrame#confirmNoteBanner {{ background-color: {{bg}}; border: 1px solid {brd}; border-radius: 6px; }}",
            custom_colors=custom,
        )
        self.note_icon.setStyleSheet(
            f"color: {ico_fg}; font-weight: 700; font-size: 13px; border: none; background: transparent;"
        )
        self.note_text.setStyleSheet(
            f"color: {text_fg if entry.install_to_addons else muted_fg}; font-size: 12px; border: none; background: transparent;"
        )
        self.note_text.setText(self._i18n.tr(note_key))
