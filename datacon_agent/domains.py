from __future__ import annotations

from dataclasses import dataclass


NOT_DETECTED = "NOT_DETECTED"


@dataclass(frozen=True)
class FieldSpec:
    name: str
    kind: str
    description: str
    enum: tuple[str, ...] = ()


@dataclass(frozen=True)
class DomainSpec:
    key: str
    title: str
    hf_dataset: str
    task: str
    fields: tuple[FieldSpec, ...]
    numeric_fields: tuple[str, ...] = ()
    smiles_fields: tuple[str, ...] = ()
    guidance: tuple[str, ...] = ()

    @property
    def columns(self) -> list[str]:
        return [field.name for field in self.fields]


SMALL_MOLECULE_FIELDS = (
    FieldSpec("compound_id", "string", "Article-local compound identifier."),
    FieldSpec("smiles", "string", "Full SMILES for the extracted antibiotic molecule."),
    FieldSpec("target_type", "string", "Measurement type, usually MIC or pMIC."),
    FieldSpec("target_relation", "string", "Relation sign for the measurement.", ("=", "<", ">")),
    FieldSpec("target_value", "number", "Numeric MIC or pMIC value."),
    FieldSpec("target_units", "string", "Units exactly as reported for MIC-like values."),
    FieldSpec("bacteria", "string", "Bacterium or strain name exactly as reported."),
)


