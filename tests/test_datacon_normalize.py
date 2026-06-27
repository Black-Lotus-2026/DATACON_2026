from datacon_agent.domains import NOT_DETECTED, get_domain
from datacon_agent.normalize import (
    canonicalize_numeric_text,
    canonicalize_text,
    finalize_samples,
    normalize_samples,
    samples_to_frame,
)


def test_synergy_aliases_are_mapped_to_evaluator_columns() -> None:
    domain = get_domain("synergy")
    rows = normalize_samples(
        domain,
        {
            "samples": [
                {
                    "NP": "Ag",
                    "Bacteria": "E. coli",
                    "ZOI_drug_mm_or_MIC_µg_ml": 12.5,
                    "drug": "",
                }
            ]
        },
    )

    assert rows[0]["bacteria"] == "E. coli"
    assert rows[0]["ZOI_drug_mm_or_MIC _µg_ml"] == 12.5
    assert rows[0]["drug"] == NOT_DETECTED
    assert set(rows[0]) == set(domain.columns)


def test_pdf_identifier_matches_domain_contract() -> None:
    synergy = get_domain("synergy")
    benzimidazole = get_domain("benzimidazole")

    assert samples_to_frame(synergy, [], pdf_name="paper.pdf")["pdf"].empty

    synergy_frame = samples_to_frame(synergy, [{"NP": "Ag"}], pdf_name="paper.pdf")
    benzimidazole_frame = samples_to_frame(
        benzimidazole,
        [{"compound_id": "5a"}],
        pdf_name="paper.pdf",
    )

    assert synergy_frame.loc[0, "pdf"] == "paper.pdf"
    assert benzimidazole_frame.loc[0, "pdf"] == "paper"


def test_pdf_identifier_adds_extension_for_nanoparticle_single_agent_stems() -> None:
    synergy = get_domain("synergy")

    frame = samples_to_frame(synergy, [{"NP": "Ag"}], pdf_name="11_fbioe-09-652362")

    assert frame.loc[0, "pdf"] == "11_fbioe-09-652362.pdf"


def test_nanozyme_finalize_drops_setup_rows_when_kinetic_rows_exist() -> None:
    domain = get_domain("nanozymes")

    rows = finalize_samples(
        domain,
        [
            {"formula": "Ir", "reaction_type": "TMB + H2O2", "km_value": 0.12},
            {"formula": "Ir", "reaction_type": "H2O2", "km_value": "NOT_DETECTED", "vmax_value": "NOT_DETECTED"},
        ],
    )

    assert len(rows) == 1
    assert rows[0]["reaction_type"] == "TMB + H2O2"


def test_text_canonicalization_handles_common_unit_variants() -> None:
    assert canonicalize_text("10^-8 M s^-1") == "10-8 M s-1"
    assert canonicalize_text("μg mL^-1") == "μg mL−1"
    assert canonicalize_text("α-Fe2O3@CoNi") == "Fe2O3@CoNi"


def test_numeric_text_canonicalization_keeps_ranges_but_cleans_uncertainty() -> None:
    assert canonicalize_numeric_text("length", "20-30") == "20-30"
    assert canonicalize_numeric_text("length", "89.8 ± 7.9") == "89.8"
    assert canonicalize_numeric_text("length", "~800") == "800"
    assert canonicalize_numeric_text("temperature", "room temperature") == "NOT_DETECTED"
    assert canonicalize_numeric_text("vmax_value", "13.5 × 10⁻⁸") == "1.35e-07"


def test_nanozyme_condition_integers_keep_decimal_form() -> None:
    domain = get_domain("nanozymes")

    rows = normalize_samples(
        domain,
        {
            "samples": [
                {
                    "temperature": "25",
                    "ph": "6",
                    "c_min": "25",
                    "c_max": "200",
                    "ccat_value": "10",
                    "length": "800",
                    "width": "20-30",
                }
            ]
        },
    )

    assert rows[0]["temperature"] == "25.0"
    assert rows[0]["ph"] == "6.0"
    assert rows[0]["c_min"] == "25.0"
    assert rows[0]["c_max"] == "200.0"
    assert rows[0]["ccat_value"] == "10.0"
    assert rows[0]["length"] == "800"
    assert rows[0]["width"] == "20-30"
