from __future__ import annotations

import hashlib
import json
import os
import re
import shutil
import subprocess
import sys
import tempfile
import threading
import urllib.error
import urllib.parse
import urllib.request
import zipfile
from dataclasses import dataclass, field
from pathlib import Path
from typing import Callable, Optional


GITHUB_API_BASE = "https://api.github.com"
GITHUB_WEB_BASE = "https://github.com"
GITHUB_RAW_BASE = "https://raw.githubusercontent.com"

_SEMVER_RE = re.compile(r"v?(\d+)\.(\d+)(?:\.(\d+))?")
_META_PART_RE = re.compile(r"(?m)^\s*(major|minor|patch)\s*:\s*int\s*=\s*(\d+)")
_REPO_SLUG_RE = re.compile(r"^[A-Za-z0-9_.-]+/[A-Za-z0-9_.-]+$")

USER_PROTECTED_FILES = {
    "settings.json",
    "conversion_history.json",
    ".update_manifest.json",
}

USER_PROTECTED_DIRS = {
    "swapped_survivors",
    "survivor_swap",
    "workshop_downloads",
    "runtime",
    "dist",
    ".git",
    ".venv",
    "venv",
    "env",
    "__pycache__",
    ".pytest_cache",
}

USER_PROTECTED_PREFIXES = (
    "_l4d2sw_",
    ".l4d2sw_",
    "l4d2sw_pv_",
)

USER_PROTECTED_SUFFIXES = (
    ".bak",
    ".log",
    ".tmp",
    ".pyc",
    ".pyo",
)

MANAGED_PRUNE_DIRS = (
    "core/",
    "ui/",
    "tests/",
    "tools/",
    "docs/",
)

TEXT_NORMALIZE_EXTS = {
    ".py",
    ".md",
    ".txt",
    ".json",
    ".toml",
    ".vb",
    ".ps1",
    ".yml",
    ".yaml",
}


class UpdateError(RuntimeError):
    """Structured error carrying an i18n message key and formatting arguments."""

    def __init__(self, key: str, **kwargs: object) -> None:
        self.key = key
        self.kwargs = kwargs
        super().__init__(key)


@dataclass(frozen=True)
class UpdateFileChange:
    """Single file difference detected between local workspace and remote GitHub target."""

    rel_path: str
    change_type: str
    size_bytes: int = 0


@dataclass(frozen=True)
class UpdateCheckResult:
    """Remote version inspection result from GitHub Releases or branch metadata."""

    repo: str
    branch: str
    current_version: str
    latest_version: Optional[str]
    has_update: bool
    source_kind: str
    release_tag: str = ""
    release_title: str = ""
    release_notes: str = ""
    published_at: str = ""
    html_url: str = ""
    zip_url: str = ""
    preview_changes: list[UpdateFileChange] = field(default_factory=list)


@dataclass
class StagedUpdatePlan:
    """Extracted remote archive payload and verified local file diff ready to apply."""

    repo: str
    target_version: str
    staging_root: Path
    payload_dir: Path
    changes: list[UpdateFileChange]
    remote_manifest_paths: list[str]
    requirements_changed: bool = False


@dataclass
class UpdateApplyResult:
    """Summary of an applied or deferred GitHub update operation."""

    applied_count: int
    removed_count: int
    deferred_count: int
    requirements_updated: bool
    backup_dir: Optional[Path] = None
    relaunch_scheduled: bool = False
    logs: list[str] = field(default_factory=list)


def normalize_github_repo(raw: str) -> str:
    """Normalize a GitHub repository URL or slug into 'owner/repo' form."""
    text = (raw or "").strip()
    if not text:
        raise UpdateError("upd_err_no_repo")
    text = re.sub(r"^https?://(?:www\.)?github\.com/", "", text, flags=re.I)
    text = re.sub(r"^(?:www\.)?github\.com/", "", text, flags=re.I)
    text = text.strip().strip("/")
    parts = [p for p in text.split("/") if p]
    if len(parts) < 2:
        raise UpdateError("upd_err_invalid_repo")
    owner = parts[0]
    repo = parts[1]
    if repo.lower().endswith(".git"):
        repo = repo[:-4]
    slug = f"{owner}/{repo}"
    if not _REPO_SLUG_RE.match(slug):
        raise UpdateError("upd_err_invalid_repo")
    return slug


