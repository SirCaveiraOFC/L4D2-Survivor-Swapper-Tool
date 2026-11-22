from __future__ import annotations

from dataclasses import dataclass, replace
from datetime import datetime
import html
import json
from pathlib import Path, PurePosixPath
import re
import threading
from typing import Any, Callable, Optional
import urllib.error
import urllib.parse
import urllib.request


L4D2_APP_ID = 550
STEAM_DETAILS_API_URL = (
    "https://api.steampowered.com/ISteamRemoteStorage/GetPublishedFileDetails/v0001/"
)
STEAM_WORKSHOP_ITEM_URL = "https://steamcommunity.com/sharedfiles/filedetails/?id={item_id}"
VPK_MAGIC = b"\x34\x12\xaa\x55"

_URL_ID_RE = re.compile(r"[?&]id=(\d{5,15})\b", re.IGNORECASE)
_STEAM_URI_RE = re.compile(r"CommunityFilePage/(\d{5,15})\b", re.IGNORECASE)
_RAW_ID_RE = re.compile(r"^\d{5,15}$")
_SAFE_NAME_RE = re.compile(r'[<>:"/\\|?*\x00-\x1f]+')
_STAR_RATING_RE = re.compile(r"/([0-5])-star_large\.png", re.IGNORECASE)
_NOT_YET_RATED_RE = re.compile(r"/not-yet\.png", re.IGNORECASE)
_NUM_RATINGS_RE = re.compile(r'<div[^>]*class="numRatings"[^>]*>([^<]+)</div>', re.IGNORECASE)
_CREATOR_NAME_RE = re.compile(r'class="friendBlockContent">\s*([^<\r\n]+)', re.IGNORECASE)
_STATS_ROW_RE = re.compile(
    r"<tr>\s*<td[^>]*>([\d,\.\s]+)</td>\s*<td[^>]*>([^<]+)</td>\s*</tr>",
    re.IGNORECASE,
)


class WorkshopError(RuntimeError):
    """Localized error carrying an i18n message key and formatting parameters."""

    def __init__(self, key: str, **kwargs: Any) -> None:
        super().__init__(key)
        self.key = key
        self.kwargs = kwargs


@dataclass(frozen=True)
class WorkshopItemDetails:
    """Metadata returned by Steam Web API GetPublishedFileDetails for one Workshop item."""

    published_file_id: str
    result: int
    consumer_app_id: int
    title: str
    description: str
    filename: str
    file_size: int
    time_updated: int
    file_url: str
    preview_url: str
    tags: tuple[str, ...]
    creator_steam_id: str = ""
    time_created: int = 0
    subscriptions: int = 0
    lifetime_subscriptions: int = 0
    favorited: int = 0
    lifetime_favorited: int = 0
    views: int = 0
    rating_stars: Optional[int] = None
    num_ratings: int = 0
    creator_name: str = ""

    @property
    def workshop_url(self) -> str:
        return STEAM_WORKSHOP_ITEM_URL.format(item_id=self.published_file_id)

    @property
    def has_direct_url(self) -> bool:
        return bool(self.file_url.strip())


@dataclass(frozen=True)
class WorkshopDownloadResult:
    """Result returned after resolving or downloading one Workshop VPK."""

    details: WorkshopItemDetails
    vpk_path: Path
    preview_bytes: Optional[bytes] = None
    from_local_workshop: bool = False
    already_cached: bool = False


def extract_workshop_item_ids(raw_text: str) -> list[str]:
    """Extract ordered unique numeric Steam Workshop IDs from URLs or plain ID strings."""
    found: list[str] = []
    seen: set[str] = set()
    for token in re.split(r"[\s,;]+", raw_text or ""):
        part = token.strip()
        if not part:
            continue
        item_id: Optional[str] = None
        match = _URL_ID_RE.search(part) or _STEAM_URI_RE.search(part)
        if match:
            item_id = match.group(1)
        elif _RAW_ID_RE.match(part):
            item_id = part
        if item_id and item_id not in seen:
            seen.add(item_id)
            found.append(item_id)
    return found


def extract_workshop_item_id(raw_text: str) -> str:
    """Extract a single Steam Workshop ID from URL/ID input or raise WorkshopError."""
    ids = extract_workshop_item_ids(raw_text)
    if not ids:
        raise WorkshopError("dl_err_invalid_id")
    return ids[0]


