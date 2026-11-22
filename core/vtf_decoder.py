from __future__ import annotations

import re
import struct
from dataclasses import dataclass
from pathlib import Path, PurePosixPath
from typing import Optional

from core.models import SurvivorId
from core.survivors import SurvivorRegistry
from core.vpk_service import VpkService


VTF_FORMAT_NAMES: dict[int, str] = {
    0: "RGBA8888",
    1: "ABGR8888",
    2: "RGB888",
    3: "BGR888",
    4: "RGB565",
    5: "I8",
    6: "IA88",
    8: "A8",
    11: "ARGB8888",
    12: "BGRA8888",
    13: "DXT1",
    14: "DXT3",
    15: "DXT5",
    16: "BGRX8888",
    20: "DXT1 (1-bit Alpha)",
    21: "BGR565",
}


@dataclass(frozen=True)
class VtfInfo:
    """Header metadata parsed from a Valve Texture Format (.vtf) buffer."""

    version: str
    width: int
    height: int
    format_id: int
    format_name: str
    mipmap_count: int
    frames: int
    flags: int
    has_alpha: bool


@dataclass
class VguiPreviewItem:
    """Decoded VGUI texture preview and paired VMT material details."""

    slot_role: Optional[str]
    vtf_path: str
    vmt_path: str
    vmt_shader: str
    vmt_basetexture: str
    vtf_info: Optional[VtfInfo]
    width: int
    height: int
    rgba_bytes: bytes
    decode_error: str = ""


