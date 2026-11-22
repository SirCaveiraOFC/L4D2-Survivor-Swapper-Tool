from __future__ import annotations

from pathlib import PurePosixPath
from typing import Iterable, Optional

from core.models import FpArmsFiles, SurvivorId, SurvivorSpec, VguiIconFiles


class SurvivorRegistry:
    """Registry and lookup helpers for all 8 Left 4 Dead survivors."""

    _SPECS: dict[SurvivorId, SurvivorSpec] = {
        SurvivorId.BILL: SurvivorSpec(
            id=SurvivorId.BILL,
            display_name="Bill",
            generation="L4D1",
            survivor_id="survivor_namvet",
            model_file="survivor_namvet.mdl",
            anims_folder="survivor_namvet_anims",
            kit_folder="replace_bill",
            default_includemodels=(
                '$includemodel "survivors/anim_namvet.mdl"',
                '$includemodel "survivors/gestures_namvet.mdl"',
            ),
            fp_arms=FpArmsFiles(
                dx90_vtx="v_arms_bill.dx90.vtx",
                mdl="v_arms_bill.mdl",
                vvd="v_arms_bill.vvd",
            ),
            vgui=VguiIconFiles(
                lobby_icon="select_bill.vtf",
                in_game_icon="s_panel_namvet.vtf",
                incap_icon="s_panel_namvet_incap.vtf",
            ),
        ),
        SurvivorId.ZOEY: SurvivorSpec(
            id=SurvivorId.ZOEY,
            display_name="Zoey",
            generation="L4D1",
            survivor_id="survivor_teenangst",
            model_file="survivor_teenangst.mdl",
            anims_folder="survivor_teenangst_anims",
            kit_folder="replace_zoey",
            default_includemodels=(
                '$includemodel "survivors/anim_teenangst.mdl"',
                '$includemodel "survivors/gestures_TeenAngst.mdl"',
            ),
            fp_arms=FpArmsFiles(
                dx90_vtx="v_arms_zoey.dx90.vtx",
                mdl="v_arms_zoey.mdl",
                vvd="v_arms_zoey.vvd",
            ),
            vgui=VguiIconFiles(
                lobby_icon="select_zoey.vtf",
                in_game_icon="s_panel_teenangst.vtf",
                incap_icon="s_panel_teenangst_incap.vtf",
            ),
        ),
        SurvivorId.LOUIS: SurvivorSpec(
            id=SurvivorId.LOUIS,
            display_name="Louis",
            generation="L4D1",
            survivor_id="survivor_manager",
            model_file="survivor_manager.mdl",
            anims_folder="survivor_manager_anims",
            kit_folder="replace_louis",
            default_includemodels=(
                '$includemodel "survivors/anim_Biker.mdl"',
                '$includemodel "survivors/gestures_biker.mdl"',
            ),
            fp_arms=FpArmsFiles(
                dx90_vtx="v_arms_louis.dx90.vtx",
                mdl="v_arms_louis.mdl",
                vvd="v_arms_louis.vvd",
            ),
            vgui=VguiIconFiles(
                lobby_icon="select_louis.vtf",
                in_game_icon="s_panel_manager.vtf",
                incap_icon="s_panel_manager_incap.vtf",
            ),
        ),
        SurvivorId.FRANCIS: SurvivorSpec(
            id=SurvivorId.FRANCIS,
            display_name="Francis",
            generation="L4D1",
            survivor_id="survivor_biker",
            model_file="survivor_biker.mdl",
            anims_folder="survivor_biker_anims",
            kit_folder="replace_francis",
            default_includemodels=(
                '$includemodel "survivors/anim_Biker.mdl"',
                '$includemodel "survivors/gestures_biker.mdl"',
            ),
            fp_arms=FpArmsFiles(
                dx90_vtx="v_arms_francis.dx90.vtx",
                mdl="v_arms_francis.mdl",
                vvd="v_arms_francis.vvd",
            ),
            vgui=VguiIconFiles(
                lobby_icon="select_francis.vtf",
                in_game_icon="s_panel_biker.vtf",
                incap_icon="s_panel_biker_incap.vtf",
            ),
        ),
        SurvivorId.NICK: SurvivorSpec(
            id=SurvivorId.NICK,
            display_name="Nick",
            generation="L4D2",
            survivor_id="survivor_gambler",
            model_file="survivor_gambler.mdl",
            anims_folder="survivor_gambler_anims",
            kit_folder="replace_nick",
            default_includemodels=(
                '$includemodel "survivors/anim_gambler.mdl"',
                '$includemodel "survivors/anim_gestures.mdl"',
            ),
            fp_arms=FpArmsFiles(
                dx90_vtx="v_arms_gambler_new.dx90.vtx",
                mdl="v_arms_gambler_new.mdl",
                vvd="v_arms_gambler_new.vvd",
            ),
            vgui=VguiIconFiles(
                lobby_icon="s_panel_lobby_gambler.vtf",
                in_game_icon="s_panel_gambler.vtf",
                incap_icon="s_panel_gambler_incap.vtf",
            ),
        ),
        SurvivorId.ROCHELLE: SurvivorSpec(
            id=SurvivorId.ROCHELLE,
            display_name="Rochelle",
            generation="L4D2",
            survivor_id="survivor_producer",
            model_file="survivor_producer.mdl",
            anims_folder="survivor_producer_anims",
            kit_folder="replace_rochelle",
            default_includemodels=(
                '$includemodel "survivors/anim_producer.mdl"',
                '$includemodel "survivors/anim_gestures.mdl"',
            ),
            fp_arms=FpArmsFiles(
                dx90_vtx="v_arms_producer_new.dx90.vtx",
                mdl="v_arms_producer_new.mdl",
                vvd="v_arms_producer_new.vvd",
            ),
            vgui=VguiIconFiles(
                lobby_icon="s_panel_lobby_producer.vtf",
                in_game_icon="s_panel_producer.vtf",
                incap_icon="s_panel_producer_incap.vtf",
            ),
        ),
        SurvivorId.COACH: SurvivorSpec(
            id=SurvivorId.COACH,
            display_name="Coach",
            generation="L4D2",
            survivor_id="survivor_coach",
            model_file="survivor_coach.mdl",
            anims_folder="survivor_coach_anims",
            kit_folder="replace_coach",
            default_includemodels=(
                '$includemodel "survivors/anim_coach.mdl"',
                '$includemodel "survivors/anim_gestures.mdl"',
            ),
            fp_arms=FpArmsFiles(
                dx90_vtx="v_arms_coach_new.dx90.vtx",
                mdl="v_arms_coach_new.mdl",
                vvd="v_arms_coach_new.vvd",
            ),
            vgui=VguiIconFiles(
                lobby_icon="s_panel_lobby_coach.vtf",
                in_game_icon="s_panel_coach.vtf",
                incap_icon="s_panel_coach_incap.vtf",
            ),
        ),
        SurvivorId.ELLIS: SurvivorSpec(
            id=SurvivorId.ELLIS,
            display_name="Ellis",
            generation="L4D2",
            survivor_id="survivor_mechanic",
            model_file="survivor_mechanic.mdl",
            anims_folder="survivor_mechanic_anims",
            kit_folder="replace_ellis",
            default_includemodels=(
                '$includemodel "survivors/anim_mechanic.mdl"',
                '$includemodel "survivors/anim_gestures.mdl"',
            ),
            fp_arms=FpArmsFiles(
                dx90_vtx="v_arms_mechanic_new.dx90.vtx",
                mdl="v_arms_mechanic_new.mdl",
                vvd="v_arms_mechanic_new.vvd",
            ),
            vgui=VguiIconFiles(
                lobby_icon="s_panel_lobby_mechanic.vtf",
                in_game_icon="s_panel_mechanic.vtf",
                incap_icon="s_panel_mechanic_incap.vtf",
            ),
        ),
    }

    @classmethod
    def get(cls, survivor: SurvivorId | str) -> SurvivorSpec:
        sid = survivor if isinstance(survivor, SurvivorId) else SurvivorId(survivor.lower())
        return cls._SPECS[sid]

    @classmethod
    def all(cls) -> list[SurvivorSpec]:
        return list(cls._SPECS.values())

    @classmethod
    def detect_from_paths(cls, paths: Iterable[str]) -> Optional[SurvivorId]:
        """Auto-detect which survivor a mod replaces from its internal asset paths."""
        normalized = [p.replace("\\", "/").lstrip("./").lower() for p in paths]

        for spec in cls._SPECS.values():
            target = f"models/survivors/{spec.model_file.lower()}"
            if target in normalized:
                return spec.id

        for spec in cls._SPECS.values():
            target = f"models/weapons/arms/{spec.fp_arms.mdl.lower()}"
            if target in normalized:
                return spec.id

        for spec in cls._SPECS.values():
            for vtf_name in spec.vgui.all_filenames():
                target = f"materials/vgui/{vtf_name.lower()}"
                if target in normalized:
                    return spec.id

        return None

    @classmethod
    def match_vgui_slot(cls, filename: str, preferred_origin: Optional[SurvivorId] = None) -> Optional[str]:
        """Return 'lobby_icon', 'in_game_icon', or 'incap_icon' if filename matches a survivor VGUI VTF."""
        lower_name = PurePosixPath(filename).name.lower()
        specs: list[SurvivorSpec] = []
        if preferred_origin is not None:
            specs.append(cls.get(preferred_origin))
        specs.extend(s for s in cls._SPECS.values() if preferred_origin is None or s.id != preferred_origin)

        for spec in specs:
            if lower_name == spec.vgui.lobby_icon.lower():
                return "lobby_icon"
            if lower_name == spec.vgui.in_game_icon.lower():
                return "in_game_icon"
            if lower_name == spec.vgui.incap_icon.lower():
                return "incap_icon"
        return None

    @classmethod
    def all_known_survivor_model_stems(cls) -> set[str]:
        """Return stems for main and _light models of all 8 survivors."""
        stems = set()
        for spec in cls._SPECS.values():
            stems.add(spec.survivor_id.lower())
            stems.add(f"{spec.survivor_id.lower()}_light")
        return stems
