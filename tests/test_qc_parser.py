from __future__ import annotations

from core.qc_parser import QcParser


SAMPLE_COMPLEX_QC = """
// Leading comment about model $ignored
$modelname "survivors/survivor_teenangst.mdl"

/* Block comment mentioning $sequence "fake" {
   and unbalanced braces {{{
} */

$model "Emma" "emma_ref.smd" {
    eyeball "eye_right" "ValveBiped.Bip01_Head1" -1.2 -2.4 64.0 "eye_r" 1 4 "iris" 0.6
    flexfile "emma.vta"
    {
        defaultflex frame 0
        flex "blink" frame 1
    }
    flexcontroller eyes range -45 45 "eyes_updown"
    %blink = blink
}

$bodygroup "hair"
{
    studio "hair_main.smd"
    blank
}

$cdmaterials "models/custom/{emma}/$skin/" // trailing comment
$surfaceprop "flesh"

$sequence "EmmaPose"
{
    "emma_anims/idle.smd"
    fadein 0.2
    fadeout 0.2
    fps 30
    ikrule "lhand" release
}

$declaresequence "Calm_Idle"

$includemodel "survivors/anim_TeenAngst.mdl"
"""


def test_qc_parser_handles_nested_braces_quotes_and_comments() -> None:
    doc = QcParser.parse(SAMPLE_COMPLEX_QC)

    assert doc.find_first("$modelname") is not None
    assert doc.find_first("$modelname").first_quoted_arg() == "survivors/survivor_teenangst.mdl"

    model_stmt = doc.find_first("$model")
    assert model_stmt is not None
    assert model_stmt.has_block
    assert model_stmt.first_quoted_arg() == "Emma"
    assert "flexfile" in model_stmt.body_text()
    assert "%blink = blink" in model_stmt.body_text()

    cdmat = doc.find_first("$cdmaterials")
    assert cdmat is not None
    assert cdmat.first_quoted_arg() == "models/custom/{emma}/$skin/"

    seq = doc.find_first("$sequence")
    assert seq is not None
    assert seq.first_quoted_arg() == "EmmaPose"
    assert 'ikrule "lhand" release' in seq.body_text()

    decl = doc.find_first("$declaresequence")
    assert decl is not None
    assert decl.first_quoted_arg() == "Calm_Idle"

    assert len(doc.find_all("$includemodel")) == 1
    assert len(doc.find_all("$ignored")) == 0
    assert len(doc.find_all("$sequence")) == 1

    roundtrip = doc.to_text()
    assert '$model "Emma" "emma_ref.smd"' in roundtrip
    assert '$declaresequence "Calm_Idle"' in roundtrip
