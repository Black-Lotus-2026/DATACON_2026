INSTRUCTIONS = "You specialize in nanozymes."

PROMPT = """
Your task is to extract **every** mention of experiments for **ALL** nanozymes from a scientific article and output a **JSON array** of objects **only** (no markdown, no commentary, no extra text).
Fields for each object:
- `formula` (string): the chemical formula of the nanozyme, e.g. ""Fe3O4"", ""CuO"", etc.
- `activity` (string): catalytic activity type, typically ""peroxidase"", ""oxidase"", ""catalase"", ""laccase"", or other.
- `syngony` (string): the crystal unit of the nanozyme, e.g. ""cubic"", ""hexagonal"", ""tetragonal"", ""monoclinic"", ""orthorhombic"", ""trigonal"", ""amorphous"", ""triclinic"".
- `length` (number): the length of the nanozyme particle in nanometers.
- `width` (number): the width of the nanozyme particle in nanometers.
- `depth` (number): the depth of the nanozyme particle in nanometers.
- `surface` (string): the molecule on the surface of the nanozyme, e.g., ""naked"", ""poly(ethylene oxide)"", ""poly(N-Vinylpyrrolidone)"", ""Tetrakis(4-carboxyphenyl)porphine"", or other.
- `km_value` (number): the Michaelis constant value for the nanozyme.
- `km_unit` (string): the unit for the Michaelis constant, e.g., ""mM"", etc.
- `vmax_value` (number): the molar maximum reaction rate value.
- `vmax_unit` (string): the unit for the maximum reaction rate, e.g., ""µmol/min"", ""mol/min"", etc.
- `reaction_type` (string): the reaction type involving the substrate and co-substrate, e.g., ""TMB + H2O2"", ""H2O2 + TMB"", ""TMB"", ""ABTS + H2O2"", ""H2O2"", ""OPD + H2O2"", ""H2O2 + GSH"", or other.
- `c_min` (number): the minimum substrate concentration in catalytic assays in mM.
- `c_max` (number): the maximum substrate concentration in catalytic assays in mM.
- `c_const` (number): the constant co-substrate concentration used during assays.
- `c_const_unit` (string): the unit of measurement for co-substrate concentration.
- `ccat_value` (number): the concentration of the catalyst used in assays.
- `ccat_unit` (string): the unit of measurement for catalyst concentration.
- `ph` (number): the pH level at which experiments were conducted.
- `temperature` (number): the temperature in Celsius during the study.
Extraction rules:
1. Extract **each** nanozyme mention as a separate object. 
2. Do **not** filter, group, summarize, or deduplicate. Include repeated mentions and duplicates if they occur in different contexts. 
3. If you cannot find a required field for an object, re-check the context; if it’s still absent, set that field’s value to `""NOT_DETECTED""`.
4. The example of JSON below shows only two extracted samples, however your output should contain **all** nanozymes present in the article.
Output **must** be a single JSON array, like:
[
  {
    ""formula"": ""Fe3O4"",
    ""activity"": ""peroxidase"",
    ""syngony"": ""cubic"",
    ""length"": 10,
    ""width"": 10,
    ""depth"": 2.5,
    ""surface"": ""naked"",
    ""km_value"": 0.2,
    ""km_unit"": ""mM"",
    ""vmax_value"": 2.5,
    ""vmax_unit"": ""µmol/min"",
    ""reaction_type"": ""TMB + H2O2"",
    ""c_min"": 0.01,
    ""c_max"": 1.0,
    ""c_const"": 1.0,
    ""c_const_unit"": ""mM"",
    ""ccat_value"": 0.05,
    ""ccat_unit"": ""mg/mL"",
    ""ph"": 4.0,
    ""temperature"": 25
  },
  {
    ""formula"": ""CeO2"",
    ""activity"": ""oxidase"",
    ""syngony"": ""cubic"",
    ""length"": 5,
    ""width"": 5,
    ""depth"": 200,
    ""surface"": ""poly(ethylene oxide)"",
    ""km_value"": 54.05,
    ""km_unit"": ""mM"",
    ""vmax_value"": 7.88,
    ""vmax_unit"": ""10-8 M s-1"",
    ""reaction_type"": ""TMB"",
    ""c_min"": 0.02,
    ""c_max"": 0.8,
    ""c_const"": 800,
    ""c_const_unit"": ""μM"",
    ""ccat_value"": 0.02,
    ""ccat_unit"": ""mg/mL"",
    ""ph"": 5.5,
    ""temperature"": 37
  }
]
"""