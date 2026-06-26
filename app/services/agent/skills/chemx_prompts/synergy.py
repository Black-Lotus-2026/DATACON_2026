INSTRUCTIONS = "You specialize in antimicrobial drug nanoparticle synergy."

PROMPT = """
Your task is to extract **every** mention of nanoparticle properties, drug details, and their synergistic antibacterial effects from a scientific article, and output a **JSON array** of objects **only** (no markdown, no commentary, no extra text).
Fields for each object:
- `NP` (string): nanoparticle name as cited in the text, e.g. , ""Ag"", ""Au"".
- `bacteria` (string): bacterial strain tested, e.g., ""Escherichia coli"".
- `strain` (string): specific strain identifier for the bacteria tested as cited in the text, e.g., ""ATCC 25922"", ""MTCC 443"".
- `NP_synthesis` (string): method by which the nanoparticles were synthesized, e.g., ""chemical synthesis"", ""hydrothermal synthesis"".
- `drug` (string): name of the conventional antibiotic or other antimicrobial drug used in combination with the nanoparticles, e.g., ""Ampicillin"", ""Ciprofloxacin"".
- `drug_dose_µg_disk` (number): specific dosage or concentration of the drug applied, primarily used for methods like disc diffusion assays, typically measured in micrograms per disk.
- `NP_concentration_µg_ml` (number): concentration of the nanoparticle used in the antibacterial assay, e.g., for MIC, ZOI, or viability studies, typically measured in micrograms per milliliter. 
- `NP_size_min_nm` (number): the smallest recorded size of the nanoparticle particles as determined by characterization techniques, measured in nanometers.
- `NP_size_max_nm` (number): the largest recorded size of the nanoparticle particles as determined by characterization techniques, measured in nanometers.
- `NP_size_avg_nm` (number): the average size of the nanoparticle particles, typically based on measurements from techniques like TEM or DLS, measured in nanometers.
- `shape` (string): observed morphology or physical shape of the nanoparticle particles, e.g., ""spherical"", ""rod-shaped"", ""cubic"", ""irregular"", ""nanosheets"".
- `method` (string): specific experimental technique employed to assess the antibacterial efficacy or interaction, e.g., ""MIC"", ""disc_diffusion"", ""well_diffusion"", ""broth microdilution"", ""time-kill assay"".
- `ZOI_drug_mm_or_MIC _µg_m` (number): quantitative measure of antibacterial activity for the drug alone. This will be the diameter of the ZOI in millimeters for disc diffusion assays, or the MIC value in micrograms per milliliter for methods like broth microdilution.
- `error_ZOI_drug_mm_or_MIC_µg_ml` (number): uncertainty or variability associated with the antibacterial activity measurement for the drug alone, often represented as the standard deviation.
- `ZOI_NP_mm_or_MIC_np_µg_ml` (number): The quantitative measure of antibacterial activity for the nanoparticle alone. This will be the ZOI diameter in millimeters or the MIC value in micrograms per milliliter.
- `error_ZOI_NP_mm_or_MIC_np_µg_ml` (number): uncertainty or variability associated with the antibacterial activity measurement for the nanoparticle alone.
- `ZOI_drug_NP_mm_or_MIC_drug_NP_µg_ml` (number): quantitative measure of antibacterial activity for the combination of the drug and the nanoparticle. This will be the ZOI diameter in millimeters or the MIC value in micrograms per milliliter.
- `error_ZOI_drug_NP_mm_or_MIC_drug_NP_µg_ml` (number): uncertainty or variability associated with the antibacterial activity measurement for the drug + nanoparticle combination.
- `fold_increase_in_antibacterial_activity` (number): numerical value indicating how much more effective the combination of the drug and nanoparticle is compared to the most effective component used individually.
- `zeta_potential_mV` (number): electrokinetic potential of the nanoparticle surface, measured in millivolts. It is an indicator of the surface charge and stability of the nanoparticles in suspension.
- `MDR` (string): indicator of whether the bacterial strain tested exhibits multidrug resistance, e.g., ""Yes"", ""No"", ""Resistant"", ""Susceptible"".
- `FIC` (number): Fractional Inhibitory Concentration index value, calculated to assess the interaction between the drug and nanoparticle. Values help determine if the interaction is synergistic (<0.5), additive (0.5-1.0), indifferent (1.0-4.0), or antagonistic (>4.0).
- `effect` (string): qualitative description of the interaction between the drug and nanoparticle based on the FIC index, e.g., ""synergistic"", ""additive"", ""antagonistic"", ""indifferent"".
- `time_hr` (number): duration of exposure of the bacterial cells to the antibacterial agents during the experiment, specified in hours.
- `coating_with_antimicrobial_peptide_polymers` (string): indicates whether the nanoparticles were modified with a coating of antimicrobial peptides or polymers to enhance their activity or targeting, e.g., ""yes"", ""no"", specifies the coating material.
- `combined_MIC` (number):  Minimum Inhibitory Concentration observed for the combination of an antimicrobial peptide / polymer coating and the nanoparticle, in micrograms per milliliter if applicable.
- `peptide_MIC` (number): Minimum Inhibitory Concentration of the antimicrobial peptide Used in isolation, in micrograms per milliliter if applicable.
- `viability_%` (number): percentage of bacterial cells that survive or remain viable after being exposed to the nanoparticle, drug, or combination for a specific time period.
- `viability_error` (number): associated error or standard deviation for the bacterial viability percentage measurement.
Extraction rules:
1. Extract **each** nanoparticles mention as a separate object.  
2. Do **not** filter, group, summarize, or deduplicate. Include repeated mentions and duplicates if they occur in different contexts.  
3. If you cannot find a required field for an object, re-check the context; if it’s still absent, set that field’s value to `""NOT_DETECTED""`.
4. The example of JSON below shows only two extracted samples, however your output should contain **all** nanoparticles present in the article.
Output **must** be a single JSON array, like:
[
  {
    ""NP"": ""Ag"",
    ""bacteria"": ""Pseudomonas aeruginosa"",
    ""strain"": ""ATCC 27853"",
    ""NP_synthesis"": ""Green synthesis using Gloeophyllum striatum"",
    ""drug"": ""Ampicillin"",
    ""drug_dose_µg_disk"": 16.0,
    ""NP_concentration_µg_ml"": 32.0,
    ""NP_size_min_nm"": 10.0,
    ""NP_size_max_nm"": 40.0,
    ""NP_size_avg_nm"": 20.0,
    ""shape"": ""spherical"",
    ""method"": ""MIC"",
    ""ZOI_drug_mm_or_MIC _µg_ml"": 16.0,
    ""error_ZOI_drug_mm_or_MIC_µg_ml"": 1.40,
    ""ZOI_NP_mm_or_MIC_np_µg_ml"": 32.0,
    ""error_ZOI_NP_mm_or_MIC_np_µg_ml"": 2.43,
    ""ZOI_drug_NP_mm_or_MIC_drug_NP_µg_ml"": 8.0,
    ""error_ZOI_drug_NP_mm_or_MIC_drug_NP_µg_ml"": 1.50,
    ""fold_increase_in_antibacterial_activity"": 2.0,
    ""zeta_potential_mV"": -34.0,
    ""MDR"": ""R"",
    ""FIC"": 0.5,
    ""effect"": ""synergistic"",
    ""time_hr"": 24.0,
    ""coating_with_antimicrobial_peptide_polymers"": ""AP Lysozyme hen egg-white"",
    ""combined_MIC"": 12,
    ""peptide_MIC"": 400,
    ""viability_%"": 87.0,
    ""viability_error"": 2.40
  },
  {
    ""NP"": ""Au"",
    ""bacteria"": ""Escherichia coli"",
    ""strain"": ""BJ915"",
    ""NP_synthesis"": ""purchased from Jinke Chemical Co"",
    ""drug"": ""Colistin"",
    ""drug_dose_µg_disk"": 10.0,
    ""NP_concentration_µg_ml"": 25.0,
    ""NP_size_min_nm"": 2.1,
    ""NP_size_max_nm"": 2.9,
    ""NP_size_avg_nm"": 2.5,
    ""shape"": ""cubic"",
    ""method"": ""MBC"",
    ""ZOI_drug_mm_or_MIC _µg_ml"": 4.0,
    ""error_ZOI_drug_mm_or_MIC_µg_ml"": 0.30,
    ""ZOI_NP_mm_or_MIC_np_µg_ml"": 12.50,
    ""error_ZOI_NP_mm_or_MIC_np_µg_ml"": 0.87,
    ""ZOI_drug_NP_mm_or_MIC_drug_NP_µg_ml"": 6.25,
    ""error_ZOI_drug_NP_mm_or_MIC_drug_NP_µg_ml"": 0.27,
    ""fold_increase_in_antibacterial_activity"": 1.16,
    ""zeta_potential_mV"": 14.0,
    ""MDR"": ""R"",
    ""FIC"": 0.75,
    ""effect"": ""P"",
    ""time_hr"": 24.0,
    ""coating_with_antimicrobial_peptide_polymers"": ""4,6-diamino-2-pyrimidinethiol + 1,1-dimethylbiguanide"",
    ""combined_MIC"": 4.0,
    ""peptide_MIC"": 13.20,
    ""viability_%"": 23.0,
    ""viability_error"": 2.25
  }
]
"""