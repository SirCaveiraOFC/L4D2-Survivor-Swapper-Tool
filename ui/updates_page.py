from __future__ import annotations

import threading
from pathlib import Path
from typing import Callable, Optional

from PySide6.QtCore import QObject, QThread, QUrl, Qt, Signal
from PySide6.QtGui import QColor, QDesktopServices
from PySide6.QtWidgets import (
    QAbstractItemView,
    QFrame,
    QHBoxLayout,
    QHeaderView,
    QLabel,
    QSizePolicy,
    QTableWidgetItem,
    QVBoxLayout,
    QWidget,
)
from qfluentwidgets import (
    BodyLabel,
    CaptionLabel,
    FluentIcon,
    HeaderCardWidget,
    IconWidget,
    InfoBadge,
    InfoBar,
    InfoBarPosition,
    InfoLevel,
    LineEdit,
    MessageBox,
    PrimaryPushButton,
    ProgressBar,
    PushButton,
    ScrollArea,
    StrongBodyLabel,
    SubtitleLabel,
    TableWidget,
    TextBrowser,
    isDarkTheme,
)

from core.app_meta import APP_META
from core.config_manager import ConfigManager
from core.i18n import LocalizationManager
from core.models import AppConfig
from core.updater import (
    GITHUB_WEB_BASE,
    StagedUpdatePlan,
    UpdateApplyResult,
    UpdateCheckResult,
    UpdateError,
    UpdateFileChange,
    apply_staged_update,
    check_for_updates,
    normalize_github_repo,
    parse_version_tuple,
    stage_update_from_zip,
)
from core.workshop_downloader import format_bytes
from ui.addon_ui_shared import (
    CenteredIconHeaderView,
    create_icon_row,
    set_table_headers_with_icons,
    shutdown_worker_thread,
)
from ui.theme import COLORS, L4d2ThemeManager
from ui.widgets import (
    FlowPanel,
    add_card_header_icon,
    create_switch_with_help,
    update_switch_help,
)


class UpdateCheckWorker(QObject):
    """Background worker querying GitHub release/branch metadata and changed file tree."""

    checked = Signal(object, bool)
    failed = Signal(str, object, bool)
    done = Signal()

    def __init__(
        self,
        repo: str,
        current_version: str,
        project_root: Path,
        branch: str = "main",
        extra_protected: tuple[str, ...] = (),
        silent: bool = False,
    ) -> None:
        super().__init__()
        self._repo = repo
        self._current_version = current_version
        self._project_root = project_root
        self._branch = branch
        self._extra_protected = extra_protected
        self._silent = silent
        self._cancel_event = threading.Event()

    def request_cancel(self) -> None:
        self._cancel_event.set()

    def run(self) -> None:
        try:
            if self._cancel_event.is_set():
                return
            result = check_for_updates(
                repo=self._repo,
                current_version=self._current_version,
                project_root=self._project_root,
                branch=self._branch,
                extra_protected_roots=self._extra_protected,
            )
            if not self._cancel_event.is_set():
                self.checked.emit(result, self._silent)
        except UpdateError as exc:
            if not self._cancel_event.is_set():
                self.failed.emit(exc.key, exc.kwargs, self._silent)
        except Exception as exc:
            if not self._cancel_event.is_set():
                self.failed.emit("upd_err_network", {"reason": str(exc)}, self._silent)
        finally:
            self.done.emit()


class UpdateApplyWorker(QObject):
    """Background worker downloading the GitHub archive, diffing files, and applying updates."""

    progressUpdated = Signal(int, int)
    applyingStage = Signal()
    finished = Signal(object, object)
    failed = Signal(str, object)
    done = Signal()

    def __init__(
        self,
        zip_url: str,
        repo: str,
        target_version: str,
        project_root: Path,
        extra_protected: tuple[str, ...] = (),
    ) -> None:
        super().__init__()
        self._zip_url = zip_url
        self._repo = repo
        self._target_version = target_version
        self._project_root = project_root
        self._extra_protected = extra_protected
        self._cancel_event = threading.Event()

    def request_cancel(self) -> None:
        self._cancel_event.set()

    def run(self) -> None:
        try:
            plan = stage_update_from_zip(
                zip_url=self._zip_url,
                repo=self._repo,
                target_version=self._target_version,
                project_root=self._project_root,
                extra_protected_roots=self._extra_protected,
                progress_cb=lambda done, total: self.progressUpdated.emit(done, total),
                cancel_event=self._cancel_event,
            )
            self.applyingStage.emit()
            apply_res = apply_staged_update(
                plan=plan,
                project_root=self._project_root,
                install_requirements=True,
                keep_backup=True,
            )
            self.finished.emit(plan, apply_res)
        except UpdateError as exc:
            self.failed.emit(exc.key, exc.kwargs)
        except Exception as exc:
            self.failed.emit("upd_err_network", {"reason": str(exc)})
        finally:
            self.done.emit()


