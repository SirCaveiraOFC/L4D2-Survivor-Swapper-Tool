from __future__ import annotations

import html
import re
from typing import Optional


_NOPARSE_RE = re.compile(r"\[noparse\](.*?)\[/noparse\]", re.IGNORECASE | re.DOTALL)
_CODE_RE = re.compile(r"\[code\](.*?)\[/code\]", re.IGNORECASE | re.DOTALL)
_IMG_ATTR_RE = re.compile(
    r"\[img=([^\]]+)\](?:\[/img\])?", re.IGNORECASE
)
_IMG_TAG_RE = re.compile(r"\[img\](.*?)\[/img\]", re.IGNORECASE | re.DOTALL)
_URL_ATTR_RE = re.compile(r"\[url=([^\]]+)\](.*?)\[/url\]", re.IGNORECASE | re.DOTALL)
_URL_SELF_RE = re.compile(r"\[url\](.*?)\[/url\]", re.IGNORECASE | re.DOTALL)
_H_TAG_RE = re.compile(r"\[(h[1-3])\](.*?)\[/\1\]", re.IGNORECASE | re.DOTALL)
_HR_RE = re.compile(r"\[hr\s*/?\](?:\[/hr\])?", re.IGNORECASE)
_LIST_RE = re.compile(r"\[(olist|list)\](.*?)\[/\1\]", re.IGNORECASE | re.DOTALL)
_QUOTE_RE = re.compile(r"\[quote(?:=([^\]]+))?\](.*?)\[/quote\]", re.IGNORECASE | re.DOTALL)
_TABLE_RE = re.compile(r"\[table([^\]]*)\](.*?)\[/table\]", re.IGNORECASE | re.DOTALL)
_TR_RE = re.compile(r"\[tr\](.*?)\[/tr\]", re.IGNORECASE | re.DOTALL)
_CELL_RE = re.compile(r"\[(th|td)\](.*?)\[/\1\]", re.IGNORECASE | re.DOTALL)
_INLINE_TAG_RE = re.compile(
    r"\[(b|u|i|strike|spoiler)\](.*?)\[/\1\]", re.IGNORECASE | re.DOTALL
)
_KNOWN_STRIP_RE = re.compile(
    r"\[/?(?:h[1-3]|b|u|i|strike|spoiler|noparse|hr|url|img|list|olist|\*|quote|code|table|tr|th|td)(?:=[^\]]*)?\]",
    re.IGNORECASE,
)
_BARE_URL_RE = re.compile(r"(https?://[^\s<>\[\]\"']+)")
_YT_ID_RE = re.compile(r"(?:youtube\.com/watch\?[^\s]*v=|youtu\.be/)([A-Za-z0-9_-]{6,})")
_STORE_APP_RE = re.compile(r"store\.steampowered\.com/app/(\d+)", re.IGNORECASE)
_WORKSHOP_ITEM_RE = re.compile(
    r"steamcommunity\.com/(?:sharedfiles|workshop)/filedetails/\?[^\s]*id=(\d+)",
    re.IGNORECASE,
)


def _normalize_url(raw_url: str) -> str:
    cleaned = html.unescape(raw_url or "").strip()
    if not cleaned:
        return ""
    if not re.match(r"^[a-zA-Z][a-zA-Z0-9+.-]*://", cleaned):
        if cleaned.startswith("//"):
            return f"https:{cleaned}"
        return f"https://{cleaned}"
    return cleaned


