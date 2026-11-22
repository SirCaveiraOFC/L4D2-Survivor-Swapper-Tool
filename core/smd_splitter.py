from __future__ import annotations

import re
from pathlib import Path, PurePosixPath
from typing import Optional

from core.qc_parser import QcDocument, QcParser, QcStatement

SmdTriangle = tuple[str, str, str, str]


class SmdSplitter:
    """Splits oversized Source reference SMDs into studio-safe chunks for L4D2 studiomdl.exe."""

    DEFAULT_MAX_TRIS_PER_SMD = 20000

    _STUDIO_CHOICE_RE = re.compile(r'^\s*studio\s+"([^"]+)"\s*$', re.IGNORECASE)
    _REPLACEMODEL_RE = re.compile(r'^\s*replacemodel\s+"([^"]+)"\s+"([^"]+)"', re.IGNORECASE)
    _FLEX_BLOCK_RE = re.compile(r'(?im)^\s*(flexfile|eyelid|flex|flexpair)\b')
    _VTA_REF_RE = re.compile(r'(?im)^\s*(?:flexfile|eyelid\s+\S+)\s+"([^"]+)"')

    @classmethod
    def prepare_qc_for_studiomdl(
        cls,
        qc_path: Path,
        max_tris: int = DEFAULT_MAX_TRIS_PER_SMD,
    ) -> list[str]:
        """Inspect mesh SMDs referenced by qc_path and split any exceeding max_tris."""
        if not qc_path.exists():
            return []

        raw_bytes = qc_path.read_bytes()
        try:
            qc_text = raw_bytes.decode("utf-8")
        except UnicodeDecodeError:
            qc_text = raw_bytes.decode("cp1252", errors="replace")

        doc = QcParser.parse(qc_text)
        qc_dir = qc_path.parent
        new_statements: list[QcStatement] = []
        split_sources: set[str] = set()
        logs: list[str] = []

        for st in doc.statements:
            if st.directive == "$body":
                replaced, src_key, log_line = cls._handle_body(st, qc_dir, max_tris)
                if replaced is not None:
                    new_statements.extend(replaced)
                    if src_key:
                        split_sources.add(src_key)
                    if log_line:
                        logs.append(log_line)
                    continue

            elif st.directive == "$bodygroup":
                replaced, src_key, log_line = cls._handle_bodygroup(st, qc_dir, max_tris)
                if replaced is not None:
                    new_statements.extend(replaced)
                    if src_key:
                        split_sources.add(src_key)
                    if log_line:
                        logs.append(log_line)
                    continue

            elif st.directive == "$model":
                replaced, src_key, log_line = cls._handle_model(st, qc_dir, max_tris)
                if replaced is not None:
                    new_statements.extend(replaced)
                    if src_key:
                        split_sources.add(src_key)
                    if log_line:
                        logs.append(log_line)
                    continue

            new_statements.append(st)

        if not split_sources:
            return logs

        final_statements = cls._cleanup_lod_statements(new_statements, split_sources)
        qc_path.write_text(QcDocument(final_statements).to_text(), encoding="utf-8", newline="\n")
        return logs

    @classmethod
    def _build_split_body_result(
        cls,
        body_prefix: str,
        smd_rel: str,
        qc_dir: Path,
        max_tris: int,
    ) -> tuple[Optional[list[QcStatement]], Optional[str], Optional[str]]:
        smd_path = cls._resolve_smd_path(qc_dir, smd_rel)
        if smd_path is None:
            return None, None, None
        chunks, tri_count = cls._split_smd_file(qc_dir, smd_path, max_tris)
        if not chunks:
            return None, None, None
        out = [
            QcStatement("$body", f'$body "{body_prefix}_p{idx}" "{rel}"')
            for idx, rel in enumerate(chunks)
        ]
        log = f"Auto-split oversized SMD '{smd_path.name}' ({tri_count} tris) into {len(chunks)} chunks."
        return out, cls._norm_key(smd_rel), log

    @classmethod
    def _handle_body(
        cls,
        st: QcStatement,
        qc_dir: Path,
        max_tris: int,
    ) -> tuple[Optional[list[QcStatement]], Optional[str], Optional[str]]:
        args = st.quoted_args()
        if len(args) < 2:
            return None, None, None
        return cls._build_split_body_result(args[0], args[1], qc_dir, max_tris)

    @classmethod
    def _handle_bodygroup(
        cls,
        st: QcStatement,
        qc_dir: Path,
        max_tris: int,
    ) -> tuple[Optional[list[QcStatement]], Optional[str], Optional[str]]:
        group_name = st.first_quoted_arg() or "body"
        inner_lines = cls._non_comment_lines(st.body_text())
        if len(inner_lines) != 1:
            return None, None, None
        match = cls._STUDIO_CHOICE_RE.match(inner_lines[0])
        if not match:
            return None, None, None
        return cls._build_split_body_result(group_name, match.group(1), qc_dir, max_tris)

    @classmethod
    def _handle_model(
        cls,
        st: QcStatement,
        qc_dir: Path,
        max_tris: int,
    ) -> tuple[Optional[list[QcStatement]], Optional[str], Optional[str]]:
        args = st.quoted_args()
        if len(args) < 2:
            return None, None, None
        model_name, smd_rel = args[0], args[1]
        smd_path = cls._resolve_smd_path(qc_dir, smd_rel)
        if smd_path is None:
            return None, None, None

        parsed = cls._read_smd_triangles(smd_path)
        if parsed is None:
            return None, None, None
        header, tris = parsed
        if len(tris) <= max_tris:
            return None, None, None

        body_suffix = ""
        has_flex = False
        if st.has_block:
            body_text = st.body_text()
            body_suffix = f"\n{{\n{body_text.strip()}\n}}"
            has_flex = bool(cls._FLEX_BLOCK_RE.search(body_text))

        if has_flex:
            primary_tris, extra_tris = cls._partition_tris_by_flex_vta(qc_dir, st.body_text(), tris)
            if not extra_tris:
                return None, None, None
            primary_chunks = cls._chunk_triangles(primary_tris, max_tris)
            extra_chunks = cls._chunk_triangles(extra_tris, max_tris)
            groups = primary_chunks + extra_chunks
        else:
            groups = cls._chunk_triangles(tris, max_tris)

        if len(groups) <= 1:
            return None, None, None

        rel_chunks = cls._write_smd_chunks(qc_dir, smd_path, header, groups)
        out = [QcStatement("$model", f'$model "{model_name}" "{rel_chunks[0]}"{body_suffix}')]
        for idx, rel in enumerate(rel_chunks[1:], start=1):
            out.append(QcStatement("$body", f'$body "{model_name}_p{idx}" "{rel}"'))

        log = f"Auto-split oversized $model SMD '{smd_path.name}' ({len(tris)} tris) into {len(rel_chunks)} chunks."
        return out, cls._norm_key(smd_rel), log

    @classmethod
    def _split_smd_file(
        cls,
        qc_dir: Path,
        smd_path: Path,
        max_tris: int,
    ) -> tuple[list[str], int]:
        parsed = cls._read_smd_triangles(smd_path)
        if parsed is None:
            return [], 0
        header, tris = parsed
        if len(tris) <= max_tris:
            return [], len(tris)

        groups = cls._chunk_triangles(tris, max_tris)
        rel_chunks = cls._write_smd_chunks(qc_dir, smd_path, header, groups)
        return rel_chunks, len(tris)

    @staticmethod
    def _chunk_triangles(tris: list[SmdTriangle], max_tris: int) -> list[list[SmdTriangle]]:
        if not tris:
            return []
        return [tris[i : i + max_tris] for i in range(0, len(tris), max_tris)]

    @staticmethod
    def _write_smd_chunks(
        qc_dir: Path,
        smd_path: Path,
        header: str,
        groups: list[list[SmdTriangle]],
    ) -> list[str]:
        rel_chunks: list[str] = []
        stem = smd_path.stem
        for idx, tri_group in enumerate(groups):
            chunk_path = smd_path.parent / f"{stem}_part{idx}{smd_path.suffix}"
            with chunk_path.open("w", encoding="utf-8", newline="\n") as fh:
                fh.write(header)
                for mat_line, v1, v2, v3 in tri_group:
                    fh.write(mat_line)
                    fh.write(v1)
                    fh.write(v2)
                    fh.write(v3)
                fh.write("end\n")
            rel_chunks.append(chunk_path.relative_to(qc_dir).as_posix())
        return rel_chunks

    @staticmethod
    def _read_smd_triangles(smd_path: Path) -> Optional[tuple[str, list[SmdTriangle]]]:
        raw = smd_path.read_bytes()
        try:
            text = raw.decode("utf-8")
        except UnicodeDecodeError:
            text = raw.decode("cp1252", errors="replace")

        lines = text.splitlines()
        tri_idx = next((i for i, l in enumerate(lines) if l.strip().lower() == "triangles"), -1)
        if tri_idx == -1:
            return None

        header = "\n".join(lines[: tri_idx + 1]) + "\n"

        tris: list[SmdTriangle] = []
        i = tri_idx + 1
        n = len(lines)

        while i < n:
            line = lines[i]
            stripped = line.strip()
            if not stripped or stripped.startswith("//"):
                i += 1
                continue
            if stripped.lower() == "end":
                break

            mat_line = line + "\n"
            verts: list[str] = []
            j = i + 1
            while j < n and len(verts) < 3:
                vl = lines[j]
                vst = vl.strip()
                if not vst or vst.startswith("//"):
                    j += 1
                    continue
                if vst.lower() == "end":
                    break
                verts.append(vl + "\n")
                j += 1

            if len(verts) < 3:
                break
            tris.append((mat_line, verts[0], verts[1], verts[2]))
            i = j

        return header, tris

    @classmethod
    def _partition_tris_by_flex_vta(
        cls,
        qc_dir: Path,
        model_block: str,
        tris: list[SmdTriangle],
    ) -> tuple[list[SmdTriangle], list[SmdTriangle]]:
        vta_coords: set[tuple[int, int, int]] = set()
        for match in cls._VTA_REF_RE.finditer(model_block):
            vta_path = cls._resolve_smd_path(qc_dir, match.group(1), default_ext=".vta")
            if vta_path is not None:
                vta_coords.update(cls._extract_vta_flex_coords(vta_path))

        if not vta_coords:
            return tris, []

        flex_mats: set[str] = set()
        for mat_line, v1, v2, v3 in tris:
            mat_key = mat_line.strip().lower()
            if mat_key in flex_mats:
                continue
            for v_line in (v1, v2, v3):
                coord = cls._quantized_vert_coord(v_line)
                if coord is not None and coord in vta_coords:
                    flex_mats.add(mat_key)
                    break

        if not flex_mats:
            return tris, []

        primary: list[SmdTriangle] = []
        extra: list[SmdTriangle] = []
        for tri in tris:
            if tri[0].strip().lower() in flex_mats:
                primary.append(tri)
            else:
                extra.append(tri)
        return (primary, extra) if primary else (tris, [])

    @classmethod
    def _extract_vta_flex_coords(cls, vta_path: Path) -> set[tuple[int, int, int]]:
        raw = vta_path.read_bytes()
        try:
            text = raw.decode("utf-8")
        except UnicodeDecodeError:
            text = raw.decode("cp1252", errors="replace")

        rest_by_idx: dict[int, tuple[int, int, int]] = {}
        moved_indices: set[int] = set()
        in_va = False
        cur_time = -1

        for line in text.splitlines():
            st = line.strip()
            if st.lower() == "vertexanimation":
                in_va = True
                continue
            if not in_va:
                continue
            if st.lower() == "end":
                break
            if st.lower().startswith("time "):
                try:
                    cur_time = int(st.split()[1])
                except (IndexError, ValueError):
                    cur_time = -1
                continue

            parts = st.split()
            if len(parts) < 4:
                continue
            try:
                vidx = int(parts[0])
            except ValueError:
                continue

            if cur_time == 0:
                coord = cls._quantized_vert_coord(st)
                if coord is not None:
                    rest_by_idx[vidx] = coord
            elif cur_time > 0:
                moved_indices.add(vidx)

        if moved_indices and rest_by_idx:
            matched = {rest_by_idx[i] for i in moved_indices if i in rest_by_idx}
            if matched:
                return matched
        return set(rest_by_idx.values())

    @staticmethod
    def _quantized_vert_coord(line: str) -> Optional[tuple[int, int, int]]:
        parts = line.split()
        if len(parts) < 4:
            return None
        try:
            return (round(float(parts[1]) * 100), round(float(parts[2]) * 100), round(float(parts[3]) * 100))
        except ValueError:
            return None

    @classmethod
    def _cleanup_lod_statements(
        cls,
        statements: list[QcStatement],
        split_sources: set[str],
    ) -> list[QcStatement]:
        cleaned: list[QcStatement] = []
        for st in statements:
            if st.directive != "$lod" or not st.has_block:
                cleaned.append(st)
                continue

            brace_idx = st._first_unquoted_brace(st.raw_text)
            header = st.raw_text[:brace_idx].strip()
            kept_lines: list[str] = []
            for raw_line in st.body_text().splitlines():
                rm = cls._REPLACEMODEL_RE.match(raw_line)
                if rm and cls._norm_key(rm.group(1)) in split_sources:
                    continue
                if raw_line.strip():
                    kept_lines.append(raw_line)

            if not kept_lines:
                continue
            body_joined = "\n".join(kept_lines)
            cleaned.append(QcStatement("$lod", f"{header}\n{{\n{body_joined}\n}}"))
        return cleaned

    @staticmethod
    def _non_comment_lines(body_text: str) -> list[str]:
        out: list[str] = []
        for line in body_text.splitlines():
            stripped = line.split("//", 1)[0].strip()
            if stripped:
                out.append(stripped)
        return out

    @staticmethod
    def _norm_key(rel_path: str) -> str:
        norm = rel_path.replace("\\", "/").strip().lower()
        return str(PurePosixPath(norm).with_suffix(".smd"))

    @staticmethod
    def _resolve_smd_path(qc_dir: Path, raw_rel: str, default_ext: str = ".smd") -> Optional[Path]:
        cleaned = raw_rel.replace("\\", "/").strip().lstrip("./")
        if not cleaned:
            return None
        candidates = [cleaned]
        if Path(cleaned).suffix == "" and default_ext:
            candidates.append(f"{cleaned}{default_ext}")

        for cand in candidates:
            current = qc_dir
            found = True
            for part in PurePosixPath(cand).parts:
                if not current.exists() or not current.is_dir():
                    found = False
                    break
                part_lower = part.lower()
                match = next((p for p in current.iterdir() if p.name.lower() == part_lower), None)
                if match is None:
                    found = False
                    break
                current = match
            if found and current.is_file():
                return current
        return None