def build_safe_vpk_filename(item_id: str, remote_filename: str, title: str = "") -> str:
    """Construct a collision-free, sanitized '.vpk' filename preserving original mod hints."""
    leaf = PurePosixPath((remote_filename or "").replace("\\", "/")).name
    if not leaf:
        leaf = f"{title or item_id}.vpk"
    stem = Path(leaf).stem
    stem = _SAFE_NAME_RE.sub("_", stem).strip(" ._")
    stem = re.sub(r"\s+", " ", stem)
    if not stem or stem == item_id:
        return f"{item_id}.vpk"
    stem = stem[:96].rstrip(" ._")
    if stem.startswith(f"{item_id}_") or stem.endswith(f"_{item_id}"):
        return f"{stem}.vpk"
    return f"{item_id}_{stem}.vpk"


def format_bytes(size_bytes: int) -> str:
    """Format byte counts concisely as B, KB, MB, or GB."""
    size = max(0, int(size_bytes))
    if size < 1024:
        return f"{size} B"
    if size < 1024 * 1024:
        return f"{size / 1024.0:.1f} KB"
    if size < 1024 * 1024 * 1024:
        return f"{size / (1024.0 * 1024.0):.1f} MB"
    return f"{size / (1024.0 * 1024.0 * 1024.0):.2f} GB"


def format_timestamp(epoch: int, language: str = "en-US") -> str:
    """Format a Unix epoch timestamp cleanly according to UI language conventions."""
    if epoch <= 0:
        return "-"
    lower = (language or "en-US").strip().lower().replace("_", "-")
    fmt = "%d/%m/%Y %H:%M" if lower.startswith(("pt", "es")) else "%Y-%m-%d %H:%M"
    try:
        return datetime.fromtimestamp(int(epoch)).strftime(fmt)
    except (OSError, OverflowError, ValueError):
        return "-"


def parse_published_file_details(payload: dict[str, Any]) -> list[WorkshopItemDetails]:
    """Parse Steam Web API GetPublishedFileDetails JSON payload into WorkshopItemDetails."""
    resp = payload.get("response") or {}
    raw_items = resp.get("publishedfiledetails")
    if not isinstance(raw_items, list):
        raise WorkshopError("dl_err_bad_response")

    parsed: list[WorkshopItemDetails] = []
    for entry in raw_items:
        if not isinstance(entry, dict):
            continue
        item_id = str(entry.get("publishedfileid") or "").strip()
        result_code = int(entry.get("result") or 0)
        app_id = int(entry.get("consumer_app_id") or 0)
        if result_code != 1:
            raise WorkshopError("dl_err_not_found", item_id=item_id or "?")
        if app_id != L4D2_APP_ID:
            raise WorkshopError(
                "dl_err_wrong_app",
                item_id=item_id or "?",
                app_id=app_id,
            )

        raw_tags = entry.get("tags") or []
        tags = tuple(
            str(tag.get("tag")).strip()
            for tag in raw_tags
            if isinstance(tag, dict) and str(tag.get("tag") or "").strip()
        )
        parsed.append(
            WorkshopItemDetails(
                published_file_id=item_id,
                result=result_code,
                consumer_app_id=app_id,
                title=str(entry.get("title") or item_id).strip(),
                description=str(entry.get("description") or "").strip(),
                filename=str(entry.get("filename") or "").strip(),
                file_size=int(entry.get("file_size") or 0),
                time_updated=int(entry.get("time_updated") or 0),
                file_url=str(entry.get("file_url") or "").strip(),
                preview_url=str(entry.get("preview_url") or "").strip(),
                tags=tags,
                creator_steam_id=str(entry.get("creator") or "").strip(),
                time_created=int(entry.get("time_created") or 0),
                subscriptions=int(entry.get("subscriptions") or 0),
                lifetime_subscriptions=int(entry.get("lifetime_subscriptions") or 0),
                favorited=int(entry.get("favorited") or 0),
                lifetime_favorited=int(entry.get("lifetime_favorited") or 0),
                views=int(entry.get("views") or 0),
            )
        )
    if not parsed:
        raise WorkshopError("dl_err_bad_response")
    return parsed


def format_count(value: int, sep: str = ",") -> str:
    """Format non-negative integers with localized thousands grouping."""
    return f"{max(0, int(value)):,}".replace(",", sep)


def _parse_int_digits(raw: str) -> int:
    digits = re.sub(r"[^\d]", "", raw or "")
    return int(digits) if digits else 0


