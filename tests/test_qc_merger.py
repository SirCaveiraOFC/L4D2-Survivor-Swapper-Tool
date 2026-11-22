from __future__ import annotations

from pathlib import Path

from core.models import SurvivorId
from core.qc_merger import QcMerger
from core.qc_parser import QcParser
from core.survivors import SurvivorRegistry


def test_merge_origin_with_model_no_phy_and_stale_weightlist() -> None:
    origin_qc = """
$modelname "survivors/survivor_manager.mdl"
$model "Roboco" "roboco.smd" {
    eyeball "eye_right" "ValveBiped.Bip01_Head1" -1.1 -2.3 62.0 "eyeball_r" 1 4 "iris" 0.6
}
$cdmaterials "models/roboco/"
$jigglebone "hair_jiggle" {
    is_flexible {
        length 20
        tip_mass 0
        pitch_stiffness 100
        yaw_stiffness 100
    }
}
$weightlist "weights_Idle_Standing_Align" {
    "ValveBiped.hlp_r_trap" 1
}
$weightlist "weights_Used" {
    "ValveBiped.Bip01_Pelvis" 1
}
$animation "a_proportions" "anims/proportions.smd" {
    fps 30
}
$sequence "RobocoIdle" {
    "anims/idle.smd"
    fps 30
    weightlist "weights_Used"
    ikrule "rfoot" footstep
}
$sequence "ragdoll" {
    "anims/ragdoll.smd"
    activity "ACT_DIERAGDOLL" 1
    fps 30
}
$includemodel "survivors/anim_producer.mdl"
$includemodel "survivors/anim_Biker.mdl"
"""

    kit_qc = """
$modelname "survivors/survivor_mechanic.mdl"
$ikchain "rfoot" "ValveBiped.Bip01_R_Foot" knee 0.7 0.7 0
$weightlist "weights_Idle_Standing_Align" {
    "ValveBiped.hlp_r_trap" 1
}
$sequence "Mechanic" {
    "survivor_mechanic_anims/Mechanic.smd"
    fps 30
}
$declaresequence "Idle_Standing"
$declaresequence "Calm_Run"
$sequence "ragdoll" {
    "survivor_mechanic_anims/ragdoll.smd"
    activity "ACT_DIERAGDOLL" 1
}
$includemodel "survivors/anim_biker.mdl"
$includemodel "survivors/anim_mechanic.mdl"
$includemodel "survivors/anim_gestures.mdl"
$collisionjoints "survivor_mechanic_physics.smd" {
    $mass 100.0
}
"""

    origin_spec = SurvivorRegistry.get(SurvivorId.LOUIS)
    dest_spec = SurvivorRegistry.get(SurvivorId.ELLIS)

    result = QcMerger.merge_survivor_qc(origin_qc, kit_qc, origin_spec, dest_spec)

    assert not result.used_kit_ragdoll
    assert not result.has_collision_joints

    merged_doc = QcParser.parse(result.qc_text)
    assert merged_doc.find_first("$modelname").first_quoted_arg() == "survivors/survivor_mechanic.mdl"
    assert merged_doc.find_first("$model") is not None
    assert merged_doc.find_first("$jigglebone") is not None

    wl_names = {st.first_quoted_arg() for st in merged_doc.find_all("$weightlist")}
    assert wl_names == {"weights_Used"}

    ik_names = {(st.first_quoted_arg() or "").lower() for st in merged_doc.find_all("$ikchain")}
    assert "rfoot" in ik_names

    assert len(merged_doc.find_all("$collisionjoints")) == 0

    includes = [st.first_quoted_arg() for st in merged_doc.find_all("$includemodel")]
    assert includes == [
        "survivors/anim_producer.mdl",
        "survivors/anim_Biker.mdl",
        "survivors/anim_mechanic.mdl",
        "survivors/anim_gestures.mdl",
    ]

    decl_idx = result.qc_text.index("$declaresequence")
    slot0_idx = result.qc_text.index('"RobocoIdle"')
    assert slot0_idx < decl_idx


