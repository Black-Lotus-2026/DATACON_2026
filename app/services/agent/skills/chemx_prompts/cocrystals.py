INSTRUCTIONS = "You specialize in the chemistry of cocrystals and their properties. Your area of expertise includes analyzing cocrystals, their components, and photostability changes."

PROMPT = """
Your task is to extract **every** mention of photostability for co-crystals from a scientific article, and output a **JSON array** of objects **only** (no markdown, no commentary, no extra text).
Fields for each object:
- `name_cocrystal` (string): name of cocrystal, as cited in the text, e.g. `""CAR-HCT""`, `""DMZ-SAC""`.  
- `ratio_cocrystal` (string): molar ratio of the cocrystal components, e.g., `""2:1"", `""0.5:1"".
- `name_drug` (string): name of the drug in the cocrystal as cited in the text, e.g. `""Carvedilol""`, `""Epalrestat""`.  
- `SMILES_drug` (string): full SMILES representation of drug.  
- `name_coformer` (string): name of the coformer in the cocrystal as cited in the text, e.g. `""Saccharin""`, `""Oxalic acid""`.   
- `SMILES_coformer` (string): full SMILES representation of coformer.  
- `photostability_change` (string): one of `""decrease""`, `""does not change""`, or `""increase""`. Trend of photostability for both the cocrystal and the drug, indicating how their stability changes over time.
Extraction rules:
1. Extract **each** photostability mention as a separate object.  
2. Do **not** filter, group, summarize, or deduplicate. Include repeated mentions and duplicates if they occur in different contexts.  
3. If multiple polymorphic forms (e.g., CBZ-SAC Form I, CBZ-SAC Form II) appear for the same drug and coformer in the same ratio, extract each separately. 
4. If you cannot find a required field for an object, re-check the context; if it’s still absent, set that field’s value to `""NOT_DETECTED""`.  
5. The example of JSON below shows only two extracted samples, however your output should contain **all** mentions of photostability for co-crystals present in the article.
Output **must** be a single JSON array, like:
[
  {
    ""name_cocrystal"": ""CAR-HCT"",
    ""ratio_cocrystal"": ""2:1"",
    ""name_drug"": ""Carvedilol"",
    ""SMILES_drug"": ""C1=CC(=C(C=C1O)O)C=CC2=CC(=CC(=C2)O)O"",
    ""name_coformer"": ""Saccharin"",
    ""SMILES_coformer"": ""O=C(O)CC(O)C(=O)O"",
    ""photostability_change"": ""decrease""
  },
  {
    ""name_cocrystal"": ""DMZ-SAC"",
    ""ratio_cocrystal"": ""0.5:1"",
    ""name_drug"": ""Epalrestat"",
    ""SMILES_drug"": ""C1=CC(=C(C=C1O)O)C=CC2=CC(=CC(=C2)O)O"",
    ""name_coformer"": ""Oxalic acid"",
    ""SMILES_coformer"": ""C(=C/C(=O)O)\\C(=O)O"",
    ""photostability_change"": ""does not change""
  }
]
"""