def parse_version_tuple(raw: str) -> Optional[tuple[int, int, int]]:
    """Parse semantic version text (e.g. 'v2.1.0' or '2.1') into a 3-int tuple."""
    match = _SEMVER_RE.search((raw or "").strip())
    if not match:
        return None
    major = int(match.group(1))
    minor = int(match.group(2))
    patch = int(match.group(3) or 0)
    return (major, minor, patch)


def format_version_tuple(ver: tuple[int, int, int]) -> str:
    """Format a 3-int semantic version tuple cleanly as 'major.minor.patch'."""
    return f"{ver[0]}.{ver[1]}.{ver[2]}"


def extract_app_meta_version(py_text: str) -> Optional[tuple[int, int, int]]:
    """Extract (major, minor, patch) integer fields from core/app_meta.py text."""
    found: dict[str, int] = {}
    for m in _META_PART_RE.finditer(py_text or ""):
        found[m.group(1)] = int(m.group(2))
    if "major" in found and "minor" in found:
        return (found["major"], found["minor"], found.get("patch", 0))
    return None


def git_blob_sha1(data: bytes) -> str:
    """Compute Git object blob SHA-1 digest matching GitHub Git Trees API entries."""
    header = f"blob {len(data)}\0".encode("ascii")
    return hashlib.sha1(header + data).hexdigest()


def _clean_rel_posix(raw_path: str) -> str:
    norm = (raw_path or "").replace("\\", "/").strip()
    while norm.startswith("./"):
        norm = norm[2:]
    return norm.lstrip("/")


def is_protected_rel_path(rel_posix: str, extra_protected_roots: tuple[str, ...] = ()) -> bool:
    """Return True if rel_posix refers to user config, mods, temp state, or local VCS files."""
    norm = _clean_rel_posix(rel_posix)
    if not norm:
        return True
    lower = norm.lower()
    parts = [p for p in lower.split("/") if p]
    if not parts:
        return True
    first = parts[0]
    if lower in USER_PROTECTED_FILES or first in USER_PROTECTED_DIRS:
        return True
    for part in parts:
        if part in {"__pycache__", ".pytest_cache", ".git", "bin", "obj"}:
            return True
    if any(first.startswith(pref) for pref in USER_PROTECTED_PREFIXES):
        return True
    if any(lower.endswith(suf) for suf in USER_PROTECTED_SUFFIXES):
        return True
    for extra in extra_protected_roots:
        cleaned = _clean_rel_posix(extra).strip("/").lower()
        if cleaned and (lower == cleaned or lower.startswith(f"{cleaned}/")):
            return True
    return False


def _request_json(url: str, timeout: float = 12.0) -> tuple[int, dict | list]:
    req = urllib.request.Request(
        url,
        headers={
            "Accept": "application/vnd.github+json",
            "User-Agent": "L4D2SurvivorSwapper/2.0",
        },
        method="GET",
    )
    with urllib.request.urlopen(req, timeout=timeout) as resp:
        status = getattr(resp, "status", 200) or 200
        raw = resp.read(4 * 1024 * 1024).decode("utf-8", errors="replace")
        return status, json.loads(raw)


def _request_text(url: str, timeout: float = 10.0) -> str:
    req = urllib.request.Request(
        url,
        headers={"User-Agent": "L4D2SurvivorSwapper/2.0"},
        method="GET",
    )
    with urllib.request.urlopen(req, timeout=timeout) as resp:
        return resp.read(2 * 1024 * 1024).decode("utf-8", errors="replace")


def _file_content_matches_sha(local_path: Path, remote_sha: str, rel_posix: str) -> bool:
    try:
        data = local_path.read_bytes()
    except OSError:
        return False
    if git_blob_sha1(data) == remote_sha:
        return True
    if local_path.suffix.lower() in TEXT_NORMALIZE_EXTS and b"\r\n" in data:
        if git_blob_sha1(data.replace(b"\r\n", b"\n")) == remote_sha:
            return True
    return False


def _load_update_manifest(project_root: Path) -> Optional[set[str]]:
    manifest_path = project_root / ".update_manifest.json"
    if not manifest_path.is_file():
        return None
    try:
        raw = json.loads(manifest_path.read_text(encoding="utf-8", errors="ignore"))
        files = raw.get("managed_files") if isinstance(raw, dict) else None
        if isinstance(files, list):
            return {_clean_rel_posix(str(p)) for p in files if p}
    except (OSError, json.JSONDecodeError, TypeError):
        pass
    return None


