from __future__ import annotations

import re
from dataclasses import dataclass

from core.models import SurvivorSpec
from core.qc_parser import QcDocument, QcParser, QcStatement


@dataclass
class QcMergeResult:
    """Merged QC source text along with metadata about kit fallbacks used."""

    qc_text: str
    used_kit_ragdoll: bool
    has_collision_joints: bool


class QcMerger:
    """Merges an origin survivor QC with a destination swap-kit QC cleanly and universally."""

    _EXCLUDED_ORIGIN_DIRECTIVES = {
        "$modelname",
        "$declaresequence",
        "$includemodel",
        "$collisionjoints",
        "$collisionmodel",
        "$animation",
        "$sequence",
        "$weightlist",
    }

    _SEQUENCE_DELTA_RE = re.compile(r"(?im)^\s*(predelta|delta)\b")
    _IKRULE_RE = re.compile(r'(?im)^\s*ikrule\s+"([^"]+)"')
    _WEIGHTLIST_REF_RE = re.compile(r'(?im)^\s*weightlist\s+"([^"]+)"')
    _SMD_REF_RE = re.compile(r'"([^"]+\.smd)"', re.IGNORECASE)

    @classmethod
    def merge_survivor_qc(
        cls,
        origin_qc_text: str,
        kit_qc_text: str,
        origin_spec: SurvivorSpec,
        dest_spec: SurvivorSpec,
    ) -> QcMergeResult:
        origin_doc = QcParser.parse(origin_qc_text)
        kit_doc = QcParser.parse(kit_qc_text)

        modelname_stmt = kit_doc.find_first("$modelname")
        modelname_line = (
            modelname_stmt.raw_text
            if modelname_stmt is not None
            else f'$modelname "survivors/{dest_spec.model_file}"'
        )

        origin_body_stmts = [
            st for st in origin_doc.statements
            if st.directive not in cls._EXCLUDED_ORIGIN_DIRECTIVES
        ]

        origin_animations = origin_doc.find_all("$animation")
        origin_sequences = origin_doc.find_all("$sequence")

        origin_ragdoll: QcStatement | None = None
        non_delta_seqs: list[QcStatement] = []
        delta_seqs: list[QcStatement] = []

        for seq in origin_sequences:
            seq_name = (seq.first_quoted_arg() or "").strip().lower()
            if seq_name == "ragdoll" and origin_ragdoll is None:
                origin_ragdoll = seq
            elif cls._is_delta_sequence(seq):
                delta_seqs.append(seq)
            else:
                non_delta_seqs.append(seq)

        kit_ragdoll = next(
            (s for s in kit_doc.find_all("$sequence") if (s.first_quoted_arg() or "").lower() == "ragdoll"),
            None,
        )
        kit_slot0 = next(
            (s for s in kit_doc.find_all("$sequence") if (s.first_quoted_arg() or "").lower() != "ragdoll"),
            None,
        )

        used_kit_ragdoll = False
        final_ragdoll = origin_ragdoll
        if final_ragdoll is None:
            final_ragdoll = kit_ragdoll
            used_kit_ragdoll = kit_ragdoll is not None

        if non_delta_seqs:
            slot0_seq = non_delta_seqs[0]
            extra_seqs = non_delta_seqs[1:] + delta_seqs
        elif origin_ragdoll is not None:
            slot0_seq = cls._build_reference_pose_sequence(dest_spec, origin_ragdoll)
            extra_seqs = delta_seqs
        elif kit_slot0 is not None:
            slot0_seq = kit_slot0
            extra_seqs = delta_seqs
        else:
            raise ValueError("Origin QC has no usable $sequence or ragdoll sequence to build slot 0.")

        kept_anim_seq_stmts = list(origin_animations) + [slot0_seq] + list(extra_seqs)
        if final_ragdoll is not None:
            kept_anim_seq_stmts.append(final_ragdoll)

        existing_ikchains = {
            (st.first_quoted_arg() or "").lower(): st
            for st in origin_body_stmts
            if st.directive == "$ikchain"
        }
        kit_ikchains = {
            (st.first_quoted_arg() or "").lower(): st
            for st in kit_doc.find_all("$ikchain")
        }
        for st in kept_anim_seq_stmts:
            for match in cls._IKRULE_RE.finditer(cls._strip_quotes_not_needed(st.body_text())):
                chain_name = match.group(1).lower()
                if chain_name not in existing_ikchains and chain_name in kit_ikchains:
                    chain_stmt = kit_ikchains[chain_name]
                    origin_body_stmts.append(chain_stmt)
                    existing_ikchains[chain_name] = chain_stmt

        referenced_weightlists: set[str] = set()
        for st in kept_anim_seq_stmts:
            for match in cls._WEIGHTLIST_REF_RE.finditer(st.body_text()):
                referenced_weightlists.add(match.group(1).lower())

        kept_weightlists: list[QcStatement] = []
        seen_weightlists: set[str] = set()
        for wl in origin_doc.find_all("$weightlist") + kit_doc.find_all("$weightlist"):
            wl_name = (wl.first_quoted_arg() or "").lower()
            if wl_name in referenced_weightlists and wl_name not in seen_weightlists:
                seen_weightlists.add(wl_name)
                kept_weightlists.append(wl)

        kit_seq_skeleton: list[QcStatement] = []
        ragdoll_inserted = False
        first_kit_seq_seen = False

        for st in kit_doc.statements:
            if st.directive == "$sequence":
                name_lower = (st.first_quoted_arg() or "").lower()
                if name_lower == "ragdoll":
                    if final_ragdoll is not None and not ragdoll_inserted:
                        kit_seq_skeleton.append(final_ragdoll)
                        ragdoll_inserted = True
                elif not first_kit_seq_seen:
                    kit_seq_skeleton.append(slot0_seq)
                    first_kit_seq_seen = True
            elif st.directive == "$declaresequence":
                kit_seq_skeleton.append(st)

        if not first_kit_seq_seen:
            kit_seq_skeleton.insert(0, slot0_seq)
        if final_ragdoll is not None and not ragdoll_inserted:
            kit_seq_skeleton.append(final_ragdoll)

        origin_includes = [st.raw_text for st in origin_doc.find_all("$includemodel")]
        if not origin_includes:
            origin_includes = list(origin_spec.default_includemodels)
        kit_includes = [st.raw_text for st in kit_doc.find_all("$includemodel")]

        merged_includes: list[str] = []
        seen_includes: set[str] = set()
        for inc in origin_includes + kit_includes:
            key = cls._normalize_include_key(inc)
            if key not in seen_includes:
                seen_includes.add(key)
                merged_includes.append(inc)

        origin_collisions = origin_doc.find_all("$collisionjoints") + origin_doc.find_all("$collisionmodel")

        final_sections: list[str] = [
            "// Merged by L4D2 Survivor Swapper Tool",
            modelname_line,
            *[st.raw_text for st in origin_body_stmts],
            *[st.raw_text for st in kept_weightlists],
            *[st.raw_text for st in origin_animations],
            *[st.raw_text for st in kit_seq_skeleton],
            *[st.raw_text for st in extra_seqs],
            *merged_includes,
            *[st.raw_text for st in origin_collisions],
        ]

        merged_text = "\n\n".join(part.strip() for part in final_sections if part and part.strip()) + "\n"
        return QcMergeResult(
            qc_text=merged_text,
            used_kit_ragdoll=used_kit_ragdoll,
            has_collision_joints=bool(origin_collisions),
        )

    @staticmethod
    def rewrite_arms_qc(arms_qc_text: str, dest_spec: SurvivorSpec) -> str:
        """Update $modelname inside a decompiled v_arms QC to target destination survivor."""
        new_directive = f'$modelname "weapons/arms/{dest_spec.fp_arms.mdl}"'
        pattern = re.compile(r'(?im)^\s*\$modelname\s+"[^"]+"')
        if pattern.search(arms_qc_text):
            return pattern.sub(lambda _m: new_directive, arms_qc_text, count=1)
        return new_directive + "\n\n" + arms_qc_text

    @classmethod
    def _is_delta_sequence(cls, seq: QcStatement) -> bool:
        return bool(cls._SEQUENCE_DELTA_RE.search(seq.body_text()))

    @classmethod
    def _build_reference_pose_sequence(cls, dest_spec: SurvivorSpec, ragdoll_seq: QcStatement) -> QcStatement:
        smd_match = cls._SMD_REF_RE.search(ragdoll_seq.body_text())
        smd_ref = smd_match.group(1) if smd_match else f"{dest_spec.anims_folder}\\ragdoll.smd"
        raw = (
            f'$sequence "Custom{dest_spec.display_name}" {{\n'
            f'\t"{smd_ref}"\n'
            f"\tfadein 0.2\n"
            f"\tfadeout 0.2\n"
            f"\tfps 30\n"
            f"}}"
        )
        return QcStatement(directive="$sequence", raw_text=raw)

    @staticmethod
    def _normalize_include_key(includemodel_line: str) -> str:
        m = re.search(r'"([^"]+)"', includemodel_line)
        if m:
            return m.group(1).replace("\\", "/").strip().lower()
        return includemodel_line.replace("\\", "/").strip().lower()

    @staticmethod
    def _strip_quotes_not_needed(text: str) -> str:
        return text