def _calc_mip_bytes(fmt: int, width: int, height: int) -> int:
    w = max(1, width)
    h = max(1, height)
    if fmt in (13, 20):
        return max(1, (w + 3) // 4) * max(1, (h + 3) // 4) * 8
    if fmt in (14, 15):
        return max(1, (w + 3) // 4) * max(1, (h + 3) // 4) * 16
    bpp = {
        0: 4,
        1: 4,
        2: 3,
        3: 3,
        4: 2,
        5: 1,
        6: 2,
        7: 1,
        8: 1,
        9: 3,
        10: 3,
        11: 4,
        12: 4,
        16: 4,
        17: 2,
        18: 2,
        19: 2,
        21: 2,
        22: 2,
        23: 4,
        24: 8,
        25: 8,
        26: 4,
    }.get(fmt, 0)
    return w * h * bpp


def _rgb565_to_rgb888(val: int) -> tuple[int, int, int]:
    r = ((val >> 11) & 0x1F) * 255 // 31
    g = ((val >> 5) & 0x3F) * 255 // 63
    b = (val & 0x1F) * 255 // 31
    return r, g, b


def _bgr565_to_rgb888(val: int) -> tuple[int, int, int]:
    b = ((val >> 11) & 0x1F) * 255 // 31
    g = ((val >> 5) & 0x3F) * 255 // 63
    r = (val & 0x1F) * 255 // 31
    return r, g, b


def _decode_dxt1_color_block(block: bytes, offset: int, allow_punchthrough: bool) -> list[tuple[int, int, int, int]]:
    c0, c1, code = struct.unpack_from("<HHI", block, offset)
    r0, g0, b0 = _rgb565_to_rgb888(c0)
    r1, g1, b1 = _rgb565_to_rgb888(c1)

    if c0 > c1 or not allow_punchthrough:
        palette = (
            (r0, g0, b0, 255),
            (r1, g1, b1, 255),
            ((2 * r0 + r1) // 3, (2 * g0 + g1) // 3, (2 * b0 + b1) // 3, 255),
            ((r0 + 2 * r1) // 3, (g0 + 2 * g1) // 3, (b0 + 2 * b1) // 3, 255),
        )
    else:
        palette = (
            (r0, g0, b0, 255),
            (r1, g1, b1, 255),
            ((r0 + r1) // 2, (g0 + g1) // 2, (b0 + b1) // 2, 255),
            (0, 0, 0, 0),
        )

    pixels: list[tuple[int, int, int, int]] = []
    for i in range(16):
        idx = (code >> (2 * i)) & 0x03
        pixels.append(palette[idx])
    return pixels


def _decode_dxt_blocks(raw: bytes, width: int, height: int, fmt: int, has_alpha_flag: bool) -> bytes:
    out = bytearray(width * height * 4)
    bx_count = max(1, (width + 3) // 4)
    by_count = max(1, (height + 3) // 4)
    block_size = 8 if fmt in (13, 20) else 16
    allow_punch = fmt == 20 or has_alpha_flag

    pos = 0
    for by in range(by_count):
        for bx in range(bx_count):
            if pos + block_size > len(raw):
                return bytes(out)

            if fmt in (13, 20):
                colors = _decode_dxt1_color_block(raw, pos, allow_punch)
                alphas = None
            elif fmt == 14:
                alpha_bits = struct.unpack_from("<Q", raw, pos)[0]
                alphas = [((alpha_bits >> (4 * i)) & 0x0F) * 17 for i in range(16)]
                colors = _decode_dxt1_color_block(raw, pos + 8, False)
            else:
                a0 = raw[pos]
                a1 = raw[pos + 1]
                bits = int.from_bytes(raw[pos + 2 : pos + 8], "little")
                if a0 > a1:
                    a_lut = (
                        a0,
                        a1,
                        (6 * a0 + a1) // 7,
                        (5 * a0 + 2 * a1) // 7,
                        (4 * a0 + 3 * a1) // 7,
                        (3 * a0 + 4 * a1) // 7,
                        (2 * a0 + 5 * a1) // 7,
                        (a0 + 6 * a1) // 7,
                    )
                else:
                    a_lut = (
                        a0,
                        a1,
                        (4 * a0 + a1) // 5,
                        (3 * a0 + 2 * a1) // 5,
                        (2 * a0 + 3 * a1) // 5,
                        (a0 + 4 * a1) // 5,
                        0,
                        255,
                    )
                alphas = [a_lut[(bits >> (3 * i)) & 0x07] for i in range(16)]
                colors = _decode_dxt1_color_block(raw, pos + 8, False)

            pos += block_size
            for py in range(4):
                ty = by * 4 + py
                if ty >= height:
                    continue
                for px in range(4):
                    tx = bx * 4 + px
                    if tx >= width:
                        continue
                    i = py * 4 + px
                    r, g, b, a = colors[i]
                    if alphas is not None:
                        a = alphas[i]
                    dst = (ty * width + tx) * 4
                    out[dst] = r
                    out[dst + 1] = g
                    out[dst + 2] = b
                    out[dst + 3] = a
    return bytes(out)


def parse_vtf_header(data: bytes) -> Optional[tuple[VtfInfo, int, int]]:
    """Parse VTF binary header and return (VtfInfo, high_res_offset, depth)."""
    if len(data) < 64 or data[:4] != b"VTF\x00":
        return None

    ver_maj, ver_min, header_size = struct.unpack_from("<III", data, 4)
    width, height, flags, frames, _first_frame = struct.unpack_from("<HHIIH", data, 16)
    high_fmt, mipmap_count, low_fmt, low_w, low_h = struct.unpack_from("<iBiBB", data, 52)
    depth = 1
    if header_size >= 65 and (ver_maj > 7 or ver_min >= 2):
        depth = max(1, struct.unpack_from("<H", data, 63)[0])

    data_offset = -1
    if (ver_maj > 7 or ver_min >= 3) and header_size >= 80 and len(data) >= 80:
        num_res = struct.unpack_from("<I", data, 76)[0]
        res_end = min(len(data), 80 + min(num_res, 64) * 8)
        for pos in range(80, res_end - 7, 8):
            if data[pos : pos + 3] == b"\x30\x00\x00":
                data_offset = struct.unpack_from("<I", data, pos + 4)[0]
                break

    if data_offset < 0:
        low_bytes = _calc_mip_bytes(low_fmt, low_w, low_h) if (low_fmt >= 0 and low_w > 0 and low_h > 0) else 0
        data_offset = header_size + low_bytes

    fmt_name = VTF_FORMAT_NAMES.get(high_fmt, f"FMT_{high_fmt}")
    has_alpha = high_fmt in (0, 1, 6, 8, 11, 12, 14, 15, 20) or bool(flags & 0x3000)
    info = VtfInfo(
        version=f"{ver_maj}.{ver_min}",
        width=width,
        height=height,
        format_id=high_fmt,
        format_name=fmt_name,
        mipmap_count=max(1, mipmap_count),
        frames=max(1, frames),
        flags=flags,
        has_alpha=has_alpha,
    )
    return info, data_offset, depth


def decode_vtf_to_rgba(data: bytes) -> tuple[Optional[VtfInfo], int, int, bytes, str]:
    """Decode frame 0 mipmap 0 of a .vtf binary buffer into tightly packed RGBA8888 bytes."""
    parsed = parse_vtf_header(data)
    if parsed is None:
        return None, 0, 0, b"", "Invalid VTF header"

    info, offset, depth = parsed
    w, h, fmt = info.width, info.height, info.format_id
    if w == 0 or h == 0:
        return info, 0, 0, b"", "Zero VTF dimensions"

    faces = 6 if (info.flags & 0x4000) else 1
    for mip in range(info.mipmap_count - 1, 0, -1):
        mw = max(1, w >> mip)
        mh = max(1, h >> mip)
        mz = max(1, depth >> mip)
        offset += _calc_mip_bytes(fmt, mw, mh) * info.frames * faces * mz

    mip0_size = _calc_mip_bytes(fmt, w, h)
    if mip0_size <= 0 or offset + mip0_size > len(data):
        return info, w, h, b"", f"Unsupported or truncated VTF format ({info.format_name})"

    raw = data[offset : offset + mip0_size]

    if fmt in (13, 14, 15, 20):
        has_alpha_flag = bool(info.flags & 0x3000)
        return info, w, h, _decode_dxt_blocks(raw, w, h, fmt, has_alpha_flag), ""

    if fmt == 0:
        return info, w, h, bytes(raw), ""

    out = bytearray(w * h * 4)
    if fmt == 12:
        for i in range(0, len(raw), 4):
            out[i] = raw[i + 2]
            out[i + 1] = raw[i + 1]
            out[i + 2] = raw[i]
            out[i + 3] = raw[i + 3]
        return info, w, h, bytes(out), ""
    if fmt == 16:
        for i in range(0, len(raw), 4):
            out[i] = raw[i + 2]
            out[i + 1] = raw[i + 1]
            out[i + 2] = raw[i]
            out[i + 3] = 255
        return info, w, h, bytes(out), ""
    if fmt == 1:
        for i in range(0, len(raw), 4):
            out[i] = raw[i + 3]
            out[i + 1] = raw[i + 2]
            out[i + 2] = raw[i + 1]
            out[i + 3] = raw[i]
        return info, w, h, bytes(out), ""
    if fmt == 11:
        for i in range(0, len(raw), 4):
            out[i] = raw[i + 1]
            out[i + 1] = raw[i + 2]
            out[i + 2] = raw[i + 3]
            out[i + 3] = raw[i]
        return info, w, h, bytes(out), ""
    if fmt == 2:
        dst = 0
        for i in range(0, len(raw), 3):
            out[dst] = raw[i]
            out[dst + 1] = raw[i + 1]
            out[dst + 2] = raw[i + 2]
            out[dst + 3] = 255
            dst += 4
        return info, w, h, bytes(out), ""
    if fmt == 3:
        dst = 0
        for i in range(0, len(raw), 3):
            out[dst] = raw[i + 2]
            out[dst + 1] = raw[i + 1]
            out[dst + 2] = raw[i]
            out[dst + 3] = 255
            dst += 4
        return info, w, h, bytes(out), ""
    if fmt in (4, 21):
        conv = _rgb565_to_rgb888 if fmt == 4 else _bgr565_to_rgb888
        for px_idx in range(w * h):
            val = struct.unpack_from("<H", raw, px_idx * 2)[0]
            r, g, b = conv(val)
            dst = px_idx * 4
            out[dst] = r
            out[dst + 1] = g
            out[dst + 2] = b
            out[dst + 3] = 255
        return info, w, h, bytes(out), ""
    if fmt == 5:
        for px_idx, v in enumerate(raw):
            dst = px_idx * 4
            out[dst] = v
            out[dst + 1] = v
            out[dst + 2] = v
            out[dst + 3] = 255
        return info, w, h, bytes(out), ""
    if fmt == 6:
        for px_idx in range(w * h):
            v = raw[px_idx * 2]
            a = raw[px_idx * 2 + 1]
            dst = px_idx * 4
            out[dst] = v
            out[dst + 1] = v
            out[dst + 2] = v
            out[dst + 3] = a
        return info, w, h, bytes(out), ""
    if fmt == 8:
        for px_idx, a in enumerate(raw):
            dst = px_idx * 4
            out[dst] = 255
            out[dst + 1] = 255
            out[dst + 2] = 255
            out[dst + 3] = a
        return info, w, h, bytes(out), ""

    return info, w, h, b"", f"Unsupported VTF format ({info.format_name})"


def parse_vmt_details(vmt_text: str) -> tuple[str, str]:
    """Extract (shader_name, $basetexture) from a Source VMT material text."""
    shader = ""
    basetex = ""
    shader_match = re.search(r'^\s*"?([A-Za-z0-9_]+)"?\s*\{?', vmt_text, re.M)
    if shader_match:
        shader = shader_match.group(1)
    tex_match = re.search(r'"?\$basetexture"?\s+"?([^"\r\n}]+)"?', vmt_text, re.I)
    if tex_match:
        basetex = tex_match.group(1).strip().replace("\\", "/")
    return shader, basetex


def extract_vgui_previews(
    source_path: Path,
    origin: Optional[SurvivorId] = None,
) -> list[VguiPreviewItem]:
    """Read and decode VGUI .vtf/.vmt files from a survivor .vpk or folder."""
    raw_files: dict[str, bytes] = {}
    orig_paths: dict[str, str] = {}

    if source_path.is_file() and source_path.suffix.lower() == ".vpk":
        try:
            with VpkService._open_vpk(source_path) as pak:
                for entry in pak:
                    norm = entry.replace("\\", "/").lstrip("./").lower()
                    if norm.startswith("materials/vgui/") and (norm.endswith(".vtf") or norm.endswith(".vmt")):
                        orig_paths[norm] = entry.replace("\\", "/")
                        raw_files[norm] = pak[entry].read()
        except Exception:
            return []
    elif source_path.is_dir():
        vgui_dir = source_path / "materials" / "vgui"
        if not vgui_dir.exists():
            return []
        for child in vgui_dir.rglob("*"):
            if child.is_file() and child.suffix.lower() in (".vtf", ".vmt"):
                rel = child.relative_to(source_path).as_posix()
                norm = rel.lower()
                orig_paths[norm] = rel
                try:
                    raw_files[norm] = child.read_bytes()
                except OSError:
                    pass

    vtf_keys = sorted(k for k in raw_files if k.endswith(".vtf"))
    slot_order = {"lobby_icon": 0, "in_game_icon": 1, "incap_icon": 2}
    items: list[VguiPreviewItem] = []
    seen_vtfs: set[str] = set()

    def build_item(vtf_norm: str, vmt_norm: str, role: Optional[str]) -> VguiPreviewItem:
        shader = ""
        basetex = ""
        if vmt_norm and vmt_norm in raw_files:
            vmt_text = raw_files[vmt_norm].decode("utf-8", errors="ignore")
            shader, basetex = parse_vmt_details(vmt_text)
        info, w, h, rgba, err = decode_vtf_to_rgba(raw_files[vtf_norm])
        return VguiPreviewItem(
            slot_role=role,
            vtf_path=orig_paths.get(vtf_norm, vtf_norm),
            vmt_path=orig_paths.get(vmt_norm, vmt_norm) if vmt_norm in raw_files else "",
            vmt_shader=shader,
            vmt_basetexture=basetex,
            vtf_info=info,
            width=w,
            height=h,
            rgba_bytes=rgba,
            decode_error=err,
        )

    for vtf_norm in vtf_keys:
        if vtf_norm in seen_vtfs:
            continue
        seen_vtfs.add(vtf_norm)
        stem = str(PurePosixPath(vtf_norm).with_suffix(""))
        vmt_norm = f"{stem}.vmt"
        role = SurvivorRegistry.match_vgui_slot(PurePosixPath(vtf_norm).name, preferred_origin=origin)
        items.append(build_item(vtf_norm, vmt_norm if vmt_norm in raw_files else "", role))

    for vmt_norm in sorted(k for k in raw_files if k.endswith(".vmt")):
        stem = str(PurePosixPath(vmt_norm).with_suffix(""))
        vmt_text = raw_files[vmt_norm].decode("utf-8", errors="ignore")
        shader, basetex = parse_vmt_details(vmt_text)
        if not basetex:
            continue
        candidate = f"materials/{basetex.lstrip('/')}.vtf".lower()
        if candidate in raw_files and candidate not in seen_vtfs:
            seen_vtfs.add(candidate)
            role = SurvivorRegistry.match_vgui_slot(PurePosixPath(vmt_norm).name, preferred_origin=origin)
            items.append(build_item(candidate, vmt_norm, role))

    items.sort(key=lambda it: (slot_order.get(it.slot_role or "", 99), it.vtf_path.lower()))
    return items
