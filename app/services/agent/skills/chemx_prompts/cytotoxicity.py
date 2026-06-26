INSTRUCTIONS = "You specialize in cytotoxic nanoparticles."

PROMPT = """
Your task is to extract information for **ALL** cytotoxic nanoparticles from a scientific article and output a **JSON array** of objects **only** (no markdown, no commentary, no extra text).
Fields for each object:
- `material` (string): Composition of the nanoparticle/material tested (e.g., ""SiO2"", ""Ag"").
- `shape` (string): Physical shape of the particle (e.g., ""Sphere"", ""Rod"").
- `coat_functional_group` (string): Surface coating or functionalization (e.g., ""CTAB"", ""PEG"").
- `synthesis_method` (string): Synthesis method (e.g., ""Precipitation"", ""Commercial"").
- `surface_charge` (string): one of `""Negative""`, `""Neutral""`, or `""Positive""`. Reported surface charge.
- `core_nm` (number): Primary particle size in nm.
- `size_in_medium_nm` (number): Hydrodynamic size in biological medium in nm.
- `hydrodynamic_nm` (number): Size in solution including coatings in nm.
- `potential_mv` (number): Surface charge in solution in mV.
- `zeta_in_medium_mv` (number): Zeta potential in medium in mV.
- `no_of_cells_cells_well` (number): Cell density per well in the assay.
- `human_animal` (string):  one of ""A"" for Animal or ""H"" for Human. Origin of cells.
- `cell_source` (string): Species/organism (e.g., ""Rat"", ""Human"").
- `cell_tissue` (string): Tissue origin of the cell line (e.g., ""Adrenal Gland"", ""Lung"").
- `cell_morphology` (string): Cell shape (e.g., ""Irregular"", ""Epithelial"").
- `cell_age` (string): Developmental stage of cells (e.g., ""Adult"", ""Embryonic"").
- `time_hr` (number): Exposure duration in hours.
- `concentration` (number): Tested concentration of the material (unit-specific, e.g., μg/mL).
- `test` (string): Cytotoxicity assay type (e.g., ""MTT"", ""LDH"").
- `test_indicator` (string): Reagent measured (e.g., ""TetrazoliumSalt"" for MTT).
- `viability_%` (number): Cell viability percentage relative to control.
Extraction rules:
1. If multiple values are reported (e.g., sizes), prioritize TEM-measured sizes for core_nm. For concentration, note unit context from article if ambiguous.
2. Error Handling: Prioritize table data over text; note assumptions for ambiguous data.
3. Viability Notes: For viability_percent, values >100% may indicate proliferation stimulation; extract as reported.
4. Extract **each** nanoparticle mention as a separate object. 
5. Do **not** filter, group, summarize, or deduplicate. Include repeated mentions and duplicates if they occur in different contexts. 
6. If you cannot find a required field for an object, re-check the context; if it’s still absent, set that field’s value to `""NOT_DETECTED""`.
7. The example of JSON below shows only two extracted samples, however your output should contain **all** nanoparticles present in the article.
Output **must** be a single JSON array, like:
[
  {
    ""material"": ""SiO2"",
    ""shape"": ""Rod"",
    ""coat_functional_group"": ""PEG"",
    ""synthesis_method"": ""Precipitation"",
    ""surface_charge"": ""Negative"",
    ""core_nm"": 20.0,
    ""size_in_medium_nm"": 25.0,
    ""hydrodynamic_nm"": 30.0,
    ""potential_mv"": -15.0,
    ""zeta_in_medium_mv"": -10.0,
    ""no_of_cells_cells_well"": 5000.0,
    ""human_animal"": ""H"",
    ""cell_source"": ""Human"",
    ""cell_tissue"": ""Lung"",
    ""cell_morphology"": ""Epithelial"",
    ""cell_age"": ""Adult"",
    ""time_hr"": 24.0,
    ""concentration"": 100.0,
    ""test"": ""MTT"",
    ""test_indicator"": ""TetrazoliumSalt"",
    ""viability_%"": 85.0
  },
  {
    ""material"": ""Fe3O4"",
    ""shape"": ""Sphere"",
    ""coat_functional_group"": ""Dextran"",
    ""synthesis_method"": ""Thermal Decomposition"",
    ""surface_charge"": ""Positive"",
    ""core_nm"": 10.0,
    ""size_in_medium_nm"": 15.0,
    ""hydrodynamic_nm"": 18.0,
    ""potential_mv"": -30.0,
    ""zeta_in_medium_mv"": -15.0,
    ""no_of_cells_cells_well"": 10000.0,
    ""human_animal"": ""A"",
    ""cell_source"": ""Dog"",
    ""cell_tissue"": ""Kidney"",
    ""cell_morphology"": ""Epithelial"",
    ""cell_age"": ""Adult"",
    ""time_hr"": 24.0,
    ""concentration"": 300.0,
    ""test"": ""MTT"",
    ""test_indicator"": ""TetrazoliumSalt"",
    ""viability_%"": 115.09
  }
]
"""