def extract_steam_summary(raw_bbcode: str, title: str = "", max_len: int = 180) -> str:
    """Build a readable 1-to-2 line summary from Steam Workshop BBCode without ugly broken headings."""
    if not raw_bbcode:
        return ""
    cleaned = _IMG_ATTR_RE.sub(" ", raw_bbcode)
    cleaned = _IMG_TAG_RE.sub(" ", cleaned)
    cleaned = _HR_RE.sub(" ", cleaned)
    cleaned = _KNOWN_STRIP_RE.sub(" ", cleaned)
    lines = [re.sub(r"\s+", " ", ln).strip() for ln in cleaned.replace("\r\n", "\n").split("\n")]
    filtered: list[str] = []
    title_low = (title or "").strip().lower()
    for ln in lines:
        if not ln:
            continue
        low = ln.lower()
        if title_low and (low == title_low or low == f"name: {title_low}" or low == f"nome: {title_low}"):
            continue
        if low.startswith("description:"):
            ln = ln[len("description:") :].strip()
        elif low.startswith("descrição:"):
            ln = ln[len("descrição:") :].strip()
        if ln:
            filtered.append(ln)
    joined = " · ".join(filtered[:3])
    joined = re.sub(r"\s+", " ", joined).strip()
    if len(joined) > max_len:
        return f"{joined[: max_len - 1].rstrip()}…"
    return joined


