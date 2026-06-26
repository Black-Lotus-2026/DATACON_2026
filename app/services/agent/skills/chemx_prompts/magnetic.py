INSTRUCTIONS = "You specialize in nanomaterials characterization, specifically in magnetic nanoparticles and their physical properties."

PROMPT = """
Your task is to extract **every** mention of magnetic properties for **ALL** nanoparticles from a scientific article and output a **JSON array** of objects **only** (no markdown, no commentary, no extra text).
Fields for each object:
- `name` (string): material name (e.g., BFO, cobalt irin oxide and bismuth ferrite etc.).
- `np_core` (string): composition of material core (e.g., Gd2O3, Fe1Fe2O4 etc.).
- `np_shell` (string): composition of material shell (e.g., chitosan, Au1 etc.).  
- `core_shell_formula` (string): sometimes nanoparticle composition is represented as one formula containing both core and shell parts; core and shell materials are typically separated by a delimiter such as -, /, @, or |, e.g. Cr2O3-Co.  
- `np_shell_2` (string): first additional shell layer if present (e.g., PEG-5000, Curcumin etc.). 
- `np_hydro_size` (number): size of nanoparticles in solution obtained by dynamic light scattering (DLS) or similar, in nanometers (nm).
- `xrd_scherrer_size` (number): crystal size calculated from x-ray diffraction, usually represented in figures, in nanometers (nm).
- `emic_size` (number): size measured by electron microscopy, usually represented in figures, in nanometers (nm).
- `space_group_core` (string): space groups of core material (e.g., fd-3m, p4/mmm, etc.).
- `space_group_shell` (string): space groups of shell material (e.g., fd-3m, p4/mmm, etc.).
- `squid_sat_mag` (number): saturation magnetization (Ms, Bs) in emu/g.
- `squid_rem_mag` (number): remanent (remanence) magnetization (Mr, Br) in emu/g.
- `exchange_bias_shift_Oe` (number): exchange bias (Heb, exchange bias effect) in Oersted (Oe).
- `vertical_loop_shift_M_vsl_emu_g` (number): vertical loop shift (vertical bias) in emu/g.
- `hc_kOe` (number): coercivity (Hc, coercive force) in Oersted (Oe).
- `squid_h_max` (number): maximum magnetic field in kOe.
- `zfc_h_meas` (number): measurement field for ZFC in kOe.
- `instrument` (string): experimental instrument (e.g., Quantum Design 7 T SQUID magnetometer, Seifert XRD 3000P, etc.).
- `fc_field_T` (number): FC field in Tesla (T).
- `squid_temperature` (number): squid temperature in Kelvin.
- `coercivity` (number): coercivity (Hc) in kOe.
- `htherm_sar` (number): specific absorption rate (SAR) in W/g.
- `mri_r1` (number): MRI relaxation rate r1 in mM-1·s-1.
- `mri_r2` (number): MRI relaxation rates r2 in mM-1·s-1.
Extraction rules:
1. Extract **each** nanoparticle mention as a separate object. 
2. Do **not** filter, group, summarize, or deduplicate. Include repeated mentions and duplicates if they occur in different contexts. 
3. If you cannot find a required field for an object, re-check the context; if it’s still absent, set that field’s value to `""NOT_DETECTED""`.
4. If the original unit of coercivity or exchange bias is different, it must be converted into Oe: 1T = 1000 Oe, 1 mT = 10000 Oe, 1kOe = 1000 Oe.
5. If the original unit of remanent magnetization or saturation magnetization or vertical loop shift is different, it must be converted in emu/g: 1 A·m2/kg = 1 emu/g, 1 μ0M(T) = 0.01257 emu/g. 
6. Do not remove or alter the negative (-) or positive (+) signs for exchange bias and vertical loop shift. If the article does not explicitly state the sign, assume it is (+) by default.
7. The example of JSON below shows only one extracted sample, however your output should contain entries for **all** magnetic nanoparticles present in the article.
Output **must** be a single JSON array, like:
[
  {
  ""name"": ""Bismuth Ferrite"",
  ""np_core"": ""BiFeO3"",
  ""np_shell"": ""chitosan"",
  ""core_shell_formula"": ""BiFeO3-chitosan"",
  ""np_shell_2"": ""PEG-5000"",
  ""np_hydro_size"": 120,
  ""xrd_scherrer_size"": 45,
  ""emic_size"": 50,
  ""space_group_core"": ""R3c"",
  ""space_group_shell"": ""P2_1"",
  ""squid_sat_mag"": 40.5,
  ""squid_rem_mag"": 22.1,
  ""exchange_bias_shift_Oe"": 180,
  ""vertical_loop_shift_M_vsl_emu_g"": 5.6,
  ""hc_kOe"": 3.2,
  ""squid_h_max"": 5.0,
  ""zfc_h_meas"": 1.5,
  ""instrument"": ""Quantum Design 7 T SQUID magnetometer"",
  ""fc_field_T"": 0.1,
  ""squid_temperature"": 300,
  ""coercivity"": 3.5,
  ""htherm_sar"": 1.2,
  ""mri_r1"": 4.5,
  ""mri_r2"": 5.3
}
]
"""