def _save_update_manifest(project_root: Path, managed_files: list[str], version: str) -> None:
    manifest_path = project_root / ".update_manifest.json"
    payload = {
        "version": version,
        "managed_files": sorted(set(managed_files)),
    }
    manifest_path.write_text(
        json.dumps(payload, indent=2, ensure_ascii=False) + "\n",
        encoding="utf-8",
        newline="\n",
    )


def _list_local_tracked_files(
    project_root: Path,
    extra_protected_roots: tuple[str, ...] = (),
) -> dict[str, Path]:
    found: dict[str, Path] = {}
    if not project_root.exists():
        return found
    manifest = _load_update_manifest(project_root)
    for item in project_root.rglob("*"):
        if not item.is_file():
            continue
        rel = item.relative_to(project_root).as_posix()
        if is_protected_rel_path(rel, extra_protected_roots):
            continue
        if manifest is not None:
            if rel in manifest or rel.lower().startswith(MANAGED_PRUNE_DIRS):
                found[rel] = item
        elif rel.lower().startswith(MANAGED_PRUNE_DIRS):
            found[rel] = item
    return found


def _compute_tree_preview(
    repo: str,
    ref: str,
    project_root: Path,
    extra_protected_roots: tuple[str, ...] = (),
    timeout: float = 10.0,
) -> list[UpdateFileChange]:
    try:
        url = f"{GITHUB_API_BASE}/repos/{repo}/git/trees/{urllib.parse.quote(ref, safe='')}?recursive=1"
        _, payload = _request_json(url, timeout=timeout)
    except Exception:
        return []
    if not isinstance(payload, dict):
        return []
    tree = payload.get("tree")
    if not isinstance(tree, list):
        return []

    remote_blobs: dict[str, tuple[str, int]] = {}
    for entry in tree:
        if not isinstance(entry, dict) or entry.get("type") != "blob":
            continue
        rel = _clean_rel_posix(str(entry.get("path") or ""))
        if not rel or is_protected_rel_path(rel, extra_protected_roots):
            continue
        sha = str(entry.get("sha") or "")
        size = int(entry.get("size") or 0)
        remote_blobs[rel] = (sha, size)

    changes: list[UpdateFileChange] = []
    for rel in sorted(remote_blobs):
        sha, size = remote_blobs[rel]
        local_file = project_root / rel
        if not local_file.exists():
            changes.append(UpdateFileChange(rel_path=rel, change_type="added", size_bytes=size))
        elif sha and not _file_content_matches_sha(local_file, sha, rel):
            changes.append(UpdateFileChange(rel_path=rel, change_type="modified", size_bytes=size))

    local_tracked = _list_local_tracked_files(project_root, extra_protected_roots)
    for rel in sorted(local_tracked):
        if rel not in remote_blobs:
            changes.append(UpdateFileChange(rel_path=rel, change_type="removed", size_bytes=0))

    return changes