def parse_workshop_web_stats(html_text: str) -> dict[str, Any]:
    """Extract star score, ratings count, creator personas, and stats table fallbacks from Steam HTML."""
    result: dict[str, Any] = {
        "rating_stars": None,
        "num_ratings": 0,
        "creator_name": "",
        "views": 0,
        "subscriptions": 0,
        "favorited": 0,
    }
    if not html_text:
        return result

    star_match = _STAR_RATING_RE.search(html_text)
    if star_match:
        result["rating_stars"] = int(star_match.group(1))
    elif _NOT_YET_RATED_RE.search(html_text):
        result["rating_stars"] = 0

    num_match = _NUM_RATINGS_RE.search(html_text)
    if num_match:
        result["num_ratings"] = _parse_int_digits(num_match.group(1))

    sidebar_part = html_text.split('id="commentthread', 1)[0]
    creators: list[str] = []
    for match in _CREATOR_NAME_RE.finditer(sidebar_part):
        name = html.unescape(match.group(1)).strip()
        if name and name not in creators:
            creators.append(name)
        if len(creators) >= 6:
            break
    if creators:
        result["creator_name"] = ", ".join(creators)

    for num_str, label in _STATS_ROW_RE.findall(sidebar_part):
        val = _parse_int_digits(num_str)
        low = label.lower()
        if "visitor" in low or "visitante" in low:
            result["views"] = val
        elif "subscriber" in low or "inscrito" in low or "suscriptor" in low:
            result["subscriptions"] = val
        elif "favorite" in low or "favorito" in low:
            result["favorited"] = val

    return result


def fetch_workshop_web_stats(item_id: str, timeout: float = 10.0) -> dict[str, Any]:
    """Fetch public Steam Workshop HTML page cleanly to obtain star rating and author names."""
    url = STEAM_WORKSHOP_ITEM_URL.format(item_id=item_id)
    req = urllib.request.Request(
        url,
        headers={
            "User-Agent": "L4D2SurvivorSwapper/2.0",
            "Accept-Language": "en-US,en;q=0.9",
        },
        method="GET",
    )
    try:
        with urllib.request.urlopen(req, timeout=timeout) as resp:
            raw = resp.read(2 * 1024 * 1024).decode("utf-8", errors="replace")
        return parse_workshop_web_stats(raw)
    except Exception:
        return {}


def enrich_item_from_web(details: WorkshopItemDetails, timeout: float = 10.0) -> WorkshopItemDetails:
    """Enrich API details with star rating and Steam persona names scraped safely from public HTML."""
    web_stats = fetch_workshop_web_stats(details.published_file_id, timeout=timeout)
    if not web_stats:
        return details
    return replace(
        details,
        rating_stars=(
            web_stats["rating_stars"]
            if web_stats.get("rating_stars") is not None
            else details.rating_stars
        ),
        num_ratings=int(web_stats.get("num_ratings") or details.num_ratings),
        creator_name=str(web_stats.get("creator_name") or details.creator_name),
        views=details.views or int(web_stats.get("views") or 0),
        subscriptions=details.subscriptions or int(web_stats.get("subscriptions") or 0),
        favorited=details.favorited or int(web_stats.get("favorited") or 0),
    )


def fetch_items_details(item_ids: list[str], timeout: float = 15.0) -> list[WorkshopItemDetails]:
    """Query Steam Web API GetPublishedFileDetails for one or more L4D2 Workshop item IDs."""
    if not item_ids:
        raise WorkshopError("dl_err_invalid_id")
    post_fields: dict[str, Any] = {"itemcount": len(item_ids)}
    for idx, wid in enumerate(item_ids):
        post_fields[f"publishedfileids[{idx}]"] = wid
    body = urllib.parse.urlencode(post_fields).encode("utf-8")
    req = urllib.request.Request(
        STEAM_DETAILS_API_URL,
        data=body,
        headers={
            "Content-Type": "application/x-www-form-urlencoded",
            "User-Agent": "L4D2SurvivorSwapper/2.0",
        },
        method="POST",
    )
    try:
        with urllib.request.urlopen(req, timeout=timeout) as resp:
            raw = resp.read().decode("utf-8", errors="replace")
        payload = json.loads(raw)
    except WorkshopError:
        raise
    except urllib.error.HTTPError as exc:
        raise WorkshopError("dl_err_http", status=exc.code) from exc
    except (urllib.error.URLError, TimeoutError, json.JSONDecodeError, OSError) as exc:
        raise WorkshopError("dl_err_network", reason=str(exc)) from exc
    return parse_published_file_details(payload)


