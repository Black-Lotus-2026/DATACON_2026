INSTRUCTIONS = "You specialize in chemistry of small molecules. In particular, your area is antibiotics and their properties."

PROMPT = """
Your task is to extract **every** mention of MIC or pMIC values for oxazolidinone antibiotics from a scientific article and output a **JSON array** of objects **only** (no markdown, no commentary, no extra text).
Fields for each object:
- `compound_id` (string):  ID of a molecule within the article, as cited in the text, e.g. `""5a""`, `""Compound 3""`.  
- `smiles` (string): full SMILES representation of an oxazolidinone antibiotic.  
- `target_type` (string): type of measurement, either `""MIC""` or `""pMIC""`, exactly as stated.  
- `target_relation` (string): one of `""=""`, `""<""`, or `"">""`. If no relation symbol is shown, use `""=""`.  
- `target_value` (number): the numeric value of MIC/pMIC (without quotes).  
- `target_units` (string): e.g. `""μg/mL""`, `""mg/L""`, etc.  
- `bacteria` (string): the organism against which MIC/pMIC was measured, named exactly as in the text. Record full names, abbreviations, or any related taxonomic identifiers of bacteria.
Extraction rules:
1. Extract **each** MIC or pMIC mention as a separate object.  
2. Do **not** filter, group, summarize, or deduplicate. Include repeated mentions and duplicates if they occur in different contexts.  
3. If a range is given (e.g., “2–8 μg/mL”), leave it as a range. 
4. If a molecule is fully depicted in a figure, write it as a SMILES string. If a molecule is depicted as a scaffold and residues separately in different places of an article, connect them by compound ID into one molecule and write it as a single SMILES string.
5. If multiple measurement types appear for the same compound and bacterium (e.g., MIC₅₀, MIC₉₀), extract each separately.  
6. If you cannot find a required field for an object, re-check the context; if it’s still absent, set that field’s value to `""NOT_DETECTED""`. 
7. The example of JSON below shows only two extracted samples, however your output should contain **all** MIC or pMIC measurements of oxazolidinone antibiotics present in the article.
Output **must** be a single JSON array, like:
[
  {
    ""compound_id"": ""12b"",
    ""smiles"": ""CC1=CC=C(C=C1)C(=O)Nc2ccc(cc2)C(=O)N3CCCCC3=O"",
    ""target_type"": ""MIC"",
    ""target_relation"": ""<"",
    ""target_value"": 1,
    ""target_units"": ""mmol/l"",
    ""bacteria"": ""methicillin-susceptible S. aureus""
  },
  {
    ""compound_id"": ""5a"",
    ""smiles"": ""CC1=CC=CC=C1N2C=NC3=CC=CC=C23"",
    ""target_type"": ""MIC"",
    ""target_relation"": ""="",
    ""target_value"": 2,
    ""target_units"": ""μg/mL"",
    ""bacteria"": ""Escherichia coli""
  }
]
"""