def test_merge_borrows_ragdoll_and_builds_slot0_when_origin_only_has_ragdoll() -> None:
    origin_qc = """
$modelname "survivors/survivor_teenangst.mdl"
$body "body" "ref.smd"
$cdmaterials "models/emma/"
$sequence "ragdoll" {
    "emma_anims/ragdoll.smd"
    fps 30
}
"""
    kit_qc = """
$modelname "survivors/survivor_coach.mdl"
$sequence "Coach" {
    "survivor_coach_anims/Coach.smd"
    fps 30
}
$declaresequence "WalkN"
$sequence "ragdoll" {
    "survivor_coach_anims/ragdoll.smd"
    fps 30
}
$includemodel "survivors/anim_coach.mdl"
$includemodel "survivors/anim_gestures.mdl"
"""
    res = QcMerger.merge_survivor_qc(
        origin_qc,
        kit_qc,
        SurvivorRegistry.get(SurvivorId.ZOEY),
        SurvivorRegistry.get(SurvivorId.COACH),
    )
    assert not res.used_kit_ragdoll
    assert '$sequence "CustomCoach"' in res.qc_text
    assert '$declaresequence "WalkN"' in res.qc_text
    assert res.qc_text.index('$sequence "CustomCoach"') < res.qc_text.index('$declaresequence "WalkN"')


def test_merge_borrows_kit_ragdoll_when_origin_missing_ragdoll() -> None:
    origin_qc = """
$modelname "survivors/survivor_teenangst.mdl"
$body "body" "ref.smd"
$sequence "EmmaIdle" {
    "emma_anims/idle.smd"
    fps 30
}
"""
    kit_qc = """
$modelname "survivors/survivor_namvet.mdl"
$sequence "NamVet" { "idle.smd" fps 30 }
$declaresequence "WalkN"
$sequence "ragdoll" { "ragdoll.smd" fps 30 }
$includemodel "survivors/anim_namvet.mdl"
"""
    res = QcMerger.merge_survivor_qc(
        origin_qc,
        kit_qc,
        SurvivorRegistry.get(SurvivorId.ZOEY),
        SurvivorRegistry.get(SurvivorId.BILL),
    )
    assert res.used_kit_ragdoll
    assert '$sequence "ragdoll"' in res.qc_text


def test_rewrite_arms_qc_updates_modelname() -> None:
    arms_qc = """
$modelname "weapons/arms/v_arms_zoey.mdl"
$body "studio" "v_arms_zoey_ref.smd"
$cdmaterials "models/v_arms/"
"""
    rewritten = QcMerger.rewrite_arms_qc(arms_qc, SurvivorRegistry.get(SurvivorId.ELLIS))
    assert '$modelname "weapons/arms/v_arms_mechanic_new.mdl"' in rewritten
    assert '$body "studio" "v_arms_zoey_ref.smd"' in rewritten


def test_kit_ellis_qc_uses_anim_mechanic_if_present() -> None:
    kit_ellis_qc = Path("HUNK'S_SURVIVOR_SWAP_KIT") / "replace_ellis" / "survivor_mechanic.qc"
    if kit_ellis_qc.exists():
        content = kit_ellis_qc.read_text(encoding="utf-8", errors="ignore")
        assert "anim_mechanic.mdl" in content.lower()


def _make_sample_smd(path: Path, tri_materials: list[str]) -> None:
    lines = [
        "version 1",
        "nodes",
        '  0 "root" -1',
        "end",
        "skeleton",
        "time 0",
        "  0 0 0 0 0 0 0",
        "end",
        "triangles",
    ]
    for idx, mat in enumerate(tri_materials):
        x = float(idx)
        lines.append(mat)
        lines.append(f"  0 {x:.6f} 0.0 0.0 0.0 0.0 1.0 0.0 0.0 1 0 1.0")
        lines.append(f"  0 {x:.6f} 1.0 0.0 0.0 0.0 1.0 1.0 0.0 1 0 1.0")
        lines.append(f"  0 {x:.6f} 0.0 1.0 0.0 0.0 1.0 0.0 1.0 1 0 1.0")
    lines.append("end")
    path.write_text("\n".join(lines) + "\n", encoding="utf-8", newline="\n")