def steam_bbcode_to_html(
    raw_bbcode: str,
    is_dark: bool = True,
    original_author_label: str = "Originally posted by",
    loaded_images: Optional[set[str]] = None,
) -> tuple[str, list[str]]:
    """Convert documented Steam BBCode tags into clean styled HTML and collect unique image URLs."""
    if not raw_bbcode:
        return "", []

    text_fg = "#EAEFF5" if is_dark else "#181C22"
    muted_fg = "#9AA4B2" if is_dark else "#5E6673"
    heading_fg = "#66C0F4" if is_dark else "#1B5E91"
    link_fg = "#66C0F4" if is_dark else "#0B66C3"
    card_bg = "#1D222C" if is_dark else "#EFECE5"
    card_alt = "#252B37" if is_dark else "#E5E0D5"
    border_fg = "#363E4F" if is_dark else "#C8C0B0"
    accent_bar = "#D93838" if is_dark else "#B82828"
    spoiler_bg = "#2C3340" if is_dark else "#DFD9CC"

    tokens: dict[str, str] = {}
    token_idx = 0
    image_urls: list[str] = []
    seen_imgs: set[str] = set()

    def stash(fragment: str) -> str:
        nonlocal token_idx
        key = f"\ue000TOK{token_idx}\ue001"
        token_idx += 1
        tokens[key] = fragment
        return key

    work = (raw_bbcode or "").replace("\r\n", "\n").replace("\r", "\n")

    def on_noparse(m: re.Match[str]) -> str:
        return stash(html.escape(m.group(1), quote=True))

    work = _NOPARSE_RE.sub(on_noparse, work)

    def on_code(m: re.Match[str]) -> str:
        inner = m.group(1).strip("\n")
        escaped = html.escape(inner, quote=True)
        return stash(
            f'<pre style="font-family: Consolas, \'Courier New\', monospace; font-size: 12px; '
            f'background-color: {card_bg}; color: {text_fg}; border: 1px solid {border_fg}; '
            f'border-radius: 6px; padding: 10px 12px; margin: 8px 0;">{escaped}</pre>'
        )

    work = _CODE_RE.sub(on_code, work)

    raw_chunks = re.split(r"(\ue000TOK\d+\ue001)", work)
    escaped_parts: list[str] = []
    for chunk in raw_chunks:
        if chunk.startswith("\ue000TOK") and chunk.endswith("\ue001"):
            escaped_parts.append(chunk)
        else:
            escaped_parts.append(html.escape(chunk, quote=True))
    work = "".join(escaped_parts)

    def on_img_url(raw_src: str) -> str:
        url = _normalize_url(raw_src)
        if not url.lower().startswith(("https://", "http://")):
            return html.escape(raw_src, quote=True)
        if url not in seen_imgs:
            seen_imgs.add(url)
            image_urls.append(url)
        safe_url = html.escape(url, quote=True)
        if loaded_images is not None and url in loaded_images:
            return stash(
                f'<div style="margin: 8px 0;"><a href="{safe_url}" style="color: {link_fg}; text-decoration: none;">'
                f'<img src="{safe_url}"></a></div>'
            )
        return stash(
            f'<div style="margin: 6px 0; padding: 5px 10px; background-color: {card_bg}; '
            f'border: 1px solid {border_fg}; border-radius: 4px;">'
            f'<a href="{safe_url}" style="color: {link_fg}; text-decoration: none;">'
            f'[Image] {safe_url}</a></div>'
        )

    work = _IMG_ATTR_RE.sub(lambda m: on_img_url(m.group(1)), work)
    work = _IMG_TAG_RE.sub(lambda m: on_img_url(m.group(1)), work)

    def wrap_url(target_raw: str, label_raw: str) -> str:
        url = _normalize_url(target_raw)
        if not url:
            return label_raw
        safe_url = html.escape(url, quote=True)
        open_tok = stash(f'<a href="{safe_url}" style="color: {link_fg}; text-decoration: underline;">')
        close_tok = stash("</a>")
        return f"{open_tok}{label_raw}{close_tok}"

    work = _URL_ATTR_RE.sub(lambda m: wrap_url(m.group(1), m.group(2)), work)
    work = _URL_SELF_RE.sub(lambda m: wrap_url(m.group(1), m.group(1)), work)

    def on_bare_url(m: re.Match[str]) -> str:
        raw_url = m.group(1)
        trailing = ""
        while raw_url and raw_url[-1] in ".,);:!?":
            trailing = raw_url[-1] + trailing
            raw_url = raw_url[:-1]
        unescaped = html.unescape(raw_url)
        safe_href = html.escape(unescaped, quote=True)
        yt_m = _YT_ID_RE.search(unescaped)
        if yt_m:
            return stash(
                f'<div style="margin: 6px 0; padding: 6px 10px; background-color: {card_bg}; '
                f'border: 1px solid {border_fg}; border-left: 3px solid {accent_bar}; border-radius: 4px;">'
                f'<a href="{safe_href}" style="color: {link_fg}; font-weight: 600; text-decoration: none;">'
                f'YouTube: {safe_href}</a></div>'
            ) + trailing
        store_m = _STORE_APP_RE.search(unescaped)
        if store_m:
            return stash(
                f'<div style="margin: 6px 0; padding: 6px 10px; background-color: {card_bg}; '
                f'border: 1px solid {border_fg}; border-left: 3px solid {heading_fg}; border-radius: 4px;">'
                f'<a href="{safe_href}" style="color: {link_fg}; font-weight: 600; text-decoration: none;">'
                f'Steam Store (App {store_m.group(1)}): {safe_href}</a></div>'
            ) + trailing
        ws_m = _WORKSHOP_ITEM_RE.search(unescaped)
        if ws_m:
            return stash(
                f'<div style="margin: 6px 0; padding: 6px 10px; background-color: {card_bg}; '
                f'border: 1px solid {border_fg}; border-left: 3px solid {heading_fg}; border-radius: 4px;">'
                f'<a href="{safe_href}" style="color: {link_fg}; font-weight: 600; text-decoration: none;">'
                f'Steam Workshop (ID {ws_m.group(1)}): {safe_href}</a></div>'
            ) + trailing
        return stash(f'<a href="{safe_href}" style="color: {link_fg};">{safe_href}</a>') + trailing

    work = _BARE_URL_RE.sub(on_bare_url, work)

    def on_list(m: re.Match[str]) -> str:
        kind = m.group(1).lower()
        tag = "ol" if kind == "olist" else "ul"
        body = m.group(2).strip()
        raw_items = re.split(r"\[\*\]", body)
        items_html: list[str] = []
        for entry in raw_items:
            cleaned_entry = entry.strip()
            if cleaned_entry:
                items_html.append(f'<li style="margin: 3px 0;">{cleaned_entry}</li>')
        if not items_html:
            return body
        return f'<{tag} style="margin: 6px 0 8px 18px; padding-left: 6px;">' + "".join(items_html) + f"</{tag}>"

    for _ in range(4):
        updated = _LIST_RE.sub(on_list, work)
        if updated == work:
            break
        work = updated

    def on_table(m: re.Match[str]) -> str:
        attrs = (m.group(1) or "").lower()
        body = m.group(2)
        noborder = "noborder=1" in attrs
        equalcells = "equalcells=1" in attrs
        tbl_width = ' width="100%"' if equalcells else ""
        cell_border = "none" if noborder else f"1px solid {border_fg}"

        rows_out: list[str] = []
        for tr_m in _TR_RE.finditer(body):
            tr_inner = tr_m.group(1)
            cells: list[str] = []
            for cell_m in _CELL_RE.finditer(tr_inner):
                ctype = cell_m.group(1).lower()
                cbody = cell_m.group(2).strip()
                if ctype == "th":
                    cells.append(
                        f'<th style="background-color: {card_alt}; color: {text_fg}; font-weight: 700; '
                        f'text-align: left; padding: 6px 10px; border: {cell_border};">{cbody}</th>'
                    )
                else:
                    cells.append(
                        f'<td style="padding: 5px 10px; border: {cell_border}; color: {text_fg};">'
                        f"{cbody}</td>"
                    )
            if cells:
                rows_out.append(f"<tr>{''.join(cells)}</tr>")
        if not rows_out:
            return body
        return (
            f'<table cellspacing="0" cellpadding="0"{tbl_width} '
            f'style="border-collapse: collapse; margin: 8px 0; background-color: {card_bg};">'
            + "".join(rows_out)
            + "</table>"
        )

    work = _TABLE_RE.sub(on_table, work)

    def on_quote(m: re.Match[str]) -> str:
        author = (m.group(1) or "").strip()
        body = m.group(2).strip()
        author_line = ""
        if author:
            author_line = (
                f'<div style="color: {muted_fg}; font-size: 12px; margin-bottom: 4px;">'
                f"{html.escape(original_author_label, quote=True)} <b>{author}</b>:</div>"
            )
        return (
            f'<blockquote style="margin: 8px 0; padding: 8px 12px; background-color: {card_bg}; '
            f'border: 1px solid {border_fg}; border-left: 3px solid {heading_fg}; border-radius: 4px;">'
            f"{author_line}{body}</blockquote>"
        )

    for _ in range(4):
        updated = _QUOTE_RE.sub(on_quote, work)
        if updated == work:
            break
        work = updated

    def on_heading(m: re.Match[str]) -> str:
        tag = m.group(1).lower()
        sizes = {"h1": "17px", "h2": "15px", "h3": "13px"}
        top_m = {"h1": "10px", "h2": "8px", "h3": "6px"}
        return (
            f'<{tag} style="color: {heading_fg}; font-size: {sizes[tag]}; font-weight: 700; '
            f'margin: {top_m[tag]} 0 4px 0;">{m.group(2).strip()}</{tag}>'
        )

    work = _H_TAG_RE.sub(on_heading, work)
    work = _HR_RE.sub(
        f'<hr style="border: none; border-top: 1px solid {border_fg}; margin: 10px 0;">',
        work,
    )

    def on_inline(m: re.Match[str]) -> str:
        tag = m.group(1).lower()
        inner = m.group(2)
        if tag == "b":
            return f"<b>{inner}</b>"
        if tag == "u":
            return f"<u>{inner}</u>"
        if tag == "i":
            return f"<i>{inner}</i>"
        if tag == "strike":
            return f"<s>{inner}</s>"
        return (
            f'<span style="background-color: {spoiler_bg}; color: {text_fg}; '
            f'border: 1px dashed {border_fg}; border-radius: 3px; padding: 1px 5px;">'
            f"[SPOILER] {inner}</span>"
        )

    for _ in range(5):
        updated = _INLINE_TAG_RE.sub(on_inline, work)
        if updated == work:
            break
        work = updated

    work = re.sub(
        r"\s*(</?(?:h[1-3]|ul|ol|table|blockquote|pre|hr|div)[^>]*>)\s*",
        lambda m: m.group(1),
        work,
    )
    work = re.sub(r"\n{3,}", "\n\n", work.strip())
    work = work.replace("\n", "<br>\n")

    for _ in range(3):
        replaced_any = False
        for key, val in tokens.items():
            if key in work:
                work = work.replace(key, val)
                replaced_any = True
        if not replaced_any:
            break

    full_html = (
        f'<div style="color: {text_fg}; font-size: 13px; line-height: 1.48;">'
        f"{work}</div>"
    )
    return full_html, image_urls