def fetch_preview_bytes(preview_url: str, timeout: float = 10.0) -> Optional[bytes]:
    """Download a Steam Workshop thumbnail image into memory, returning None on non-fatal failure."""
    cleaned = (preview_url or "").strip()
    if not cleaned.lower().startswith(("https://", "http://")):
        return None
    req = urllib.request.Request(
        cleaned,
        headers={"User-Agent": "L4D2SurvivorSwapper/2.0"},
        method="GET",
    )
    try:
        with urllib.request.urlopen(req, timeout=timeout) as resp:
            data = resp.read(8 * 1024 * 1024)
            return data if data else None
    except Exception:
        return None


def is_valid_vpk_file(path: Path) -> bool:
    """Verify whether path exists and begins with the Valve VPK signature."""
    if not path.is_file():
        return False
    try:
        with path.open("rb") as fh:
            return fh.read(4) == VPK_MAGIC
    except OSError:
        return False


def download_vpk(
    details: WorkshopItemDetails,
    target_dir: Path,
    addons_dir: Optional[Path] = None,
    progress_cb: Optional[Callable[[int, int], None]] = None,
    cancel_event: Optional[threading.Event] = None,
    overwrite: bool = False,
    preview_bytes: Optional[bytes] = None,
    timeout: float = 30.0,
) -> WorkshopDownloadResult:
    """Download a Workshop VPK via Steam CDN GET streaming or fall back to local Workshop cache."""
    resolved_preview = (
        preview_bytes
        if preview_bytes is not None
        else fetch_preview_bytes(details.preview_url)
    )

    if not details.has_direct_url:
        if addons_dir is not None:
            local_vpk = addons_dir / "workshop" / f"{details.published_file_id}.vpk"
            if is_valid_vpk_file(local_vpk):
                return WorkshopDownloadResult(
                    details=details,
                    vpk_path=local_vpk,
                    preview_bytes=resolved_preview,
                    from_local_workshop=True,
                )
        raise WorkshopError("dl_err_no_file_url", item_id=details.published_file_id)

    if not details.file_url.lower().startswith(("https://", "http://")):
        raise WorkshopError("dl_err_bad_url", item_id=details.published_file_id)

    target_dir.mkdir(parents=True, exist_ok=True)
    dest_name = build_safe_vpk_filename(
        details.published_file_id,
        details.filename,
        details.title,
    )
    dest_path = target_dir / dest_name

    if not overwrite and is_valid_vpk_file(dest_path):
        expected = details.file_size
        if expected <= 0 or dest_path.stat().st_size == expected:
            if progress_cb is not None:
                size_now = dest_path.stat().st_size
                progress_cb(size_now, size_now)
            return WorkshopDownloadResult(
                details=details,
                vpk_path=dest_path,
                preview_bytes=resolved_preview,
                already_cached=True,
            )

    part_path = dest_path.with_name(f"{dest_path.name}.part")
    req = urllib.request.Request(
        details.file_url,
        headers={"User-Agent": "L4D2SurvivorSwapper/2.0"},
        method="GET",
    )

    downloaded = 0
    try:
        with urllib.request.urlopen(req, timeout=timeout) as resp:
            content_len_hdr = resp.headers.get("Content-Length")
            total_bytes = (
                int(content_len_hdr)
                if content_len_hdr and content_len_hdr.isdigit()
                else max(0, details.file_size)
            )
            with part_path.open("wb") as out_fh:
                while True:
                    if cancel_event is not None and cancel_event.is_set():
                        raise WorkshopError("dl_err_cancelled")
                    chunk = resp.read(65536)
                    if not chunk:
                        break
                    out_fh.write(chunk)
                    downloaded += len(chunk)
                    if progress_cb is not None:
                        progress_cb(downloaded, total_bytes)
        if not is_valid_vpk_file(part_path):
            raise WorkshopError("dl_err_not_vpk", item_id=details.published_file_id)
        part_path.replace(dest_path)
    except WorkshopError:
        part_path.unlink(missing_ok=True)
        raise
    except urllib.error.HTTPError as exc:
        part_path.unlink(missing_ok=True)
        raise WorkshopError("dl_err_http", status=exc.code) from exc
    except (urllib.error.URLError, TimeoutError, OSError) as exc:
        part_path.unlink(missing_ok=True)
        raise WorkshopError("dl_err_network", reason=str(exc)) from exc

    return WorkshopDownloadResult(
        details=details,
        vpk_path=dest_path,
        preview_bytes=resolved_preview,
    )