def test_smd_splitter_splits_oversized_bodygroup_and_cleans_lod(tmp_path: Path) -> None:
    from core.smd_splitter import SmdSplitter

    smd_path = tmp_path / "shenti.smd"
    _make_sample_smd(smd_path, ["mat_a"] * 7)
    qc_path = tmp_path / "test.qc"
    qc_path.write_text(
        '$modelname "survivors/survivor_gambler.mdl"\n'
        '$bodygroup "body1"\n'
        "{\n"
        '\tstudio "shenti.smd"\n'
        "}\n"
        "$lod 20\n"
        "{\n"
        '\treplacemodel "shenti.smd" "shenti_lod1.smd"\n'
        '\treplacemodel "other.smd" "other_lod1.smd"\n'
        "}\n"
        "$lod 40\n"
        "{\n"
        '\treplacemodel "shenti.smd" "shenti_lod2.smd"\n'
        "}\n",
        encoding="utf-8",
    )

    logs = SmdSplitter.prepare_qc_for_studiomdl(qc_path, max_tris=3)
    assert len(logs) == 1
    assert (tmp_path / "shenti_part0.smd").exists()
    assert (tmp_path / "shenti_part1.smd").exists()
    assert (tmp_path / "shenti_part2.smd").exists()

    updated_qc = qc_path.read_text(encoding="utf-8")
    assert '$body "body1_p0" "shenti_part0.smd"' in updated_qc
    assert '$body "body1_p1" "shenti_part1.smd"' in updated_qc
    assert '$body "body1_p2" "shenti_part2.smd"' in updated_qc
    assert "shenti_lod1.smd" not in updated_qc
    assert 'replacemodel "other.smd" "other_lod1.smd"' in updated_qc
    assert "$lod 40" not in updated_qc


def test_smd_splitter_splits_model_preserving_vta_flex_materials(tmp_path: Path) -> None:
    from core.smd_splitter import SmdSplitter

    smd_path = tmp_path / "merged_model.smd"
    _make_sample_smd(smd_path, ["face_mat", "face_mat", "dress_mat", "dress_mat", "dress_mat", "hair_mat"])

    vta_path = tmp_path / "face.vta"
    vta_path.write_text(
        "version 1\n"
        "nodes\n"
        '  0 "root" -1\n'
        "end\n"
        "skeleton\n"
        "time 0\n"
        "  0 0 0 0 0 0 0\n"
        "end\n"
        "vertexanimation\n"
        "time 0\n"
        "  0 0.000000 0.0 0.0 0 0 1\n"
        "  1 2.000000 0.0 0.0 0 0 1\n"
        "time 1\n"
        "  0 0.050000 0.0 0.0 0 0 1\n"
        "end\n",
        encoding="utf-8",
    )

    qc_path = tmp_path / "model.qc"
    qc_path.write_text(
        '$modelname "survivors/survivor_gambler.mdl"\n'
        '$model "Survivor" "merged_model.smd" {\n'
        '\tflexfile "face.vta"\n'
        "\t{\n"
        "\t\tdefaultflex frame 0\n"
        "\t}\n"
        "}\n",
        encoding="utf-8",
    )

    logs = SmdSplitter.prepare_qc_for_studiomdl(qc_path, max_tris=2)
    assert len(logs) == 1
    updated_qc = qc_path.read_text(encoding="utf-8")
    assert '$model "Survivor" "merged_model_part0.smd"' in updated_qc
    assert '$body "Survivor_p1" "merged_model_part1.smd"' in updated_qc
    assert '$body "Survivor_p2" "merged_model_part2.smd"' in updated_qc
    part0 = (tmp_path / "merged_model_part0.smd").read_text(encoding="utf-8")
    part1 = (tmp_path / "merged_model_part1.smd").read_text(encoding="utf-8")
    assert "face_mat" in part0 and "dress_mat" not in part0
    assert "dress_mat" in part1 and "face_mat" not in part1
