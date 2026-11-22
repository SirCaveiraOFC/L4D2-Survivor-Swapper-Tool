from __future__ import annotations

import os
import re
import shutil
import tempfile
import uuid
from pathlib import Path, PurePosixPath
from typing import Optional

from core.addons_scanner import AddonsScanner
from core.i18n import LocalizationManager
from core.mdl_toolchain import MdlToolchain
from core.models import (
    CancelCallback,
    DetectedModInfo,
    EnvironmentStatus,
    ModMetadata,
    ProgressCallback,
    SurvivorId,
    SurvivorSpec,
    SwapCancelledError,
    SwapJobRequest,
    SwapProgress,
    SwapTargetResult,
)
from core.qc_merger import QcMerger
from core.smd_splitter import SmdSplitter
from core.survivors import SurvivorRegistry
from core.vpk_service import VpkService


_JobCancelledError = SwapCancelledError


class SwapEngine:
    """Transactional OOP pipeline that converts L4D2 survivor mods between survivors."""

    _INVALID_FILENAME_CHARS = re.compile(r'[\\/:*?"<>|]')

    def __init__(
        self,
        env_status: EnvironmentStatus,
        kit_dir: Path,
        vpk_service: Optional[VpkService] = None,
        i18n: Optional[LocalizationManager] = None,
    ) -> None:
        self.env_status = env_status
        self.kit_dir = Path(kit_dir)
        self.vpk_service = vpk_service or VpkService()
        self.i18n = i18n or LocalizationManager("en-US")

        if not env_status.is_ready_for_swap:
            missing = []
            if not env_status.l4d2_installed:
                missing.append("Left 4 Dead 2")
            if not env_status.studiomdl_path or not env_status.studiomdl_path.exists():
                missing.append("studiomdl.exe (Authoring Tools)")
            if not env_status.vpk_exe_path or not env_status.vpk_exe_path.exists():
                missing.append("vpk.exe (Authoring Tools)")
            if not env_status.decompiler_cli_path or not env_status.decompiler_cli_path.exists():
                missing.append("MdlDecompilerCli.exe")
            raise RuntimeError("Environment not ready. Missing: " + ", ".join(missing))

        self.toolchain = MdlToolchain(
            decompiler_cli=env_status.decompiler_cli_path,
            studiomdl_exe=env_status.studiomdl_path,
            l4d2_dir=env_status.l4d2_dir,
        )

    def inspect_mod(self, source_path: Path) -> DetectedModInfo:
        return self.vpk_service.inspect_source(source_path)

    def run_job(
        self,
        request: SwapJobRequest,
        progress_cb: Optional[ProgressCallback] = None,
        keep_temp_on_error: bool = False,
        cancel_cb: Optional[CancelCallback] = None,
    ) -> list[SwapTargetResult]:
        if not request.destinations:
            raise ValueError("At least one destination survivor must be selected.")

        origin_spec = SurvivorRegistry.get(request.origin)
        results: list[SwapTargetResult] = []
        workspace = Path(tempfile.gettempdir()) / f"l4d2sw_{uuid.uuid4().hex[:8]}"
        workspace.mkdir(parents=True, exist_ok=True)

        total_targets = len(request.destinations)
        total_steps = 2 + total_targets * 5
        current_step = 0
        had_error = False
        job_cancelled = False

        def check_cancelled() -> None:
            if cancel_cb is not None and cancel_cb():
                raise _JobCancelledError()

        def emit(message: str, target: Optional[SurvivorId] = None, log_line: Optional[str] = None) -> None:
            if progress_cb is None:
                return
            pct = min(100, int((current_step / max(1, total_steps)) * 100))
            progress_cb(
                SwapProgress(
                    step=current_step,
                    total_steps=total_steps,
                    percent=pct,
                    message=message,
                    target=target,
                    log_line=log_line,
                )
            )

        self.toolchain.active_cancel_cb = cancel_cb
        self.vpk_service.active_cancel_cb = cancel_cb
        try:
            try:
                check_cancelled()
                current_step += 1
                emit(self.i18n.tr("prog_preparing_source", name=request.source_path.name))
                origin_mod_dir = workspace / "origin_mod"
                if request.source_path.is_file() and request.source_path.suffix.lower() == ".vpk":
                    self.vpk_service.extract_vpk(request.source_path, origin_mod_dir)
                elif request.source_path.is_dir():
                    shutil.copytree(request.source_path, origin_mod_dir, dirs_exist_ok=True)
                else:
                    raise ValueError(f"Invalid source path: {request.source_path}")

                check_cancelled()
                current_step += 1
                emit(self.i18n.tr("prog_decompiling_origin", origin=origin_spec.display_name))
                origin_mdl = self._find_case_insensitive_rel(
                    origin_mod_dir, f"models/survivors/{origin_spec.model_file}"
                )
                surv_dir = self._find_case_insensitive_rel(origin_mod_dir, "models/survivors")
                light_mdl_names = (
                    sorted(
                        p.name
                        for p in surv_dir.iterdir()
                        if p.is_file() and "_light" in p.stem.lower() and p.suffix.lower() == ".mdl"
                    )
                    if surv_dir is not None and surv_dir.is_dir()
                    else []
                )
                light_warning: Optional[str] = None
                if light_mdl_names:
                    light_warning = self.i18n.tr(
                        "prog_warn_light_ignored",
                        files=", ".join(light_mdl_names),
                    )
                    emit(light_warning, log_line=light_warning)

                if origin_mdl is None:
                    if light_mdl_names:
                        raise FileNotFoundError(
                            f"Could not find main 'models/survivors/{origin_spec.model_file}' "
                            f"(only _light model files found: {', '.join(light_mdl_names)})"
                        )
                    raise FileNotFoundError(
                        f"Could not find 'models/survivors/{origin_spec.model_file}' inside {request.source_path.name}"
                    )

                origin_dec_dir = workspace / "dec_origin_body"
                origin_qc_path, decomp_body_logs = self.toolchain.decompile(origin_mdl, origin_dec_dir)

                origin_arms_mdl = self._find_origin_arms_mdl(origin_mod_dir, origin_spec)
                origin_arms_dec_dir: Optional[Path] = None
                origin_arms_qc_path: Optional[Path] = None
                decomp_arms_logs: list[str] = []
                arms_decomp_warning: Optional[str] = None
                if request.include_arms and origin_arms_mdl is not None:
                    origin_arms_dec_dir = workspace / "dec_origin_arms"
                    try:
                        origin_arms_qc_path, decomp_arms_logs = self.toolchain.decompile(
                            origin_arms_mdl, origin_arms_dec_dir
                        )
                    except _JobCancelledError:
                        raise
                    except Exception as exc:
                        origin_arms_dec_dir = None
                        origin_arms_qc_path = None
                        first_line = self._first_error_line(exc)
                        arms_decomp_warning = self.i18n.tr("prog_warn_arms_failed", error=first_line)
                        emit(arms_decomp_warning, log_line=arms_decomp_warning)

                for dest_id in request.destinations:
                    check_cancelled()
                    dest_spec = SurvivorRegistry.get(dest_id)
                    if dest_spec.id == origin_spec.id:
                        results.append(
                            SwapTargetResult(
                                destination=dest_id,
                                success=False,
                                error_message="Origin and destination survivors cannot be the same.",
                            )
                        )
                        current_step += 5
                        continue

                    target_logs = list(decomp_body_logs) + list(decomp_arms_logs)
                    target_warnings: list[str] = [light_warning] if light_warning else []
                    step_counter_ref = [current_step]

                    def step_advance(msg: str, target: SurvivorId = dest_id, ref: list[int] = step_counter_ref) -> None:
                        self._advance_and_emit(progress_cb, msg, target, lambda: ref[0], total_steps)

                    try:
                        result = self._process_single_target(
                            request=request,
                            origin_spec=origin_spec,
                            dest_spec=dest_spec,
                            origin_mod_dir=origin_mod_dir,
                            origin_qc_path=origin_qc_path,
                            origin_dec_dir=origin_dec_dir,
                            origin_arms_qc_path=origin_arms_qc_path,
                            origin_arms_dec_dir=origin_arms_dec_dir,
                            arms_decomp_warning=arms_decomp_warning,
                            workspace=workspace,
                            step_advance=step_advance,
                            step_counter_ref=step_counter_ref,
                            logs=target_logs,
                            warnings=target_warnings,
                            check_cancelled=check_cancelled,
                        )
                        current_step += 5
                        results.append(result)
                    except _JobCancelledError:
                        job_cancelled = True
                        cancel_msg = self.i18n.tr("prog_cancelled")
                        results.append(
                            SwapTargetResult(
                                destination=dest_id,
                                success=False,
                                cancelled=True,
                                warnings=target_warnings,
                                error_message=cancel_msg,
                                logs=target_logs,
                            )
                        )
                        emit(cancel_msg, target=dest_id, log_line=cancel_msg)
                        break
                    except Exception as exc:
                        had_error = True
                        current_step += 5
                        results.append(
                            SwapTargetResult(
                                destination=dest_id,
                                success=False,
                                warnings=target_warnings,
                                error_message=str(exc),
                                logs=target_logs,
                            )
                        )
                        emit(
                            self.i18n.tr("prog_target_failed", target=dest_spec.display_name, error=exc),
                            target=dest_id,
                            log_line=str(exc),
                        )
            except _JobCancelledError:
                job_cancelled = True
                cancel_msg = self.i18n.tr("prog_cancelled")
                results.append(
                    SwapTargetResult(
                        destination=request.destinations[0],
                        success=False,
                        cancelled=True,
                        error_message=cancel_msg,
                    )
                )
                emit(cancel_msg, log_line=cancel_msg)

            if progress_cb is not None:
                finish_msg = self.i18n.tr("prog_cancelled") if job_cancelled else self.i18n.tr("prog_finished")
                progress_cb(
                    SwapProgress(
                        step=current_step if job_cancelled else total_steps,
                        total_steps=total_steps,
                        percent=100 if not job_cancelled else min(99, int((current_step / max(1, total_steps)) * 100)),
                        message=finish_msg,
                    )
                )
            return results
        except Exception:
            had_error = True
            raise
        finally:
            self.toolchain.active_cancel_cb = None
            self.vpk_service.active_cancel_cb = None
            if workspace.exists() and not (had_error and keep_temp_on_error):
                shutil.rmtree(workspace, ignore_errors=True)

    def _process_single_target(
        self,
        request: SwapJobRequest,
        origin_spec: SurvivorSpec,
        dest_spec: SurvivorSpec,
        origin_mod_dir: Path,
        origin_qc_path: Path,
        origin_dec_dir: Path,
        origin_arms_qc_path: Optional[Path],
        origin_arms_dec_dir: Optional[Path],
        arms_decomp_warning: Optional[str],
        workspace: Path,
        step_advance,
        step_counter_ref: list[int],
        logs: list[str],
        warnings: list[str],
        check_cancelled=None,
    ) -> SwapTargetResult:
        def next_step(msg: str) -> None:
            if check_cancelled is not None:
                check_cancelled()
            step_counter_ref[0] += 1
            step_advance(msg)

        tag = dest_spec.id.value
        target_ws = workspace / f"t_{tag}"
        staging_game = self.toolchain.create_staging_game_dir(target_ws / "stage")
        build_body_dir = target_ws / "build_body"
        orig_title_val = (
            request.metadata.original_title
            or request.metadata.title
            or request.source_path.stem
        )
        pack_stem = self._sanitize_filename(
            self._format_output_name(
                request.output_name_template,
                origin_spec,
                dest_spec,
                multi_target=len(request.destinations) > 1,
                title=orig_title_val,
                sanitize_origin=request.sanitize_origin_title,
            )
        )
        pack_dir = target_ws / "pack" / "pkg"
        pack_dir.mkdir(parents=True, exist_ok=True)

        next_step(self.i18n.tr("prog_target_decomp_kit", target=dest_spec.display_name))
        kit_mdl = self.kit_dir / dest_spec.kit_folder / "models" / "survivors" / dest_spec.model_file
        if not kit_mdl.exists():
            raise FileNotFoundError(f"Swap kit model not found: {kit_mdl}")

        kit_dec_dir = target_ws / "dec_kit"
        kit_qc_path, kit_decomp_logs = self.toolchain.decompile(kit_mdl, kit_dec_dir)
        logs.extend(kit_decomp_logs)

        next_step(self.i18n.tr("prog_target_merging_qc", target=dest_spec.display_name))
        shutil.copytree(origin_dec_dir, build_body_dir, dirs_exist_ok=True)

        origin_qc_text = self._read_text_safe(origin_qc_path)
        kit_qc_text = self._read_text_safe(kit_qc_path)
        merge_result = QcMerger.merge_survivor_qc(origin_qc_text, kit_qc_text, origin_spec, dest_spec)

        if merge_result.used_kit_ragdoll:
            kit_anims_src = kit_dec_dir / dest_spec.anims_folder
            if kit_anims_src.exists():
                shutil.copytree(kit_anims_src, build_body_dir / dest_spec.anims_folder, dirs_exist_ok=True)
            warnings.append(self.i18n.tr("prog_warn_fallback_ragdoll"))

        merged_qc_path = build_body_dir / dest_spec.qc_filename
        merged_qc_path.write_text(merge_result.qc_text, encoding="utf-8")
        logs.extend(SmdSplitter.prepare_qc_for_studiomdl(merged_qc_path))

        next_step(self.i18n.tr("prog_target_compiling", target=dest_spec.display_name))
        compile_body_logs = self.toolchain.compile_qc(merged_qc_path, staging_game)
        logs.extend(compile_body_logs)

        if arms_decomp_warning:
            warnings.append(arms_decomp_warning)
        elif request.include_arms and origin_arms_qc_path is not None and origin_arms_dec_dir is not None:
            try:
                build_arms_dir = target_ws / "build_arms"
                shutil.copytree(origin_arms_dec_dir, build_arms_dir, dirs_exist_ok=True)
                arms_qc_text = self._read_text_safe(origin_arms_qc_path)
                rewritten_arms_qc = QcMerger.rewrite_arms_qc(arms_qc_text, dest_spec)
                arms_target_qc = build_arms_dir / f"{Path(dest_spec.fp_arms.mdl).stem}.qc"
                arms_target_qc.write_text(rewritten_arms_qc, encoding="utf-8")
                logs.extend(SmdSplitter.prepare_qc_for_studiomdl(arms_target_qc))
                compile_arms_logs = self.toolchain.compile_qc(arms_target_qc, staging_game)
                logs.extend(compile_arms_logs)
            except _JobCancelledError:
                raise
            except Exception as exc:
                arms_stage_dir = staging_game / "models" / "weapons" / "arms"
                if arms_stage_dir.exists():
                    shutil.rmtree(arms_stage_dir, ignore_errors=True)
                first_line = self._first_error_line(exc)
                warnings.append(self.i18n.tr("prog_warn_arms_failed", error=first_line))
        elif request.include_arms:
            warnings.append(self.i18n.tr("prog_warn_no_arms"))

        next_step(self.i18n.tr("prog_target_assembling", target=dest_spec.display_name))
        self._assemble_pack_directory(
            request=request,
            origin_spec=origin_spec,
            dest_spec=dest_spec,
            origin_mod_dir=origin_mod_dir,
            staging_game=staging_game,
            pack_dir=pack_dir,
            has_physics=merge_result.has_collision_joints,
        )

        next_step(self.i18n.tr("prog_target_packing", target=dest_spec.display_name))
        if check_cancelled is not None:
            check_cancelled()
        output_vpk = request.output_dir / f"{pack_stem}.vpk"
        vpk_logs = self.vpk_service.pack_folder_to_vpk(
            source_dir=pack_dir,
            output_vpk=output_vpk,
            vpk_exe=self.env_status.vpk_exe_path,
        )
        logs.extend(vpk_logs)

        installed_path: Optional[Path] = None
        if request.install_to_addons:
            if check_cancelled is not None:
                check_cancelled()
            addons_dir = request.addons_dir or self.env_status.l4d2_addons_dir
            if addons_dir is not None:
                try:
                    addons_dir.mkdir(parents=True, exist_ok=True)
                    conflicts = AddonsScanner.find_conflicts(
                        addons_dir,
                        [(dest_spec.id, output_vpk.name)],
                    )
                    for conflict in conflicts:
                        existing = conflict.existing_addon
                        location = (
                            f"workshop/{existing.vpk_path.name}"
                            if existing.source_kind == "workshop"
                            else existing.vpk_path.name
                        )
                        warnings.append(
                            self.i18n.tr(
                                "prog_warn_addon_conflict",
                                target=dest_spec.display_name,
                                title=existing.title,
                                location=location,
                            )
                        )
                    dest_addon_path = addons_dir / output_vpk.name
                    shutil.copy2(output_vpk, dest_addon_path)
                    installed_path = dest_addon_path
                except OSError as exc:
                    warnings.append(self.i18n.tr("prog_warn_install_failed", error=exc))
            else:
                warnings.append(self.i18n.tr("prog_warn_no_addons"))

        return SwapTargetResult(
            destination=dest_spec.id,
            success=True,
            vpk_path=output_vpk,
            installed_path=installed_path,
            warnings=warnings,
            logs=logs,
        )

    def _assemble_pack_directory(
        self,
        request: SwapJobRequest,
        origin_spec: SurvivorSpec,
        dest_spec: SurvivorSpec,
        origin_mod_dir: Path,
        staging_game: Path,
        pack_dir: Path,
        has_physics: bool,
    ) -> None:
        known_stems = SurvivorRegistry.all_known_survivor_model_stems()
        for root_str, _, files in os.walk(origin_mod_dir):
            root_path = Path(root_str)
            rel_dir = root_path.relative_to(origin_mod_dir)
            rel_posix = rel_dir.as_posix().lower()

            if rel_posix == "models/weapons/arms" or rel_posix.startswith("models/weapons/arms/"):
                continue
            if not request.include_weapons and (rel_posix == "models/weapons" or rel_posix.startswith("models/weapons/")):
                continue
            if not request.include_vgui and (rel_posix == "materials/vgui" or rel_posix.startswith("materials/vgui/")):
                continue

            for fname in files:
                src_file = root_path / fname
                rel_file = rel_dir / fname
                rel_file_lower = rel_file.as_posix().lower()

                if rel_file_lower == "addoninfo.txt":
                    continue

                if rel_posix == "models/survivors":
                    base_stem = fname.split(".", 1)[0].lower()
                    if base_stem in known_stems:
                        continue

                dest_file = pack_dir / rel_file
                dest_file.parent.mkdir(parents=True, exist_ok=True)
                shutil.copy2(src_file, dest_file)

        if request.include_vgui:
            self._process_vgui_directory(pack_dir / "materials" / "vgui", origin_spec, dest_spec)

        staged_surv_dir = staging_game / "models" / "survivors"
        dest_surv_dir = pack_dir / "models" / "survivors"
        dest_surv_dir.mkdir(parents=True, exist_ok=True)

        body_exts = [".mdl", ".vvd", ".dx90.vtx"]
        if has_physics:
            body_exts.append(".phy")

        for ext in body_exts:
            src_compiled = self._find_case_insensitive_file(staged_surv_dir, f"{dest_spec.survivor_id}{ext}")
            if src_compiled is None:
                if ext == ".phy":
                    continue
                raise FileNotFoundError(
                    f"Compiled survivor artifact missing in staging: {dest_spec.survivor_id}{ext}"
                )
            shutil.copy2(src_compiled, dest_surv_dir / f"{dest_spec.survivor_id}{ext}")

        staged_arms_dir = staging_game / "models" / "weapons" / "arms"
        arms_stem = Path(dest_spec.fp_arms.mdl).stem
        if staged_arms_dir.exists():
            compiled_arms_mdl = self._find_case_insensitive_file(staged_arms_dir, dest_spec.fp_arms.mdl)
            if compiled_arms_mdl is not None:
                dest_arms_dir = pack_dir / "models" / "weapons" / "arms"
                dest_arms_dir.mkdir(parents=True, exist_ok=True)
                for ext in (".mdl", ".vvd", ".dx90.vtx"):
                    src_arm = self._find_case_insensitive_file(staged_arms_dir, f"{arms_stem}{ext}")
                    if src_arm is None:
                        raise FileNotFoundError(
                            f"Compiled arms artifact missing in staging: {arms_stem}{ext}"
                        )
                    shutil.copy2(src_arm, dest_arms_dir / f"{arms_stem}{ext}")

        target_meta = self._build_target_metadata(
            request.metadata,
            origin_spec,
            dest_spec,
            sanitize_origin=request.sanitize_origin_title,
        )
        (pack_dir / "addoninfo.txt").write_text(
            self.vpk_service.serialize_addoninfo(target_meta),
            encoding="utf-8",
        )

        if request.custom_addonimage_path is not None and request.custom_addonimage_path.is_file():
            for existing in list(pack_dir.iterdir()):
                if existing.is_file() and existing.name.lower() in (
                    "addonimage.jpg",
                    "addonimage.jpeg",
                    "addonimage.png",
                ):
                    existing.unlink()
            out_name = "addonimage.png" if request.custom_addonimage_path.suffix.lower() == ".png" else "addonimage.jpg"
            shutil.copy2(request.custom_addonimage_path, pack_dir / out_name)

    @staticmethod
    def _process_vgui_directory(vgui_dir: Path, origin_spec: SurvivorSpec, dest_spec: SurvivorSpec) -> None:
        if not vgui_dir.exists() or not vgui_dir.is_dir():
            return

        slot_map = {
            "lobby_icon": dest_spec.vgui.lobby_icon,
            "in_game_icon": dest_spec.vgui.in_game_icon,
            "incap_icon": dest_spec.vgui.incap_icon,
        }

        vtfs = list(vgui_dir.glob("*.vtf")) + list(vgui_dir.glob("*.VTF"))
        seen_paths: set[Path] = set()
        renamed_slots: set[str] = set()
        for vtf_file in vtfs:
            if vtf_file in seen_paths:
                continue
            seen_paths.add(vtf_file)
            slot = SurvivorRegistry.match_vgui_slot(vtf_file.name, preferred_origin=origin_spec.id)
            if slot:
                new_name = slot_map[slot]
                target_path = vgui_dir / new_name
                if vtf_file.name.lower() != new_name.lower():
                    if target_path.exists():
                        target_path.unlink()
                    vtf_file.rename(target_path)
                renamed_slots.add(slot)

        for vmt_file in list(vgui_dir.glob("*.vmt")) + list(vgui_dir.glob("*.VMT")):
            if not vmt_file.exists():
                continue
            equiv_vtf_name = f"{vmt_file.stem}.vtf"
            slot = SurvivorRegistry.match_vgui_slot(equiv_vtf_name, preferred_origin=origin_spec.id)
            if slot:
                if slot in renamed_slots:
                    vmt_file.unlink()
                else:
                    dest_vmt_name = Path(slot_map[slot]).with_suffix(".vmt").name
                    target_vmt = vgui_dir / dest_vmt_name
                    if target_vmt.exists() and target_vmt != vmt_file:
                        target_vmt.unlink()
                    vmt_file.rename(target_vmt)

    @staticmethod
    def clean_origin_from_text(text: str, origin_spec: SurvivorSpec) -> str:
        """Strip repeated origin survivor tags/suffixes/prefixes from a mod title or stem."""
        cleaned = (text or "").strip()
        if not cleaned:
            return ""
        names = "|".join(
            sorted(
                {re.escape(origin_spec.display_name), re.escape(origin_spec.survivor_id)},
                key=len,
                reverse=True,
            )
        )
        bracket_pat = re.compile(
            rf"\s*[\(\[]\s*(?:(?:for|para|as|como|replaces?|skin|slot)\s+)?(?:{names})\s*[\)\]]",
            re.IGNORECASE,
        )
        prefix_pat = re.compile(
            rf"^\s*(?:{names})\s*(?:=>|->|:|-|–)+\s*",
            re.IGNORECASE,
        )
        suffix_pat = re.compile(
            rf"\s*(?:[-–_:|/]+|\b(?:as|for|on|sobre|para|replaces?)\b)\s*(?:{names})\s*$",
            re.IGNORECASE,
        )

        prev = None
        while prev != cleaned:
            prev = cleaned
            cleaned = bracket_pat.sub("", cleaned).strip()
            cleaned = prefix_pat.sub("", cleaned).strip()
            cleaned = suffix_pat.sub("", cleaned).strip()
            cleaned = cleaned.strip(" -–_:|/")

        return cleaned or text.strip()

    @classmethod
    def render_placeholders(
        cls,
        template: str,
        origin_spec: SurvivorSpec,
        dest_spec: SurvivorSpec,
        orig_title: str = "",
        for_filename: bool = False,
        sanitize_origin: bool = False,
    ) -> str:
        """Expand {survivor}, {origin}, {orig_title}, and {generation} tokens safely."""
        if for_filename and ("-" in template or "_" in template):
            surv_tok = dest_spec.id.value
            orig_tok = origin_spec.id.value
            gen_tok = dest_spec.generation.lower()
            orig_gen_tok = origin_spec.generation.lower()
        else:
            surv_tok = dest_spec.display_name
            orig_tok = origin_spec.display_name
            gen_tok = dest_spec.generation
            orig_gen_tok = origin_spec.generation

        base_title = orig_title.strip()
        if sanitize_origin and base_title:
            base_title = cls.clean_origin_from_text(base_title, origin_spec)
        resolved_title = base_title or dest_spec.display_name
        return (
            template.replace("{orig_title}", resolved_title)
            .replace("{title}", resolved_title)
            .replace("{origin_generation}", orig_gen_tok)
            .replace("{generation}", gen_tok)
            .replace("{origin}", orig_tok)
            .replace("{display_name}", dest_spec.display_name)
            .replace("{survivor_id}", dest_spec.survivor_id)
            .replace("{survivor}", surv_tok)
        )

    @classmethod
    def _build_target_metadata(
        cls,
        base: ModMetadata,
        origin_spec: SurvivorSpec,
        dest_spec: SurvivorSpec,
        sanitize_origin: bool = True,
    ) -> ModMetadata:
        orig_title = base.original_title or base.title or "Swapped Survivor Skin"
        if sanitize_origin:
            orig_title = cls.clean_origin_from_text(orig_title, origin_spec)
        title = base.title or "Swapped Survivor Skin"
        tokens = (
            "{survivor}",
            "{display_name}",
            "{survivor_id}",
            "{origin}",
            "{orig_title}",
            "{title}",
            "{generation}",
            "{origin_generation}",
        )
        if any(token in title for token in tokens):
            title = cls.render_placeholders(
                title,
                origin_spec,
                dest_spec,
                orig_title=orig_title,
                for_filename=False,
                sanitize_origin=sanitize_origin,
            )
        elif sanitize_origin:
            cleaned = cls.clean_origin_from_text(title, origin_spec)
            title = f"{cleaned} ({dest_spec.display_name})"
        elif re.search(rf"\b{re.escape(origin_spec.display_name)}\b", title, re.IGNORECASE):
            title = re.sub(
                rf"\b{re.escape(origin_spec.display_name)}\b",
                dest_spec.display_name,
                title,
                flags=re.IGNORECASE,
            )
        else:
            title = f"{title} ({dest_spec.display_name})"

        desc = base.description or ""
        if desc:
            if any(token in desc for token in tokens):
                desc = cls.render_placeholders(
                    desc,
                    origin_spec,
                    dest_spec,
                    orig_title=orig_title,
                    for_filename=False,
                    sanitize_origin=sanitize_origin,
                )
            elif re.search(rf"\b{re.escape(origin_spec.display_name)}\b", desc, re.IGNORECASE):
                desc = re.sub(
                    rf"\b{re.escape(origin_spec.display_name)}\b",
                    dest_spec.display_name,
                    desc,
                    flags=re.IGNORECASE,
                )
        else:
            desc = f"Ported from {origin_spec.display_name} to {dest_spec.display_name} via L4D2 Survivor Swapper Tool."

        return ModMetadata(
            title=title,
            version=base.version,
            description=desc,
            author=base.author,
            author_steam_id=base.author_steam_id,
            url=base.url,
            steam_app_id=base.steam_app_id,
            extra_fields=dict(base.extra_fields),
            original_title=orig_title,
        )

    @staticmethod
    def _find_case_insensitive_rel(base_dir: Path, rel_path: str) -> Optional[Path]:
        current = base_dir
        for part in PurePosixPath(rel_path).parts:
            if not current.exists() or not current.is_dir():
                return None
            part_lower = part.lower()
            match = next((p for p in current.iterdir() if p.name.lower() == part_lower), None)
            if match is None:
                return None
            current = match
        return current if current.exists() else None

    @staticmethod
    def _find_case_insensitive_file(directory: Path, filename: str) -> Optional[Path]:
        if not directory.exists():
            return None
        target = filename.lower()
        return next((p for p in directory.iterdir() if p.is_file() and p.name.lower() == target), None)

    def _find_origin_arms_mdl(self, origin_mod_dir: Path, origin_spec: SurvivorSpec) -> Optional[Path]:
        preferred = self._find_case_insensitive_rel(origin_mod_dir, f"models/weapons/arms/{origin_spec.fp_arms.mdl}")
        if preferred is not None:
            return preferred
        arms_dir = self._find_case_insensitive_rel(origin_mod_dir, "models/weapons/arms")
        if arms_dir is None or not arms_dir.is_dir():
            return None
        for entry in sorted(arms_dir.iterdir()):
            if entry.is_file() and entry.suffix.lower() == ".mdl":
                return entry
        return None

    @staticmethod
    def _read_text_safe(path: Path) -> str:
        raw = path.read_bytes()
        try:
            return raw.decode("utf-8")
        except UnicodeDecodeError:
            return raw.decode("cp1252", errors="replace")

    @classmethod
    def _sanitize_filename(cls, name: str) -> str:
        cleaned = cls._INVALID_FILENAME_CHARS.sub("_", name).strip().rstrip(". ")
        return cleaned or "swapped_survivor"

    @classmethod
    def _format_output_name(
        cls,
        template: str,
        origin_spec: SurvivorSpec,
        dest_spec: SurvivorSpec,
        multi_target: bool = True,
        title: str = "",
        sanitize_origin: bool = True,
    ) -> str:
        text = template.strip() or "swapped_{survivor}"
        tokens = (
            "{survivor}",
            "{display_name}",
            "{survivor_id}",
            "{origin}",
            "{orig_title}",
            "{title}",
            "{generation}",
            "{origin_generation}",
        )
        if any(token in text for token in tokens):
            return cls.render_placeholders(
                text,
                origin_spec,
                dest_spec,
                orig_title=title,
                for_filename=True,
                sanitize_origin=sanitize_origin,
            )
        if not multi_target:
            return text
        if sanitize_origin:
            cleaned = cls.clean_origin_from_text(text, origin_spec)
            if cleaned != text:
                return f"{cleaned}_{dest_spec.id.value}"
        pattern = rf"(?<![A-Za-z0-9]){re.escape(origin_spec.display_name)}(?![A-Za-z0-9])"
        if re.search(pattern, text, re.IGNORECASE):
            return re.sub(
                pattern,
                dest_spec.id.value if text.islower() else dest_spec.display_name,
                text,
                flags=re.IGNORECASE,
            )
        return f"{text} ({dest_spec.display_name})"

    @staticmethod
    def _first_error_line(exc: Exception) -> str:
        text = str(exc).strip()
        return text.splitlines()[0] if text else type(exc).__name__

    @staticmethod
    def _advance_and_emit(progress_cb, msg, dest_id, get_step_fn, total_steps) -> None:
        if progress_cb is None:
            return
        step = get_step_fn()
        pct = min(99, int((step / max(1, total_steps)) * 100))
        progress_cb(
            SwapProgress(
                step=step,
                total_steps=total_steps,
                percent=pct,
                message=msg,
                target=dest_id,
            )
        )