def check_for_updates(
    repo: str,
    current_version: str | tuple[int, int, int],
    project_root: Optional[Path] = None,
    branch: str = "main",
    extra_protected_roots: tuple[str, ...] = (),
    timeout: float = 12.0,
) -> UpdateCheckResult:
    """Query GitHub Releases and branch core/app_meta.py to detect newer versions and file diffs."""
    slug = normalize_github_repo(repo)
    cur_tuple = (
        current_version
        if isinstance(current_version, tuple)
        else (parse_version_tuple(current_version) or (0, 0, 0))
    )
    cur_str = format_version_tuple(cur_tuple)
    cleaned_branch = (branch or "main").strip() or "main"

    rel_ver: Optional[tuple[int, int, int]] = None
    rel_tag = ""
    rel_title = ""
    rel_notes = ""
    rel_pub = ""
    rel_html = f"{GITHUB_WEB_BASE}/{slug}"
    rel_zip = ""
    rel_err: Optional[Exception] = None

    try:
        _, rel_json = _request_json(f"{GITHUB_API_BASE}/repos/{slug}/releases/latest", timeout=timeout)
        if isinstance(rel_json, dict) and not rel_json.get("draft"):
            rel_tag = str(rel_json.get("tag_name") or "").strip()
            rel_ver = parse_version_tuple(rel_tag)
            rel_title = str(rel_json.get("name") or rel_tag).strip()
            rel_notes = str(rel_json.get("body") or "").strip()
            rel_pub = str(rel_json.get("published_at") or "").strip()
            rel_html = str(rel_json.get("html_url") or rel_html).strip()
            if rel_tag:
                rel_zip = f"{GITHUB_WEB_BASE}/{slug}/archive/refs/tags/{urllib.parse.quote(rel_tag, safe='')}.zip"
            else:
                rel_zip = str(rel_json.get("zipball_url") or "").strip()
    except urllib.error.HTTPError as exc:
        if exc.code != 404:
            rel_err = exc
    except Exception as exc:
        rel_err = exc

    branch_ver: Optional[tuple[int, int, int]] = None
    branch_err: Optional[Exception] = None
    try:
        raw_meta = _request_text(
            f"{GITHUB_RAW_BASE}/{slug}/{urllib.parse.quote(cleaned_branch, safe='')}/core/app_meta.py",
            timeout=timeout,
        )
        branch_ver = extract_app_meta_version(raw_meta)
    except Exception as exc:
        branch_err = exc

    if rel_ver is None and branch_ver is None:
        err = rel_err or branch_err
        if isinstance(err, urllib.error.HTTPError):
            raise UpdateError("upd_err_http", status=err.code) from err
        if err is not None:
            raise UpdateError("upd_err_network", reason=str(err)) from err
        raise UpdateError("upd_err_no_version")

    use_release = rel_ver is not None and (branch_ver is None or rel_ver >= branch_ver)
    if use_release and rel_ver is not None:
        chosen_ver = rel_ver
        source_kind = "release"
        zip_url = rel_zip or f"{GITHUB_WEB_BASE}/{slug}/archive/refs/tags/{urllib.parse.quote(rel_tag, safe='')}.zip"
        tree_ref = rel_tag or cleaned_branch
        html_url = rel_html
        notes = rel_notes
        title = rel_title
        pub = rel_pub
    else:
        assert branch_ver is not None
        chosen_ver = branch_ver
        source_kind = "branch"
        zip_url = f"{GITHUB_WEB_BASE}/{slug}/archive/refs/heads/{urllib.parse.quote(cleaned_branch, safe='')}.zip"
        tree_ref = cleaned_branch
        html_url = f"{GITHUB_WEB_BASE}/{slug}/tree/{urllib.parse.quote(cleaned_branch, safe='')}"
        title = f"v{format_version_tuple(chosen_ver)} ({cleaned_branch})"
        notes = _fetch_branch_commit_summary(slug, cleaned_branch, timeout=min(8.0, timeout))
        pub = ""

    has_update = chosen_ver > cur_tuple
    preview_changes: list[UpdateFileChange] = []
    if project_root is not None and (has_update or chosen_ver == cur_tuple):
        if has_update:
            preview_changes = _compute_tree_preview(
                repo=slug,
                ref=tree_ref,
                project_root=project_root,
                extra_protected_roots=extra_protected_roots,
                timeout=min(10.0, timeout),
            )

    return UpdateCheckResult(
        repo=slug,
        branch=cleaned_branch,
        current_version=cur_str,
        latest_version=format_version_tuple(chosen_ver),
        has_update=has_update,
        source_kind=source_kind,
        release_tag=rel_tag if use_release else f"v{format_version_tuple(chosen_ver)}",
        release_title=title,
        release_notes=notes,
        published_at=pub,
        html_url=html_url,
        zip_url=zip_url,
        preview_changes=preview_changes,
    )


def _fetch_branch_commit_summary(slug: str, branch: str, timeout: float = 8.0) -> str:
    try:
        url = (
            f"{GITHUB_API_BASE}/repos/{slug}/commits"
            f"?sha={urllib.parse.quote(branch, safe='')}&per_page=8"
        )
        _, commits = _request_json(url, timeout=timeout)
    except Exception:
        return ""
    if not isinstance(commits, list):
        return ""
    lines: list[str] = []
    for item in commits:
        if not isinstance(item, dict):
            continue
        sha = str(item.get("sha") or "")[:7]
        commit_obj = item.get("commit") if isinstance(item.get("commit"), dict) else {}
        msg = str(commit_obj.get("message") or "").splitlines()[0].strip()
        if msg:
            lines.append(f"- `{sha}` {msg}")
    return "\n".join(lines)