DOMAINS: dict[str, DomainSpec] = {
    "benzimidazole": DomainSpec(
        key="benzimidazole",
        title="Benzimidazoles",
        hf_dataset="ai-chem/Benzimidazoles",
        task=(
            "Extract every MIC or pMIC measurement for benzimidazole antibiotics. "
            "Focus on Staphylococcus aureus and Escherichia coli when the article contains "
            "many organisms, and keep every distinct measurement as a separate row."
        ),
        fields=SMALL_MOLECULE_FIELDS,
        numeric_fields=("target_value",),
        smiles_fields=("smiles",),
    ),
    "oxazolidinone": DomainSpec(
        key="oxazolidinone",
        title="Oxazolidinones",
        hf_dataset="ai-chem/Oxazolidinones",
        task=(
            "Extract every MIC or pMIC measurement for oxazolidinone antibiotics. "
            "Keep each compound-organism-measurement mention as a separate row."
        ),
        fields=SMALL_MOLECULE_FIELDS,
        numeric_fields=("target_value",),
        smiles_fields=("smiles",),
    ),
    "cocrystals": DomainSpec(
        key="cocrystals",
        title="Co-crystals",
        hf_dataset="ai-chem/Co-crystals",
        task=(
            "Extract every photostability result for pharmaceutical co-crystals, including "
            "the drug, coformer, molar ratio, and whether photostability increases, decreases, "
            "or does not change."
        ),
        fields=(
            FieldSpec("name_cocrystal", "string", "Name or abbreviation of the co-crystal."),
            FieldSpec("ratio_cocrystal", "string", "Molar ratio of co-crystal components."),
            FieldSpec("name_drug", "string", "Drug component name."),
            FieldSpec("SMILES_drug", "string", "Full SMILES for the drug."),
            FieldSpec("name_coformer", "string", "Coformer component name."),
            FieldSpec("SMILES_coformer", "string", "Full SMILES for the coformer."),
            FieldSpec(
                "photostability_change",
                "string",
                "Photostability trend compared with the reference drug.",
                ("decrease", "does not change", "increase"),
            ),
        ),
        smiles_fields=("SMILES_drug", "SMILES_coformer"),
    ),
    "eyedrops": DomainSpec(
        key="eyedrops",
        title="EyeDrops",
        hf_dataset="ai-chem/EyeDrops",
        task=(
            "Extract ophthalmic drug or small-molecule corneal permeability records. "
            "Keep each compound as a separate row with the reported compound name, SMILES, "
            "corneal permeability perm (cm/s), and logP/lipophilicity when available."
        ),
        fields=(
            FieldSpec("smiles", "string", "Full SMILES for the ophthalmic compound."),
            FieldSpec("name", "string", "Compound or drug name exactly as reported."),
            FieldSpec(
                "perm (cm/s)",
                "number",
                "Corneal permeability value in cm/s or log permeability as reported.",
            ),
            FieldSpec("logP", "number", "Reported logP/lipophilicity value."),
        ),
        numeric_fields=("perm (cm/s)", "logP"),
        smiles_fields=("smiles",),
        guidance=(
            "Do not convert between raw permeability and log permeability unless the article explicitly gives the conversion.",
            "Prefer values from tables of corneal permeability, epithelial permeability, or ophthalmic absorption experiments.",
            "When several permeability measurements are reported for the same compound, keep distinct experimental records as separate rows.",
        ),
    ),
    "complexes": DomainSpec(
        key="complexes",
        title="Complexes",
        hf_dataset="ai-chem/Complexes",
        task=(
            "Extract organometallic complexes or chelate ligands with thermodynamic "
            "stability constants lgK/logK. Extract the ligand environment SMILES without "
            "the metal atom when a complete complex is shown."
        ),
        fields=(
            FieldSpec("compound_id", "string", "Article-local complex or ligand identifier."),
            FieldSpec("compound_name", "string", "Abbreviated or full complex/ligand name."),
            FieldSpec("SMILES", "string", "Full SMILES for the ligand or ligand environment."),
            FieldSpec("SMILES_type", "string", "Whether SMILES describes ligand or environment.", ("ligand", "environment")),
            FieldSpec("target", "number", "Numeric lgK/logK stability constant."),
        ),
        numeric_fields=("target",),
        smiles_fields=("SMILES",),
    ),
    "nanozymes": DomainSpec(
        key="nanozymes",
        title="Nanozymes",
        hf_dataset="ai-chem/Nanozymes",
        task=(
            "Extract every nanozyme catalytic experiment, including material identity, "
            "dimensions, surface, kinetic parameters, assay concentrations, pH, and temperature."
        ),
        fields=(
            FieldSpec("formula", "string", "Nanozyme chemical formula."),
            FieldSpec("activity", "string", "Catalytic activity type."),
            FieldSpec("syngony", "string", "Crystal system or amorphous state."),
            FieldSpec("length", "number", "Particle length in nm."),
            FieldSpec("width", "number", "Particle width in nm."),
            FieldSpec("depth", "number", "Particle depth in nm."),
            FieldSpec("surface", "string", "Surface molecule, coating, or naked surface."),
            FieldSpec("km_value", "number", "Michaelis constant value."),
            FieldSpec("km_unit", "string", "Unit for Michaelis constant."),
            FieldSpec("vmax_value", "number", "Maximum reaction rate value."),
            FieldSpec("vmax_unit", "string", "Unit for maximum reaction rate."),
            FieldSpec("reaction_type", "string", "Substrate/co-substrate reaction, e.g. TMB + H2O2."),
            FieldSpec("c_min", "number", "Minimum substrate concentration in mM when reported."),
            FieldSpec("c_max", "number", "Maximum substrate concentration in mM when reported."),
            FieldSpec("c_const", "number", "Constant co-substrate concentration."),
            FieldSpec("c_const_unit", "string", "Unit for constant co-substrate concentration."),
            FieldSpec("ccat_value", "number", "Catalyst concentration value."),
            FieldSpec("ccat_unit", "string", "Catalyst concentration unit."),
            FieldSpec("ph", "number", "Assay pH."),
            FieldSpec("temperature", "number", "Assay temperature in Celsius."),
        ),
        numeric_fields=(
            "length",
            "width",
            "depth",
            "km_value",
            "vmax_value",
            "c_min",
            "c_max",
            "c_const",
            "ccat_value",
            "ph",
            "temperature",
        ),
        guidance=(
            "For formula, output the material formula/core only, not generic words such as NPs, nanoparticles, nanozyme, or catalyst.",
            "For activity, use the enzyme family name without '-like' when the article says peroxidase-like, oxidase-like, catalase-like, and similar.",
            "For Michaelis-Menten tables with separate substrate columns, create one row per varied substrate column and keep km_value and vmax_value from the same column.",
            "For reaction_type, put the varied substrate first and the fixed co-substrate second when the method makes this clear, for example H2O2 + TMB or TMB + H2O2.",
            "For length, width, and depth, preserve reported ranges such as 20-30 instead of splitting them into separate minimum and maximum values.",
            "For c_const and c_const_unit, use the fixed co-substrate concentration from the kinetic experiment method; c_const_unit is only the unit such as mM, not the substrate name.",
            "For vmax_unit, copy the unit from the kinetic table header, for example μM min-1, nM s-1, 10-8 M s-1, or M s-1.",
            "For pH and temperature, use the kinetic assay conditions adopted for subsequent measurements, not the optimum-search ranges unless those are the final assay conditions.",
            "When the article or supplement provides supporting information, inspect tables and captions there before marking kinetic values as NOT_DETECTED.",
            "Ignore reference/comparison catalysts in benchmarking tables unless they are the material studied in this article; rows labelled Ref. or literature controls are not target records.",
            "Merge complementary rows for the same material, activity, and reaction_type instead of returning separate setup-only and result-only rows.",
            "Drop setup-only rows that describe assay conditions but contain no extracted target measurement such as kinetic constants, size, or other domain property.",
        ),
    ),
    "magnetic": DomainSpec(
        key="magnetic",
        title="Nanomag",
        hf_dataset="ai-chem/Nanomag",
        task=(
            "Extract magnetic and biomedical properties of magnetic nanoparticles, including "
            "core/shell composition, particle sizes, magnetic measurements, hyperthermia, and MRI relaxivity."
        ),
        fields=(
            FieldSpec("name", "string", "Nanoparticle name."),
            FieldSpec("np_core", "string", "Nanoparticle core composition."),
            FieldSpec("np_shell", "string", "First shell or coating."),
            FieldSpec("core_shell_formula", "string", "Core-shell formula."),
            FieldSpec("np_shell_2", "string", "Second shell or coating."),
            FieldSpec("np_hydro_size", "number", "Hydrodynamic size."),
            FieldSpec("xrd_scherrer_size", "number", "XRD Scherrer size."),
            FieldSpec("emic_size", "number", "Electron microscopy size."),
            FieldSpec("space_group_core", "string", "Core space group."),
            FieldSpec("space_group_shell", "string", "Shell space group."),
            FieldSpec("squid_sat_mag", "number", "SQUID saturation magnetization."),
            FieldSpec("squid_rem_mag", "number", "SQUID remanent magnetization."),
            FieldSpec("exchange_bias_shift_Oe", "number", "Exchange-bias shift in Oe."),
            FieldSpec("vertical_loop_shift_M_vsl_emu_g", "number", "Vertical loop shift."),
            FieldSpec("hc_kOe", "number", "Coercive field in kOe."),
            FieldSpec("squid_h_max", "number", "Maximum SQUID field."),
            FieldSpec("zfc_h_meas", "number", "ZFC measurement field."),
            FieldSpec("instrument", "string", "Measurement instrument."),
            FieldSpec("fc_field_T", "number", "Field-cooling field in T."),
            FieldSpec("squid_temperature", "number", "SQUID measurement temperature."),
            FieldSpec("coercivity", "number", "Coercivity."),
            FieldSpec("htherm_sar", "number", "Hyperthermia SAR."),
            FieldSpec("mri_r1", "number", "MRI r1 relaxivity."),
            FieldSpec("mri_r2", "number", "MRI r2 relaxivity."),
        ),
        numeric_fields=(
            "np_hydro_size",
            "xrd_scherrer_size",
            "emic_size",
            "squid_sat_mag",
            "squid_rem_mag",
            "exchange_bias_shift_Oe",
            "vertical_loop_shift_M_vsl_emu_g",
            "hc_kOe",
            "squid_h_max",
            "zfc_h_meas",
            "fc_field_T",
            "squid_temperature",
            "coercivity",
            "htherm_sar",
            "mri_r1",
            "mri_r2",
        ),
    ),
    "cytotoxicity": DomainSpec(
        key="cytotoxicity",
        title="Cytotox",
        hf_dataset="ai-chem/Cytotox",
        task=(
            "Extract cytotoxicity experiments for nanoparticles, including material, "
            "cell metadata, assay, exposure time, concentration, and viability percentage."
        ),
        fields=(
            FieldSpec("material", "string", "Nanomaterial identity."),
            FieldSpec("shape", "string", "Particle shape."),
            FieldSpec("coat_functional_group", "string", "Coating or functional group."),
            FieldSpec("synthesis_method", "string", "Synthesis method."),
            FieldSpec("surface_charge", "string", "Surface charge class.", ("Negative", "Neutral", "Positive")),
            FieldSpec("core_nm", "number", "Core size in nm."),
            FieldSpec("size_in_medium_nm", "number", "Size in assay medium in nm."),
            FieldSpec("hydrodynamic_nm", "number", "Hydrodynamic diameter in nm."),
            FieldSpec("potential_mv", "number", "Zeta potential in mV."),
            FieldSpec("zeta_in_medium_mv", "number", "Zeta potential in medium in mV."),
            FieldSpec("no_of_cells_cells_well", "number", "Cells per well."),
            FieldSpec("human_animal", "string", "Human or animal cell source.", ("H", "A")),
            FieldSpec("cell_source", "string", "Cell source/species."),
            FieldSpec("cell_tissue", "string", "Cell tissue."),
            FieldSpec("cell_morphology", "string", "Cell morphology."),
            FieldSpec("cell_age", "string", "Cell age or passage."),
            FieldSpec("time_hr", "number", "Exposure time in hours."),
            FieldSpec("concentration", "number", "Nanoparticle concentration."),
            FieldSpec("test", "string", "Cytotoxicity assay."),
            FieldSpec("test_indicator", "string", "Assay indicator/dye."),
            FieldSpec("viability_%", "number", "Cell viability percentage."),
        ),
        numeric_fields=(
            "core_nm",
            "size_in_medium_nm",
            "hydrodynamic_nm",
            "potential_mv",
            "zeta_in_medium_mv",
            "no_of_cells_cells_well",
            "time_hr",
            "concentration",
            "viability_%",
        ),
    ),
    "seltox": DomainSpec(
        key="seltox",
        title="SelTox",
        hf_dataset="ai-chem/SelTox",
        task=(
            "Extract antimicrobial activity and toxicity measurements for silver or other "
            "nanoparticles, including synthesis details, organism, assay method, MIC/ZOI, sizes, "
            "shape, zeta potential, and synthesis conditions."
        ),
        fields=(
            FieldSpec("np", "string", "Nanoparticle name."),
            FieldSpec("coating", "string", "Coating indicator or coating material."),
            FieldSpec("bacteria", "string", "Bacterial strain tested."),
            FieldSpec("mdr", "number", "Multidrug-resistant indicator, 0 or 1.", ("0", "1")),
            FieldSpec("strain", "string", "Specific strain identifier."),
            FieldSpec("np_synthesis", "string", "Nanoparticle synthesis method."),
            FieldSpec("method", "string", "Assay method."),
            FieldSpec("mic_np_µg_ml", "number", "Nanoparticle MIC in micrograms per mL."),
            FieldSpec("concentration", "number", "Nanoparticle concentration for ZOI."),
            FieldSpec("zoi_np_mm", "number", "Zone of inhibition in mm."),
            FieldSpec("np_size_min_nm", "number", "Minimum particle size in nm."),
            FieldSpec("np_size_max_nm", "number", "Maximum particle size in nm."),
            FieldSpec("np_size_avg_nm", "number", "Average particle size in nm."),
            FieldSpec("shape", "string", "Particle shape."),
            FieldSpec("time_set_hours", "number", "Assay duration in hours."),
            FieldSpec("zeta_potential_mV", "number", "Zeta potential in mV."),
            FieldSpec("solvent_for_extract", "string", "Solvent used for extract preparation."),
            FieldSpec("temperature_for_extract_C", "number", "Extract preparation temperature in Celsius."),
            FieldSpec("duration_preparing_extract_min", "number", "Extract preparation duration in minutes."),
            FieldSpec("precursor_of_np", "string", "Nanoparticle precursor."),
            FieldSpec("concentration_of_precursor_mM", "number", "Precursor concentration in mM."),
            FieldSpec("hydrodynamic_diameter_nm", "number", "Hydrodynamic diameter in nm."),
            FieldSpec("ph_during_synthesis", "number", "Synthesis pH."),
        ),
        numeric_fields=(
            "mdr",
            "mic_np_µg_ml",
            "concentration",
            "zoi_np_mm",
            "np_size_min_nm",
            "np_size_max_nm",
            "np_size_avg_nm",
            "time_set_hours",
            "zeta_potential_mV",
            "temperature_for_extract_C",
            "duration_preparing_extract_min",
            "concentration_of_precursor_mM",
            "hydrodynamic_diameter_nm",
            "ph_during_synthesis",
        ),
    ),
    "synergy": DomainSpec(
        key="synergy",
        title="Synergy",
        hf_dataset="ai-chem/Synergy",
        task=(
            "Extract nanoparticle-antimicrobial combination experiments, including "
            "nanoparticle properties, drug dose, organism, assay method, individual and combined "
            "activity, FIC/effect, exposure time, coatings, and viability."
        ),
        fields=(
            FieldSpec("NP", "string", "Nanoparticle name."),
            FieldSpec("bacteria", "string", "Bacterial strain tested."),
            FieldSpec("strain", "string", "Specific strain identifier."),
            FieldSpec("NP_synthesis", "string", "Nanoparticle synthesis method."),
            FieldSpec("drug", "string", "Antimicrobial drug used with the nanoparticle."),
            FieldSpec("drug_dose_µg_disk", "number", "Drug dose in micrograms per disk."),
            FieldSpec("NP_concentration_µg_ml", "number", "Nanoparticle concentration in micrograms per mL."),
            FieldSpec("NP_size_min_nm", "number", "Minimum nanoparticle size in nm."),
            FieldSpec("NP_size_max_nm", "number", "Maximum nanoparticle size in nm."),
            FieldSpec("NP_size_avg_nm", "number", "Average nanoparticle size in nm."),
            FieldSpec("shape", "string", "Nanoparticle shape."),
            FieldSpec("method", "string", "Assay method."),
            FieldSpec("ZOI_drug_mm_or_MIC _µg_ml", "number", "Drug-alone ZOI or MIC value."),
            FieldSpec("error_ZOI_drug_mm_or_MIC_µg_ml", "number", "Error for drug-alone activity."),
            FieldSpec("ZOI_NP_mm_or_MIC_np_µg_ml", "number", "Nanoparticle-alone ZOI or MIC value."),
            FieldSpec("error_ZOI_NP_mm_or_MIC_np_µg_ml", "number", "Error for nanoparticle-alone activity."),
            FieldSpec("ZOI_drug_NP_mm_or_MIC_drug_NP_µg_ml", "number", "Combination ZOI or MIC value."),
            FieldSpec("error_ZOI_drug_NP_mm_or_MIC_drug_NP_µg_ml", "number", "Error for combination activity."),
            FieldSpec("fold_increase_in_antibacterial_activity", "number", "Fold increase from combination."),
            FieldSpec("zeta_potential_mV", "number", "Zeta potential in mV."),
            FieldSpec("MDR", "string", "Multidrug resistance indicator."),
            FieldSpec("FIC", "number", "Fractional inhibitory concentration index."),
            FieldSpec("effect", "string", "Interaction effect, e.g. synergistic or additive."),
            FieldSpec("time_hr", "number", "Exposure time in hours."),
            FieldSpec("coating_with_antimicrobial_peptide_polymers", "string", "Peptide/polymer coating."),
            FieldSpec("combined_MIC", "number", "Combination MIC."),
            FieldSpec("peptide_MIC", "number", "Peptide MIC."),
            FieldSpec("viability_%", "number", "Viability percentage."),
            FieldSpec("viability_error", "number", "Viability error."),
        ),
        numeric_fields=(
            "drug_dose_µg_disk",
            "NP_concentration_µg_ml",
            "NP_size_min_nm",
            "NP_size_max_nm",
            "NP_size_avg_nm",
            "ZOI_drug_mm_or_MIC _µg_ml",
            "error_ZOI_drug_mm_or_MIC_µg_ml",
            "ZOI_NP_mm_or_MIC_np_µg_ml",
            "error_ZOI_NP_mm_or_MIC_np_µg_ml",
            "ZOI_drug_NP_mm_or_MIC_drug_NP_µg_ml",
            "error_ZOI_drug_NP_mm_or_MIC_drug_NP_µg_ml",
            "fold_increase_in_antibacterial_activity",
            "zeta_potential_mV",
            "FIC",
            "time_hr",
            "combined_MIC",
            "peptide_MIC",
            "viability_%",
            "viability_error",
        ),
    ),
}


ALIASES: dict[str, dict[str, str]] = {
    "synergy": {
        "Bacteria": "bacteria",
        "ZOI_drug_mm_or_MIC_µg_ml": "ZOI_drug_mm_or_MIC _µg_ml",
        "ZOI_drug_mm_or_MIC_µg_m": "ZOI_drug_mm_or_MIC _µg_ml",
    },
    "complexes": {
        "target_value": "target",
    },
    "eyedrops": {
        "SMILES": "smiles",
        "compound": "name",
        "compound_name": "name",
        "drug": "name",
        "permeability": "perm (cm/s)",
        "perm": "perm (cm/s)",
        "perm_cm_s": "perm (cm/s)",
        "corneal_permeability": "perm (cm/s)",
        "log_p": "logP",
        "logp": "logP",
    },
}


def get_domain(key: str) -> DomainSpec:
    try:
        return DOMAINS[key]
    except KeyError as exc:
        known = ", ".join(sorted(DOMAINS))
        raise ValueError(f"Unknown domain {key!r}. Known domains: {known}") from exc
