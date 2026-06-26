INSTRUCTIONS = "You specialize in antimicrobial nanoparticles."

PROMPT = """
Your task is to extract information for **ALL** antimicrobial nanoparticles from a scientific article and output a **JSON array** of objects **only** (no markdown, no commentary, no extra text).
Fields for each object:
- `np` (string): Nanoparticle name (e.g., ""Ag"", ""Au"", ""ZnO"").
- `coating` (string): Surface coating/modification (""1"" for coating, ""0"" for none).
- `bacteria` (string): Bacterial strain tested (e.g., ""Escherichia coli"", ""Staphylococcus aureus"").
- `mdr` (number): Multidrug-resistant strain indicator, one of 1 or 0 (1 for multidrug-resistant, 0 for not multidrug-resistant).
- `strain` (string): Specific strain identifier (e.g., ""ATCC 25922"").
- `np_synthesis` (string): Synthesis method (e.g., ""green_synthesis"", ""chemical_synthesis"", or specific details like ""Green synthesis using Pimpinella anisum"").
- `method` (string): Assay type (e.g., ""MIC"", ""ZOI"", ""MBC"", ""MBEC"").
- `mic_np_µg_ml` (number): Minimum Inhibitory Concentration (MIC) in μg/mL.
- `concentration` (number): Concentration for Zone of Inhibition (ZOI) in μg/mL.
- `zoi_np_mm` (number): Zone of Inhibition in mm.
- `np_size_min_nm` (number): Minimum nanoparticle size in nm.
- `np_size_max_nm` (number): Maximum nanoparticle size in nm.
- `np_size_avg_nm` (number): Average nanoparticle size in nm.
- `shape` (string): Morphology (e.g., ""spherical"", ""triangular"").
- `time_set_hours` (number): Experiment duration in hours.
- `zeta_potential_mV` (number): Surface charge in mV.
- `solvent_for_extract` (string): Solvent used in green synthesis (e.g., ""water"", ""ethanol"").
- `temperature_for_extract_C` (number): Temperature during extract preparation in °C.
- `duration_preparing_extract_min` (number): Time to prepare extract in minutes.
- `precursor_of_np` (string): Chemical precursor (e.g., ""AgNO3"").
- `concentration_of_precursor_mM` (number): Precursor concentration in mM.
- `hydrodynamic_diameter_nm` (number): Hydrodynamic size in nm.
- `ph_during_synthesis` (number): pH of synthesis solution.
Extraction rules:
1. Extract solvents and precursors as strings without parsing into molecular components.
2. Extract **each** nanoparticle mention as a separate object. 
3. Do **not** filter, group, summarize, or deduplicate. Include repeated mentions and duplicates if they occur in different contexts. 
4. If you cannot find a required field for an object, re-check the context; if it’s still absent, set that field’s value to `""NOT_DETECTED""`.
5. The example of JSON below shows only two extracted samples, however your output should contain **all** nanoparticles present in the article.
Output **must** be a single JSON array, like:
[
  {
    ""np"": ""Ag"",
    ""coating"": ""0"",
    ""bacteria"": ""Enterococcus faecalis"",
    ""mdr"": 0,
    ""strain"": ""ATCC 29212"",
    ""np_synthesis"": ""Green synthesis using Ixora brachypoda"",
    ""method"": ""MIC"",
    ""mic_np_µg_ml"": 32.0,
    ""concentration"": 10,
    ""zoi_np_mm"": 15,
    ""np_size_min_nm"": 10.0,
    ""np_size_max_nm"": 40.0,
    ""np_size_avg_nm"": 20.0,
    ""shape"": ""spherical"",
    ""time_set_hours"": 24,
    ""zeta_potential_mV"": -27.9,
    ""solvent_for_extract"": ""water"",
    ""temperature_for_extract_C"": 21.0,
    ""duration_preparing_extract_min"": 1440,
    ""precursor_of_np"": ""AgNO3"",
    ""concentration_of_precursor_mM"": 1.0,
    ""hydrodynamic_diameter_nm"": 55,
    ""ph_during_synthesis"": 8.5
  },
  {
    ""np"": ""ZnO"",
    ""coating"": ""0"",
    ""bacteria"": ""Klebsiella pneumoniae"",
    ""mdr"": 1,
    ""strain"": ""K-36"",
    ""np_synthesis"": ""Green synthesis using Phyllanthus emblica"",
    ""method"": ""MIC"",
    ""mic_np_µg_ml"": 6.25,
    ""concentration"": 64,
    ""zoi_np_mm"": 12,
    ""np_size_min_nm"": 20.0,
    ""np_size_max_nm"": 20.0,
    ""np_size_avg_nm"": 20.0,
    ""shape"": ""spherical"",
    ""time_set_hours"": 24.0,
    ""zeta_potential_mV"": -32,
    ""solvent_for_extract"": ""methanol"",
    ""temperature_for_extract_C"": 60,
    ""duration_preparing_extract_min"": 60,
    ""precursor_of_np"": ""Zn(NO3).6.H2O"",
    ""concentration_of_precursor_mM"": 10,
    ""hydrodynamic_diameter_nm"": 30,
    ""ph_during_synthesis"": 7.0
  }
]
"""