def _bytes_match(local_path: Path, remote_path: Path) -> bool:
    try:
        b_local = local_path.read_bytes()
        b_remote = remote_path.read_bytes()
    except OSError:
        return False
    if b_local == b_remote:
        return True
    if local_path.suffix.lower() in TEXT_NORMALIZE_EXTS:
        if b_local.replace(b"\r\n", b"\n") == b_remote.replace(b"\r\n", b"\n"):
            return True
    return False


def stage_update_from_zip(
    zip_url: str,
    repo: str,
    target_version: str,
    project_root: Path,
    extra_protected_roots: tuple[str, ...] = (),
    progress_cb: Optional[Callable[[int, int], None]] = None,
    cancel_event: Optional[threading.Event] = None,
    timeout: float = 30.0,
) -> StagedUpdatePlan:
    """Download remote GitHub ZIP archive, extract safely into staging, and diff files."""
    if not zip_url or not zip_url.lower().startswith(("https://", "http://")):
        raise UpdateError("upd_err_bad_url")

    staging_root = Path(tempfile.mkdtemp(prefix="l4d2sw_update_"))
    archive_path = staging_root / "update.zip"
    extract_dir = staging_root / "extracted"

    try:
        req = urllib.request.Request(
            zip_url,
            headers={"User-Agent": "L4D2SurvivorSwapper/2.0"},
            method="GET",
        )
        with urllib.request.urlopen(req, timeout=timeout) as resp:
            total = int(resp.headers.get("Content-Length") or 0)
            done = 0
            with archive_path.open("wb") as fh:
                while True:
                    if cancel_event is not None and cancel_event.is_set():
                        raise UpdateError("upd_err_cancelled")
                    chunk = resp.read(128 * 1024)
                    if not chunk:
                        break
                    fh.write(chunk)
                    done += len(chunk)
                    if progress_cb is not None:
                        progress_cb(done, total)

        extract_dir.mkdir(parents=True, exist_ok=True)
        extract_root = extract_dir.resolve()
        with zipfile.ZipFile(archive_path, "r") as zf:
            for info in zf.infolist():
                if cancel_event is not None and cancel_event.is_set():
                    raise UpdateError("upd_err_cancelled")
                if info.is_dir():
                    continue
                rel = info.filename.replace("\\", "/").lstrip("/")
                target = (extract_root / rel).resolve()
                if not target.is_relative_to(extract_root):
                    raise UpdateError("upd_err_unsafe_zip")
                target.parent.mkdir(parents=True, exist_ok=True)
                with zf.open(info, "r") as src, target.open("wb") as dst:
                    shutil.copyfileobj(src, dst)
        archive_path.unlink(missing_ok=True)

        top_entries = [p for p in extract_root.iterdir()]
        if len(top_entries) == 1 and top_entries[0].is_dir():
            payload_dir = top_entries[0]
        else:
            payload_dir = extract_root

        return build_staged_plan_from_dir(
            repo=repo,
            target_version=target_version,
            staging_root=staging_root,
            payload_dir=payload_dir,
            project_root=project_root,
            extra_protected_roots=extra_protected_roots,
        )
    except UpdateError:
        shutil.rmtree(staging_root, ignore_errors=True)
        raise
    except urllib.error.HTTPError as exc:
        shutil.rmtree(staging_root, ignore_errors=True)
        raise UpdateError("upd_err_http", status=exc.code) from exc
    except (urllib.error.URLError, TimeoutError, zipfile.BadZipFile, OSError) as exc:
        shutil.rmtree(staging_root, ignore_errors=True)
        raise UpdateError("upd_err_network", reason=str(exc)) from exc