class UpdatesPage(ScrollArea):
    """Dedicated GitHub update checker, changelog viewer, and safe differential updater."""

    updateAvailabilityChanged = Signal(bool, str)
    relaunchRequested = Signal()

    def __init__(
        self,
        config_mgr: ConfigManager,
        get_config_fn: Callable[[], AppConfig],
        project_root: Path,
        i18n: Optional[LocalizationManager] = None,
        parent: Optional[QWidget] = None,
    ) -> None:
        super().__init__(parent)
        self.setObjectName("updatesPage")
        self.config_mgr = config_mgr
        self._get_config = get_config_fn
        self.project_root = Path(project_root)
        self._i18n = i18n or LocalizationManager("en-US")

        self._check_thread: Optional[QThread] = None
        self._check_worker: Optional[UpdateCheckWorker] = None
        self._apply_thread: Optional[QThread] = None
        self._apply_worker: Optional[UpdateApplyWorker] = None
        self._last_check: Optional[UpdateCheckResult] = None
        self._last_changes: list[UpdateFileChange] = []
        self._busy = False
        self._status_mode = "idle"
        self._status_kwargs: dict = {}

        self.view = QWidget(self)
        self.setWidget(self.view)
        self.setWidgetResizable(True)
        self.enableTransparentBackground()

        root = QVBoxLayout(self.view)
        root.setContentsMargins(28, 24, 28, 28)
        root.setSpacing(14)

        self.page_title = SubtitleLabel("", self.view)
        self.page_subtitle = BodyLabel("", self.view)
        self.page_subtitle.setWordWrap(True)
        self.page_subtitle.setSizePolicy(QSizePolicy.Policy.Ignored, QSizePolicy.Policy.Preferred)
        root.addLayout(create_icon_row(FluentIcon.UPDATE, self.page_title, self.view))
        root.addWidget(self.page_subtitle)

        self.status_card = HeaderCardWidget(self.view)
        add_card_header_icon(self.status_card, FluentIcon.UPDATE)
        status_inner = QWidget(self.status_card)
        status_col = QVBoxLayout(status_inner)
        status_col.setContentsMargins(0, 0, 0, 0)
        status_col.setSpacing(12)

        ver_strip = QHBoxLayout()
        ver_strip.setSpacing(10)
        self.lbl_current_ver = CaptionLabel("", status_inner)
        self.current_ver_badge = InfoBadge(APP_META.version_tag, status_inner, level=InfoLevel.INFOAMTION)
        arrow_lbl = CaptionLabel("\u2192", status_inner)
        self.lbl_remote_ver = CaptionLabel("", status_inner)
        self.remote_ver_badge = InfoBadge("-", status_inner, level=InfoLevel.INFOAMTION)
        self.overall_badge = InfoBadge("", status_inner, level=InfoLevel.INFOAMTION)

        ver_strip.addWidget(self.lbl_current_ver)
        ver_strip.addWidget(self.current_ver_badge)
        ver_strip.addSpacing(4)
        ver_strip.addWidget(arrow_lbl)
        ver_strip.addSpacing(4)
        ver_strip.addWidget(self.lbl_remote_ver)
        ver_strip.addWidget(self.remote_ver_badge)
        ver_strip.addStretch(1)
        ver_strip.addWidget(self.overall_badge)
        status_col.addLayout(ver_strip)

        repo_row = QHBoxLayout()
        repo_row.setSpacing(8)
        self.lbl_repo = BodyLabel("", status_inner)
        self.lbl_repo.setMinimumWidth(92)
        self.repo_edit = LineEdit(status_inner)
        self.repo_edit.setClearButtonEnabled(True)
        self.save_repo_btn = PushButton(FluentIcon.SAVE, "", status_inner)
        self.open_github_btn = PushButton(FluentIcon.GITHUB, "", status_inner)
        repo_row.addWidget(self.lbl_repo)
        repo_row.addWidget(self.repo_edit, 1)
        repo_row.addWidget(self.save_repo_btn)
        repo_row.addWidget(self.open_github_btn)
        status_col.addLayout(repo_row)

        self.actions_panel = FlowPanel(h_space=10, v_space=8, parent=status_inner)
        self.check_btn = PrimaryPushButton(FluentIcon.SYNC, "", self.actions_panel)
        self.update_btn = PrimaryPushButton(FluentIcon.DOWNLOAD, "", self.actions_panel)
        self.update_btn.setEnabled(False)
        self.cancel_btn = PushButton(FluentIcon.CLOSE, "", self.actions_panel)
        self.cancel_btn.setVisible(False)
        self.cancel_btn.setEnabled(False)
        (
            auto_row,
            self.auto_check_switch,
            self.help_auto_check,
        ) = create_switch_with_help("", True, "", self.actions_panel)

        for w in (self.check_btn, self.update_btn, self.cancel_btn, auto_row):
            self.actions_panel.flow.addWidget(w)
        status_col.addWidget(self.actions_panel)

        self.progress_bar = ProgressBar(status_inner)
        self.progress_bar.setRange(0, 100)
        self.progress_bar.setValue(0)
        self.progress_bar.setVisible(False)
        status_col.addWidget(self.progress_bar)

        self.status_label = CaptionLabel("", status_inner)
        self.status_label.setWordWrap(True)
        status_col.addWidget(self.status_label)

        self.status_card.viewLayout.addWidget(status_inner)
        root.addWidget(self.status_card)

        self.notes_card = HeaderCardWidget(self.view)
        add_card_header_icon(self.notes_card, FluentIcon.DOCUMENT)
        self.notes_browser = TextBrowser(self.notes_card)
        self.notes_browser.setOpenExternalLinks(True)
        self.notes_browser.setReadOnly(True)
        self.notes_browser.setMinimumHeight(105)
        self.notes_browser.setMaximumHeight(160)
        self.notes_card.viewLayout.addWidget(self.notes_browser)
        root.addWidget(self.notes_card)

        self.files_card = HeaderCardWidget(self.view)
        add_card_header_icon(self.files_card, FluentIcon.FOLDER)
        files_inner = QWidget(self.files_card)
        files_col = QVBoxLayout(files_inner)
        files_col.setContentsMargins(0, 0, 0, 0)
        files_col.setSpacing(10)

        top_files_row = QHBoxLayout()
        top_files_row.setSpacing(10)
        self.files_summary_label = StrongBodyLabel("", files_inner)
        top_files_row.addWidget(self.files_summary_label, 1)
        files_col.addLayout(top_files_row)

        self.protect_banner = QFrame(files_inner)
        self.protect_banner.setObjectName("updProtectBanner")
        pb_lay = QHBoxLayout(self.protect_banner)
        pb_lay.setContentsMargins(10, 6, 10, 6)
        pb_lay.setSpacing(8)
        pb_icon = IconWidget(FluentIcon.COMPLETED, self.protect_banner)
        pb_icon.setFixedSize(14, 14)
        self.protect_label = CaptionLabel("", self.protect_banner)
        self.protect_label.setWordWrap(True)
        pb_lay.addWidget(pb_icon, 0, Qt.AlignmentFlag.AlignVCenter)
        pb_lay.addWidget(self.protect_label, 1, Qt.AlignmentFlag.AlignVCenter)
        files_col.addWidget(self.protect_banner)

        self.files_table = TableWidget(files_inner)
        self.files_table.setHorizontalHeader(CenteredIconHeaderView(Qt.Orientation.Horizontal, self.files_table))
        self.files_table.setColumnCount(3)
        self.files_table.setSelectionMode(QAbstractItemView.SelectionMode.SingleSelection)
        self.files_table.setSelectionBehavior(QAbstractItemView.SelectionBehavior.SelectRows)
        self.files_table.setEditTriggers(QAbstractItemView.EditTrigger.NoEditTriggers)
        self.files_table.setFocusPolicy(Qt.FocusPolicy.NoFocus)
        self.files_table.verticalHeader().setVisible(False)
        self.files_table.setBorderVisible(True)
        self.files_table.setBorderRadius(6)
        self.files_table.setWordWrap(False)
        self.files_table.horizontalHeader().setSectionResizeMode(0, QHeaderView.ResizeMode.ResizeToContents)
        self.files_table.horizontalHeader().setSectionResizeMode(1, QHeaderView.ResizeMode.Stretch)
        self.files_table.horizontalHeader().setSectionResizeMode(2, QHeaderView.ResizeMode.ResizeToContents)
        self.files_table.setMinimumHeight(200)
        files_col.addWidget(self.files_table)

        self.files_card.viewLayout.addWidget(files_inner)
        root.addWidget(self.files_card)
        root.addStretch(1)

        self.save_repo_btn.clicked.connect(self._on_save_repo)
        self.open_github_btn.clicked.connect(self._on_open_github)
        self.check_btn.clicked.connect(lambda: self.start_check(silent=False))
        self.update_btn.clicked.connect(self._on_install_update)
        self.cancel_btn.clicked.connect(self._on_cancel)
        self.auto_check_switch.checkedChanged.connect(self._on_auto_check_toggled)
        self.repo_edit.textChanged.connect(self._refresh_repo_buttons)

        self.load_from_config()
        self.retranslate_ui(self._i18n)

    def _effective_repo(self) -> str:
        cfg = self._get_config()
        typed = self.repo_edit.text().strip()
        return typed or (cfg.github_repo or "").strip() or (APP_META.github_repo or "").strip()

    def _extra_protected_roots(self) -> tuple[str, ...]:
        cfg = self._get_config()
        extras: list[str] = []
        for raw_val in (cfg.output_dir, cfg.workshop_download_dir, cfg.kit_dir):
            text = (raw_val or "").strip()
            if not text:
                continue
            p = Path(text)
            if not p.is_absolute():
                extras.append(p.as_posix())
            else:
                try:
                    extras.append(p.resolve().relative_to(self.project_root.resolve()).as_posix())
                except ValueError:
                    pass
        return tuple(extras)

    def load_from_config(self) -> None:
        cfg = self._get_config()
        repo = (cfg.github_repo or "").strip() or (APP_META.github_repo or "").strip()
        self.repo_edit.blockSignals(True)
        self.repo_edit.setText(repo)
        self.repo_edit.blockSignals(False)
        self.auto_check_switch.blockSignals(True)
        self.auto_check_switch.setChecked(bool(cfg.auto_check_updates))
        self.auto_check_switch.blockSignals(False)
        if not repo and self._last_check is None:
            self._status_mode = "no_repo"
            self._status_kwargs = {}
        self._refresh_repo_buttons()

    def _refresh_repo_buttons(self) -> None:
        raw = self._effective_repo()
        valid = False
        if raw:
            try:
                normalize_github_repo(raw)
                valid = True
            except UpdateError:
                valid = False
        self.open_github_btn.setEnabled(valid)
        self.check_btn.setEnabled(valid and not self._busy)

    def _apply_theme_styles(self) -> None:
        is_dark = isDarkTheme()
        border_fg = COLORS.dark_border if is_dark else COLORS.light_border
        canvas_bg = COLORS.dark_card_alt if is_dark else COLORS.light_card_alt
        muted_fg = COLORS.dark_muted if is_dark else COLORS.light_muted
        text_fg = COLORS.dark_text if is_dark else COLORS.light_text
        ok_bg = "rgba(34, 197, 94, 0.14)" if is_dark else "#ECFDF3"
        ok_border = "rgba(74, 222, 128, 0.42)" if is_dark else "#86EFAC"
        ok_fg = "#86EFAC" if is_dark else "#166534"
        self.notes_browser.setStyleSheet(
            f"TextBrowser {{ background-color: {canvas_bg}; color: {text_fg}; "
            f"border: 1px solid {border_fg}; border-radius: 6px; padding: 8px; }}"
        )
        L4d2ThemeManager.style_rich_text_browser(
            self.notes_browser,
            is_dark,
            style_markdown_runs=bool(self._last_check and self._last_check.release_notes.strip()),
        )
        self.protect_banner.setStyleSheet(
            f"QFrame#updProtectBanner {{ background-color: {ok_bg}; border: 1px solid {ok_border}; "
            f"border-radius: 6px; }}"
        )
        self.protect_label.setStyleSheet(f"color: {ok_fg}; font-size: 11px; border: none;")
        self.status_label.setStyleSheet(f"color: {muted_fg}; font-size: 12px;")

    def retranslate_ui(self, i18n: LocalizationManager) -> None:
        self._i18n = i18n
        self.page_title.setText(i18n.tr("upd_page_title"))
        self.page_subtitle.setText(i18n.tr("upd_page_subtitle"))

        self.status_card.setTitle(i18n.tr("upd_card_status_title"))
        self.lbl_current_ver.setText(i18n.tr("upd_lbl_current_ver"))
        self.lbl_remote_ver.setText(i18n.tr("upd_lbl_remote_ver"))
        self.lbl_repo.setText(i18n.tr("upd_lbl_repo"))
        self.repo_edit.setPlaceholderText(i18n.tr("upd_repo_placeholder"))
        self.save_repo_btn.setText(i18n.tr("upd_btn_save_repo"))
        self.open_github_btn.setText(i18n.tr("upd_btn_open_github"))
        self.check_btn.setText(i18n.tr("upd_btn_check"))
        self.update_btn.setText(i18n.tr("upd_btn_update_now"))
        self.cancel_btn.setText(i18n.tr("upd_btn_cancel"))
        update_switch_help(
            self.auto_check_switch,
            self.help_auto_check,
            i18n.tr("upd_switch_auto_check"),
            i18n.tr("upd_help_auto_check"),
        )
        self.actions_panel.sync_height(fallback_width=max(560, self.status_card.width() - 60))

        self.notes_card.setTitle(i18n.tr("upd_notes_card_title"))
        self.files_card.setTitle(i18n.tr("upd_files_card_title"))
        self.protect_label.setText(i18n.tr("upd_protect_note"))
        set_table_headers_with_icons(
            self.files_table,
            [
                (FluentIcon.TAG, i18n.tr("upd_col_type")),
                (FluentIcon.FOLDER, i18n.tr("upd_col_path")),
                (FluentIcon.INFO, i18n.tr("upd_col_size")),
            ],
        )

        self._apply_theme_styles()
        self._render_status_and_details()
        L4d2ThemeManager.apply_pointing_hand_cursors(self)

    def _on_auto_check_toggled(self, checked: bool) -> None:
        cfg = self._get_config()
        cfg.auto_check_updates = bool(checked)
        self.config_mgr.save(cfg)

    def _on_save_repo(self) -> None:
        raw = self.repo_edit.text().strip()
        cfg = self._get_config()
        if not raw:
            cfg.github_repo = ""
            self.config_mgr.save(cfg)
            self._status_mode = "no_repo"
            self._status_kwargs = {}
            self._render_status_and_details()
            self._refresh_repo_buttons()
            return
        try:
            slug = normalize_github_repo(raw)
        except UpdateError as exc:
            InfoBar.warning(
                self._i18n.tr("upd_err_title"),
                self._i18n.tr(exc.key, **exc.kwargs),
                parent=self.window(),
                position=InfoBarPosition.TOP,
            )
            return
        self.repo_edit.setText(slug)
        cfg.github_repo = slug
        self.config_mgr.save(cfg)
        self._refresh_repo_buttons()
        InfoBar.success(
            self._i18n.tr("upd_repo_saved_title"),
            self._i18n.tr("upd_repo_saved_msg", repo=slug),
            parent=self.window(),
            position=InfoBarPosition.TOP,
        )

    def _on_open_github(self) -> None:
        raw = self._effective_repo()
        try:
            slug = normalize_github_repo(raw)
        except UpdateError:
            return
        url = self._last_check.html_url if (self._last_check and self._last_check.html_url) else f"{GITHUB_WEB_BASE}/{slug}"
        QDesktopServices.openUrl(QUrl(url))

    def start_background_check_if_enabled(self) -> None:
        cfg = self._get_config()
        if cfg.auto_check_updates and self._effective_repo():
            self.start_check(silent=True)

    def _set_busy(self, busy: bool, downloading: bool = False) -> None:
        self._busy = busy
        self.repo_edit.setEnabled(not busy)
        self.save_repo_btn.setEnabled(not busy)
        self.check_btn.setEnabled(not busy and bool(self._effective_repo()))
        self.update_btn.setEnabled(
            not busy and bool(self._last_check is not None and self._last_check.has_update)
        )
        self.cancel_btn.setVisible(busy and downloading)
        self.cancel_btn.setEnabled(busy and downloading)
        self.actions_panel.sync_height(fallback_width=max(560, self.status_card.width() - 60))
        L4d2ThemeManager.apply_pointing_hand_cursors(self)

    def start_check(self, silent: bool = False) -> None:
        if self._busy:
            return
        raw_repo = self._effective_repo()
        try:
            slug = normalize_github_repo(raw_repo)
        except UpdateError as exc:
            if not silent:
                InfoBar.warning(
                    self._i18n.tr("upd_err_title"),
                    self._i18n.tr(exc.key, **exc.kwargs),
                    parent=self.window(),
                    position=InfoBarPosition.TOP,
                )
            self._status_mode = "no_repo"
            self._render_status_and_details()
            return

        self._set_busy(True, downloading=False)
        self._status_mode = "checking"
        self._status_kwargs = {}
        self.progress_bar.setVisible(False)
        self._render_status_and_details()

        self._check_thread = QThread(self)
        self._check_worker = UpdateCheckWorker(
            repo=slug,
            current_version=APP_META.version,
            project_root=self.project_root,
            branch=APP_META.github_branch,
            extra_protected=self._extra_protected_roots(),
            silent=silent,
        )
        self._check_worker.moveToThread(self._check_thread)
        self._check_thread.started.connect(self._check_worker.run)
        self._check_worker.checked.connect(self._on_check_completed)
        self._check_worker.failed.connect(self._on_check_failed)
        self._check_worker.done.connect(self._check_thread.quit)
        self._check_thread.finished.connect(self._cleanup_check_thread)
        self._check_thread.start()

    def _cleanup_check_thread(self) -> None:
        if self._check_worker is not None:
            self._check_worker.deleteLater()
            self._check_worker = None
        if self._check_thread is not None:
            self._check_thread.deleteLater()
            self._check_thread = None

    def _cleanup_apply_thread(self) -> None:
        if self._apply_worker is not None:
            self._apply_worker.deleteLater()
            self._apply_worker = None
        if self._apply_thread is not None:
            self._apply_thread.deleteLater()
            self._apply_thread = None

    def _on_check_completed(self, result: UpdateCheckResult, _silent: bool) -> None:
        self._last_check = result
        self._last_changes = list(result.preview_changes)
        self._set_busy(False)
        cur_ver = result.current_version or APP_META.version
        rem_ver = result.latest_version or cur_ver
        if result.has_update:
            self._status_mode = "available"
            self._status_kwargs = {"version": f"v{rem_ver}"}
        else:
            cur_tuple = parse_version_tuple(cur_ver)
            rem_tuple = parse_version_tuple(rem_ver)
            if cur_tuple and rem_tuple and cur_tuple > rem_tuple:
                self._status_mode = "ahead"
                self._status_kwargs = {"current": f"v{cur_ver}", "remote": f"v{rem_ver}"}
            else:
                self._status_mode = "up_to_date"
                self._status_kwargs = {"version": f"v{cur_ver}"}
        self._render_status_and_details()
        self.updateAvailabilityChanged.emit(
            result.has_update,
            f"v{result.latest_version}" if result.latest_version else "",
        )

    def _on_check_failed(self, key: str, kwargs: dict, silent: bool) -> None:
        self._set_busy(False)
        err_msg = self._i18n.tr(key, **(kwargs or {}))
        if not silent:
            self._status_mode = "error"
            self._status_kwargs = {"error": err_msg}
            InfoBar.error(
                self._i18n.tr("upd_err_title"),
                err_msg,
                parent=self.window(),
                position=InfoBarPosition.TOP,
                duration=6000,
            )
        else:
            self._status_mode = "idle"
            self._status_kwargs = {}
        self._render_status_and_details()

    def _on_install_update(self) -> None:
        check = self._last_check
        if self._busy or check is None or not check.has_update or not check.zip_url:
            return
        target_v = f"v{check.latest_version}" if check.latest_version else check.release_tag
        confirm = MessageBox(
            self._i18n.tr("upd_confirm_title", version=target_v),
            self._i18n.tr_plural("upd_confirm_msg", len(self._last_changes)),
            self.window(),
        )
        L4d2ThemeManager.style_dialog_yes_button(
            confirm.yesButton,
            self._i18n.tr("upd_confirm_btn"),
            FluentIcon.DOWNLOAD,
        )
        L4d2ThemeManager.style_dialog_cancel_button(
            confirm.cancelButton,
            self._i18n.tr("upd_btn_cancel"),
            FluentIcon.CLOSE,
        )
        if not confirm.exec():
            return

        self._set_busy(True, downloading=True)
        self.progress_bar.setVisible(True)
        self.progress_bar.setValue(0)
        self._status_mode = "downloading"
        self._status_kwargs = {"done": format_bytes(0), "size": "?"}
        self._render_status_and_details()

        self._apply_thread = QThread(self)
        self._apply_worker = UpdateApplyWorker(
            zip_url=check.zip_url,
            repo=check.repo,
            target_version=check.latest_version or APP_META.version,
            project_root=self.project_root,
            extra_protected=self._extra_protected_roots(),
        )
        self._apply_worker.moveToThread(self._apply_thread)
        self._apply_thread.started.connect(self._apply_worker.run)
        self._apply_worker.progressUpdated.connect(self._on_download_progress)
        self._apply_worker.applyingStage.connect(self._on_applying_stage)
        self._apply_worker.finished.connect(self._on_apply_finished)
        self._apply_worker.failed.connect(self._on_apply_failed)
        self._apply_worker.done.connect(self._apply_thread.quit)
        self._apply_thread.finished.connect(self._cleanup_apply_thread)
        self._apply_thread.start()

    def _on_cancel(self) -> None:
        if self._apply_worker is not None:
            self._apply_worker.request_cancel()
            self.cancel_btn.setEnabled(False)

    def _on_download_progress(self, done: int, total: int) -> None:
        pct = int((done / total) * 85) if total > 0 else 20
        self.progress_bar.setValue(max(0, min(90, pct)))
        self.status_label.setText(
            self._i18n.tr(
                "upd_status_downloading",
                done=format_bytes(done),
                size=format_bytes(total) if total > 0 else "?",
            )
        )

    def _on_applying_stage(self) -> None:
        self.progress_bar.setValue(92)
        self.status_label.setText(self._i18n.tr("upd_status_applying"))

    def _on_apply_finished(self, plan: StagedUpdatePlan, result: UpdateApplyResult) -> None:
        self._last_changes = list(plan.changes)
        self._set_busy(False)
        self.progress_bar.setValue(100)
        self._status_mode = "done"
        self._status_kwargs = {
            "version": f"v{plan.target_version}",
            "applied": result.applied_count,
            "removed": result.removed_count,
        }
        self._render_status_and_details()
        self.updateAvailabilityChanged.emit(False, "")

        if result.relaunch_scheduled:
            self.relaunchRequested.emit()
            return

        applied_text = self._i18n.tr_plural("upd_done_applied", result.applied_count)
        removed_text = self._i18n.tr_plural("upd_done_removed", result.removed_count)
        restart_box = MessageBox(
            self._i18n.tr("upd_done_restart_title"),
            self._i18n.tr(
                "upd_done_restart_msg",
                applied_text=applied_text,
                removed_text=removed_text,
                version=plan.target_version,
            ),
            self.window(),
        )
        L4d2ThemeManager.style_dialog_yes_button(
            restart_box.yesButton,
            self._i18n.tr("upd_confirm_btn"),
            FluentIcon.SYNC,
        )
        L4d2ThemeManager.style_dialog_cancel_button(
            restart_box.cancelButton,
            self._i18n.tr("upd_btn_cancel"),
            FluentIcon.CLOSE,
        )
        if restart_box.exec():
            from core.updater import schedule_app_relaunch

            schedule_app_relaunch(self.project_root)
            self.relaunchRequested.emit()

    def _on_apply_failed(self, key: str, kwargs: dict) -> None:
        self._set_busy(False)
        self.progress_bar.setVisible(False)
        err_msg = self._i18n.tr(key, **(kwargs or {}))
        self._status_mode = "error" if key != "upd_err_cancelled" else "idle"
        self._status_kwargs = {"error": err_msg}
        self._render_status_and_details()
        if key != "upd_err_cancelled":
            InfoBar.error(
                self._i18n.tr("upd_err_title"),
                err_msg,
                parent=self.window(),
                position=InfoBarPosition.TOP,
                duration=7000,
            )

    def _render_status_and_details(self) -> None:
        check = self._last_check
        self.remote_ver_badge.setText(f"v{check.latest_version}" if (check and check.latest_version) else "-")

        mode = self._status_mode
        if mode == "checking":
            self.overall_badge.setText(self._i18n.tr("upd_badge_checking"))
            self.overall_badge.setLevel(InfoLevel.INFOAMTION)
            self.status_label.setText(self._i18n.tr("upd_status_checking"))
        elif mode == "no_repo":
            self.overall_badge.setText(self._i18n.tr("upd_badge_no_repo"))
            self.overall_badge.setLevel(InfoLevel.WARNING)
            self.status_label.setText(self._i18n.tr("upd_status_no_repo"))
        elif mode == "available" and check is not None:
            self.overall_badge.setText(self._i18n.tr("upd_badge_available"))
            self.overall_badge.setLevel(InfoLevel.WARNING)
            self.status_label.setText(
                self._i18n.tr_plural(
                    "upd_status_available",
                    len(self._last_changes),
                    version=f"v{check.latest_version}",
                )
            )
        elif mode in ("up_to_date", "ahead"):
            self.overall_badge.setText(self._i18n.tr("upd_badge_up_to_date"))
            self.overall_badge.setLevel(InfoLevel.SUCCESS)
            status_key = "upd_status_ahead" if mode == "ahead" else "upd_status_up_to_date"
            self.status_label.setText(self._i18n.tr(status_key, **self._status_kwargs))
        elif mode == "downloading":
            self.overall_badge.setText(self._i18n.tr("upd_badge_checking"))
            self.overall_badge.setLevel(InfoLevel.INFOAMTION)
            self.status_label.setText(self._i18n.tr("upd_status_downloading", **self._status_kwargs))
        elif mode == "done":
            self.overall_badge.setText(self._i18n.tr("upd_badge_up_to_date"))
            self.overall_badge.setLevel(InfoLevel.SUCCESS)
            self.status_label.setText(self._i18n.tr("upd_status_done", **self._status_kwargs))
        elif mode == "error":
            self.overall_badge.setText(self._i18n.tr("upd_badge_error"))
            self.overall_badge.setLevel(InfoLevel.ERROR)
            self.status_label.setText(self._i18n.tr("upd_status_error", **self._status_kwargs))
        else:
            self.overall_badge.setText(self._i18n.tr("upd_badge_idle"))
            self.overall_badge.setLevel(InfoLevel.INFOAMTION)
            self.status_label.setText(self._i18n.tr("upd_status_idle"))

        self.update_btn.setEnabled(not self._busy and bool(check is not None and check.has_update))

        if check is not None and check.release_notes.strip():
            header = f"### {check.release_title}\n\n" if check.release_title else ""
            self.notes_browser.setMarkdown(f"{header}{check.release_notes}")
            L4d2ThemeManager.style_rich_text_browser(
                self.notes_browser,
                isDarkTheme(),
                style_markdown_runs=True,
            )
        else:
            self.notes_browser.setPlainText(self._i18n.tr("upd_notes_empty"))

        self._populate_files_table()

    def _populate_files_table(self) -> None:
        changes = self._last_changes
        added = sum(1 for c in changes if c.change_type == "added")
        modified = sum(1 for c in changes if c.change_type == "modified")
        removed = sum(1 for c in changes if c.change_type == "removed")
        if changes:
            self.files_summary_label.setText(
                self._i18n.tr("upd_files_summary", added=added, modified=modified, removed=removed)
            )
        else:
            self.files_summary_label.setText(self._i18n.tr("upd_files_empty"))

        is_dark = isDarkTheme()
        type_colors = {
            "added": QColor("#4ADE80" if is_dark else "#15803D"),
            "modified": QColor(COLORS.amber if is_dark else COLORS.amber_deep),
            "removed": QColor("#F87171" if is_dark else "#B91C1C"),
        }
        type_labels = {
            "added": f"+ {self._i18n.tr('upd_type_added')}",
            "modified": f"~ {self._i18n.tr('upd_type_modified')}",
            "removed": f"- {self._i18n.tr('upd_type_removed')}",
        }

        self.files_table.setRowCount(len(changes))
        for row, ch in enumerate(changes):
            t_item = QTableWidgetItem(type_labels.get(ch.change_type, ch.change_type))
            t_item.setForeground(type_colors.get(ch.change_type, QColor(COLORS.dark_text if is_dark else COLORS.light_text)))
            p_item = QTableWidgetItem(ch.rel_path)
            s_item = QTableWidgetItem(format_bytes(ch.size_bytes) if ch.size_bytes > 0 else "—")
            s_item.setTextAlignment(Qt.AlignmentFlag.AlignRight | Qt.AlignmentFlag.AlignVCenter)
            self.files_table.setItem(row, 0, t_item)
            self.files_table.setItem(row, 1, p_item)
            self.files_table.setItem(row, 2, s_item)

    def shutdown_worker(self) -> None:
        shutdown_worker_thread(
            self._check_thread,
            self._check_worker,
            cancel_fn=self._check_worker.request_cancel if self._check_worker is not None else None,
            ui_signals=(
                (self._check_worker.checked, self._check_worker.failed, self._check_worker.done)
                if self._check_worker is not None
                else ()
            ),
            timeout_ms=2500,
        )
        self._check_worker = None
        self._check_thread = None

        shutdown_worker_thread(
            self._apply_thread,
            self._apply_worker,
            cancel_fn=self._apply_worker.request_cancel if self._apply_worker is not None else None,
            ui_signals=(
                (
                    self._apply_worker.progressUpdated,
                    self._apply_worker.applyingStage,
                    self._apply_worker.finished,
                    self._apply_worker.failed,
                    self._apply_worker.done,
                )
                if self._apply_worker is not None
                else ()
            ),
            timeout_ms=3500,
        )
        self._apply_worker = None
        self._apply_thread = None