def build_staged_plan_from_dir(
    repo: str,
    target_version: str,
    staging_root: Path,
    payload_dir: Path,
    project_root: Path,
    extra_protected_roots: tuple[str, ...] = (),
) -> StagedUpdatePlan:
    """Compare an extracted update payload folder against project_root cleanly."""
    remote_files: dict[str, Path] = {}
    for item in payload_dir.rglob("*"):
        if not item.is_file():
            continue
        rel = item.relative_to(payload_dir).as_posix()
        if is_protected_rel_path(rel, extra_protected_roots):
            continue
        remote_files[rel] = item

    changes: list[UpdateFileChange] = []
    requirements_changed = False
    for rel in sorted(remote_files):
        remote_path = remote_files[rel]
        local_path = project_root / rel
        size = remote_path.stat().st_size
        if not local_path.exists():
            changes.append(UpdateFileChange(rel_path=rel, change_type="added", size_bytes=size))
            if rel.lower() == "requirements.txt":
                requirements_changed = True
        elif not _bytes_match(local_path, remote_path):
            changes.append(UpdateFileChange(rel_path=rel, change_type="modified", size_bytes=size))
            if rel.lower() == "requirements.txt":
                requirements_changed = True

    local_tracked = _list_local_tracked_files(project_root, extra_protected_roots)
    for rel in sorted(local_tracked):
        if rel not in remote_files:
            changes.append(UpdateFileChange(rel_path=rel, change_type="removed", size_bytes=0))

    return StagedUpdatePlan(
        repo=repo,
        target_version=target_version,
        staging_root=staging_root,
        payload_dir=payload_dir,
        changes=changes,
        remote_manifest_paths=sorted(remote_files.keys()),
        requirements_changed=requirements_changed,
    )


def apply_staged_update(
    plan: StagedUpdatePlan,
    project_root: Path,
    install_requirements: bool = True,
    keep_backup: bool = True,
) -> UpdateApplyResult:
    """Apply staged added/modified/removed files with rollback safety and manifest update."""
    logs: list[str] = []
    backup_dir: Optional[Path] = None
    if keep_backup:
        backup_dir = project_root / f"_l4d2sw_update_backup_{plan.target_version}"
        if backup_dir.exists():
            shutil.rmtree(backup_dir, ignore_errors=True)
        backup_dir.mkdir(parents=True, exist_ok=True)

    applied_count = 0
    removed_count = 0
    deferred_ops: list[tuple[str, str]] = []

    for ch in plan.changes:
        dest_file = project_root / ch.rel_path
        if ch.change_type in ("added", "modified"):
            src_file = plan.payload_dir / ch.rel_path
            if backup_dir is not None and dest_file.exists():
                bkp_target = backup_dir / ch.rel_path
                bkp_target.parent.mkdir(parents=True, exist_ok=True)
                try:
                    shutil.copy2(dest_file, bkp_target)
                except OSError:
                    pass
            try:
                dest_file.parent.mkdir(parents=True, exist_ok=True)
                tmp_target = dest_file.with_name(f".{dest_file.name}.upd_tmp")
                shutil.copy2(src_file, tmp_target)
                os.replace(tmp_target, dest_file)
                applied_count += 1
            except OSError as exc:
                tmp_target = dest_file.with_name(f".{dest_file.name}.upd_tmp")
                tmp_target.unlink(missing_ok=True)
                deferred_ops.append(("copy", ch.rel_path))
                logs.append(f"Deferred locked file {ch.rel_path}: {exc}")
        elif ch.change_type == "removed":
            if dest_file.exists():
                if backup_dir is not None:
                    bkp_target = backup_dir / ch.rel_path
                    bkp_target.parent.mkdir(parents=True, exist_ok=True)
                    try:
                        shutil.copy2(dest_file, bkp_target)
                    except OSError:
                        pass
                try:
                    dest_file.unlink()
                    removed_count += 1
                    _prune_empty_parents(dest_file.parent, project_root)
                except OSError as exc:
                    deferred_ops.append(("remove", ch.rel_path))
                    logs.append(f"Deferred locked removal {ch.rel_path}: {exc}")

    _save_update_manifest(project_root, plan.remote_manifest_paths, plan.target_version)

    req_updated = False
    req_file = project_root / "requirements.txt"
    if install_requirements and plan.requirements_changed and req_file.is_file():
        creationflags = getattr(subprocess, "CREATE_NO_WINDOW", 0)
        proc = subprocess.run(
            [sys.executable, "-m", "pip", "install", "-r", str(req_file)],
            cwd=str(project_root),
            capture_output=True,
            text=True,
            errors="replace",
            creationflags=creationflags,
        )
        req_updated = proc.returncode == 0
        if not req_updated:
            logs.append(f"pip install failed (exit {proc.returncode}): {proc.stderr.strip()}")

    relaunch_scheduled = False
    if deferred_ops:
        _spawn_post_exit_helper(
            project_root=project_root,
            staging_root=plan.staging_root,
            payload_dir=plan.payload_dir,
            deferred_ops=deferred_ops,
            relaunch=True,
        )
        relaunch_scheduled = True
    else:
        shutil.rmtree(plan.staging_root, ignore_errors=True)

    return UpdateApplyResult(
        applied_count=applied_count,
        removed_count=removed_count,
        deferred_count=len(deferred_ops),
        requirements_updated=req_updated,
        backup_dir=backup_dir,
        relaunch_scheduled=relaunch_scheduled,
        logs=logs,
    )


def _resolve_relaunch_command(project_root: Path) -> list[str]:
    app_script = project_root / "app.py"
    if os.name == "nt":
        launcher_exe = project_root / "L4D2 Survivor Swapper Tool.exe"
        if launcher_exe.is_file() and (project_root / "runtime").is_dir():
            return [str(launcher_exe)]
        exe = Path(sys.executable)
        pythonw = exe.with_name("pythonw.exe")
        runner = str(pythonw if pythonw.is_file() else exe)
        return [runner, str(app_script)]
    return [sys.executable, str(app_script)]


def schedule_app_relaunch(project_root: Path) -> None:
    """Spawn a fresh detached instance of the application after updates."""
    cmd = _resolve_relaunch_command(project_root)
    if os.name == "nt":
        flags = getattr(subprocess, "CREATE_NEW_PROCESS_GROUP", 0) | getattr(
            subprocess, "DETACHED_PROCESS", 0
        )
        subprocess.Popen(
            cmd,
            cwd=str(project_root),
            creationflags=flags,
            close_fds=True,
        )
    else:
        subprocess.Popen(
            cmd,
            cwd=str(project_root),
            start_new_session=True,
            close_fds=True,
        )


def _prune_empty_parents(start_dir: Path, stop_root: Path) -> None:
    cur = start_dir
    stop_resolved = stop_root.resolve()
    while cur.exists() and cur.is_dir() and cur.resolve() != stop_resolved:
        try:
            next(cur.iterdir())
            break
        except StopIteration:
            try:
                cur.rmdir()
                cur = cur.parent
            except OSError:
                break
        except OSError:
            break


def _spawn_post_exit_helper(
    project_root: Path,
    staging_root: Path,
    payload_dir: Path,
    deferred_ops: list[tuple[str, str]],
    relaunch: bool = True,
) -> None:
    ops_path = staging_root / "deferred_ops.json"
    ops_path.write_text(json.dumps(deferred_ops), encoding="utf-8", newline="\n")
    helper_py = staging_root / "finish_update.py"
    relaunch_cmd = _resolve_relaunch_command(project_root) if relaunch else []
    helper_code = "\n".join(
        [
            "import json, os, shutil, subprocess, sys, time",
            "from pathlib import Path",
            f"pid = {os.getpid()}",
            f"root = Path({repr(str(project_root))})",
            f"payload = Path({repr(str(payload_dir))})",
            f"staging = Path({repr(str(staging_root))})",
            f"ops = json.loads(Path({repr(str(ops_path))}).read_text(encoding='utf-8'))",
            "time.sleep(1.2)",
            "for _ in range(10):",
            "    pending = []",
            "    for op, rel in ops:",
            "        dest = root / rel",
            "        try:",
            "            if op == 'copy':",
            "                dest.parent.mkdir(parents=True, exist_ok=True)",
            "                shutil.copy2(payload / rel, dest)",
            "            elif op == 'remove' and dest.exists():",
            "                dest.unlink()",
            "        except OSError:",
            "            pending.append((op, rel))",
            "    ops = pending",
            "    if not ops:",
            "        break",
            "    time.sleep(0.5)",
            "shutil.rmtree(staging, ignore_errors=True)",
            *(
                [
                    f"subprocess.Popen({repr(relaunch_cmd)}, cwd=str(root), close_fds=True)",
                ]
                if relaunch
                else []
            ),
        ]
    )
    helper_py.write_text(helper_code + "\n", encoding="utf-8", newline="\n")
    creationflags = getattr(subprocess, "CREATE_NO_WINDOW", 0) | getattr(
        subprocess, "DETACHED_PROCESS", 0
    )
    subprocess.Popen(
        [sys.executable, str(helper_py)],
        cwd=str(staging_root),
        creationflags=creationflags,
        close_fds=True,
    )
