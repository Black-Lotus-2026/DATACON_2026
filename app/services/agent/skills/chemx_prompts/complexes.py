INSTRUCTIONS = "You specialize in the chemistry of organometallic complexes and their properties."

GA_PROMPT = """
Your task is to extract **every** mention of organometallic complexes and chelate ligands from scientific article, and output a **JSON array** of objects **only** (no markdown, no commentary, no extra text).
Fields for each object:
- `compound_id` (string): ID of a complex within the article, as cited in the text, e.g. `""L3""`, `""A31""`.  
- `compound_name` (string): abbreviated or full name of the complex or ligand as cited in the text, e.g. `""DOTA""`, `""tebroxime""`. 
- `SMILES` (string): full SMILES representation of ligand environment or single ligand.  If a complete organometallic complex is shown, extract all ligand structures without mentioning the metal (e.g., ""COc1cc(C=CC([O-])CC([O-])CC([O-])C=Cc2ccc(O)c(OC)c2)ccc1O. [C-]#[O+].[C-]#[O+].[C-]#[O+].[OH-]""). For a chelate ligand without a complete organometallic complex, extract only that ligand's structure (e.g., 'O=C(O)CN(CCN(CC(CC(=O)O)CC(=O)O)CCN(CC(=O)O)CC(=O)O').
- `SMILES_type` (string): one of `""ligand""` or `""environment""`. ""environment"" refers to the entire organometallic complex, including one or more ligands and a metal atom. ""ligand"" signifies a single chelate ligand, which is an organic molecule.
- `target_value` (number): the numeric value of logarithms of thermodynamic stability constants lgK or logK (without quotes). 
Extraction rules:
1. Extract **each** mention of `target_value` (lgK or logK) as a separate object.  
2. Do **not** filter, group, summarize, or deduplicate. Include repeated mentions and duplicates if they occur in different contexts.  
3. If a molecule is fully depicted in a figure, write it as a SMILES string. If a molecule is depicted as a scaffold and residues separately in different places of an article, connect them by compound ID or name into one molecule and write it a single SMILES string.
4. If multiple thermodynamic stability constants appear for the same complex or ligand extract each separately. 
5. Extract only structures that comply with these rules:
5.1. The complexes must contain **{Ga}** as the metal or the ligands must belong to complexes of that metal.
5.2. The complete molecular structure shall be given without errors in it or identifiers.
5.3. Compounds must contain more than one carbon (exclude CO, Me).
5.4. Compounds must not contain polymeric structures, attached biomolecules or carboranes, undefined radicals, undeciphered designations (e.g., amino acids) beyond the simplest abbreviations (i.e., Me, Et, Pr, Bu, Ph, Ac), names of radicals instead of their structure, or incomplete indication of the ligand structure (e.g., L = P, N).
5.5. Compounds must not be reaction intermediate or precursor.
6. If you cannot find a required field for an object, re-check the context; if it’s still absent, set that field’s value to `""NOT_DETECTED""`.  
7. The example of JSON below shows only two extracted samples, however your output should contain **all** mentions of organometallic complexes and / or chelate ligands present in the article.
Output **must** be a single JSON array, like:
[
    {
        ""compound_id"": ""L3"",
        ""compound_name"": ""DOTA"",
        ""SMILES"": ""O=C(O)CN(CCN(CC(=O)O)CC(=O)O)CC(=O)O"",
        ""SMILES_type"": ""ligand"",
        ""target"": 21.3
    },
    {
        ""compound_id"": ""A31"",
        ""compound_name"": ""tebroxime"",
        ""SMILES"": ""[C-]#[N+]CC(C)(C)OC.[C-]#[N+]CC(C)(C)OC.[C-]#[N+]CC(C)(C)OC.[C-]#[N+]CC(C)(C)OC.[C-]#[N+]CC(C)(C)OC.[C-]#[N+]CC(C)(C)OC"",
        ""SMILES_type"": ""environment"",
        ""target"": 17.9
    }
]
"""

GD_PROMPT = """
Your task is to extract **every** mention of organometallic complexes and chelate ligands from scientific article, and output a **JSON array** of objects **only** (no markdown, no commentary, no extra text).
Fields for each object:
- `compound_id` (string): ID of a complex within the article, as cited in the text, e.g. `""L3""`, `""A31""`.  
- `compound_name` (string): abbreviated or full name of the complex or ligand as cited in the text, e.g. `""DOTA""`, `""tebroxime""`. 
- `SMILES` (string): full SMILES representation of ligand environment or single ligand.  If a complete organometallic complex is shown, extract all ligand structures without mentioning the metal (e.g., ""COc1cc(C=CC([O-])CC([O-])CC([O-])C=Cc2ccc(O)c(OC)c2)ccc1O. [C-]#[O+].[C-]#[O+].[C-]#[O+].[OH-]""). For a chelate ligand without a complete organometallic complex, extract only that ligand's structure (e.g., 'O=C(O)CN(CCN(CC(CC(=O)O)CC(=O)O)CCN(CC(=O)O)CC(=O)O').
- `SMILES_type` (string): one of `""ligand""` or `""environment""`. ""environment"" refers to the entire organometallic complex, including one or more ligands and a metal atom. ""ligand"" signifies a single chelate ligand, which is an organic molecule.
- `target_value` (number): the numeric value of logarithms of thermodynamic stability constants lgK or logK (without quotes). 
Extraction rules:
1. Extract **each** mention of `target_value` (lgK or logK) as a separate object.  
2. Do **not** filter, group, summarize, or deduplicate. Include repeated mentions and duplicates if they occur in different contexts.  
3. If a molecule is fully depicted in a figure, write it as a SMILES string. If a molecule is depicted as a scaffold and residues separately in different places of an article, connect them by compound ID or name into one molecule and write it a single SMILES string.
4. If multiple thermodynamic stability constants appear for the same complex or ligand extract each separately. 
5. Extract only structures that comply with these rules:
5.1. The complexes must contain **Gd** as the metal or the ligands must belong to complexes of that metal.
5.2. The complete molecular structure shall be given without errors in it or identifiers.
5.3. Compounds must contain more than one carbon (exclude CO, Me).
5.4. Compounds must not contain polymeric structures, attached biomolecules or carboranes, undefined radicals, undeciphered designations (e.g., amino acids) beyond the simplest abbreviations (i.e., Me, Et, Pr, Bu, Ph, Ac), names of radicals instead of their structure, or incomplete indication of the ligand structure (e.g., L = P, N).
5.5. Compounds must not be reaction intermediate or precursor.
6. If you cannot find a required field for an object, re-check the context; if it’s still absent, set that field’s value to `""NOT_DETECTED""`.  
7. The example of JSON below shows only two extracted samples, however your output should contain **all** mentions of organometallic complexes and / or chelate ligands present in the article.
Output **must** be a single JSON array, like:
[
    {
        ""compound_id"": ""L3"",
        ""compound_name"": ""DOTA"",
        ""SMILES"": ""O=C(O)CN(CCN(CC(=O)O)CC(=O)O)CC(=O)O"",
        ""SMILES_type"": ""ligand"",
        ""target"": 21.3
    },
    {
        ""compound_id"": ""A31"",
        ""compound_name"": ""tebroxime"",
        ""SMILES"": ""[C-]#[N+]CC(C)(C)OC.[C-]#[N+]CC(C)(C)OC.[C-]#[N+]CC(C)(C)OC.[C-]#[N+]CC(C)(C)OC.[C-]#[N+]CC(C)(C)OC.[C-]#[N+]CC(C)(C)OC"",
        ""SMILES_type"": ""environment"",
        ""target"": 17.9
    }
]
"""

TC_PROMPT = """
Your task is to extract **every** mention of organometallic complexes and chelate ligands from scientific article, and output a **JSON array** of objects **only** (no markdown, no commentary, no extra text).
Fields for each object:
- `compound_id` (string): ID of a complex within the article, as cited in the text, e.g. `""L3""`, `""A31""`.  
- `compound_name` (string): abbreviated or full name of the complex or ligand as cited in the text, e.g. `""DOTA""`, `""tebroxime""`. 
- `SMILES` (string): full SMILES representation of ligand environment or single ligand.  If a complete organometallic complex is shown, extract all ligand structures without mentioning the metal (e.g., ""COc1cc(C=CC([O-])CC([O-])CC([O-])C=Cc2ccc(O)c(OC)c2)ccc1O. [C-]#[O+].[C-]#[O+].[C-]#[O+].[OH-]""). For a chelate ligand without a complete organometallic complex, extract only that ligand's structure (e.g., 'O=C(O)CN(CCN(CC(CC(=O)O)CC(=O)O)CCN(CC(=O)O)CC(=O)O').
- `SMILES_type` (string): one of `""ligand""` or `""environment""`. ""environment"" refers to the entire organometallic complex, including one or more ligands and a metal atom. ""ligand"" signifies a single chelate ligand, which is an organic molecule.
- `target_value` (number): the numeric value of logarithms of thermodynamic stability constants lgK or logK (without quotes). 
Extraction rules:
1. Extract **each** mention of `target_value` (lgK or logK) as a separate object.  
2. Do **not** filter, group, summarize, or deduplicate. Include repeated mentions and duplicates if they occur in different contexts.  
3. If a molecule is fully depicted in a figure, write it as a SMILES string. If a molecule is depicted as a scaffold and residues separately in different places of an article, connect them by compound ID or name into one molecule and write it a single SMILES string.
4. If multiple thermodynamic stability constants appear for the same complex or ligand extract each separately. 
5. Extract only structures that comply with these rules:
5.1. The complexes must contain **Tc** as the metal or the ligands must belong to complexes of that metal.
5.2. The complete molecular structure shall be given without errors in it or identifiers.
5.3. Compounds must contain more than one carbon (exclude CO, Me).
5.4. Compounds must not contain polymeric structures, attached biomolecules or carboranes, undefined radicals, undeciphered designations (e.g., amino acids) beyond the simplest abbreviations (i.e., Me, Et, Pr, Bu, Ph, Ac), names of radicals instead of their structure, or incomplete indication of the ligand structure (e.g., L = P, N).
5.5. Compounds must not be reaction intermediate or precursor.
6. If you cannot find a required field for an object, re-check the context; if it’s still absent, set that field’s value to `""NOT_DETECTED""`.  
7. The example of JSON below shows only two extracted samples, however your output should contain **all** mentions of organometallic complexes and / or chelate ligands present in the article.
Output **must** be a single JSON array, like:
[
    {
        ""compound_id"": ""L3"",
        ""compound_name"": ""DOTA"",
        ""SMILES"": ""O=C(O)CN(CCN(CC(=O)O)CC(=O)O)CC(=O)O"",
        ""SMILES_type"": ""ligand"",
        ""target"": 21.3
    },
    {
        ""compound_id"": ""A31"",
        ""compound_name"": ""tebroxime"",
        ""SMILES"": ""[C-]#[N+]CC(C)(C)OC.[C-]#[N+]CC(C)(C)OC.[C-]#[N+]CC(C)(C)OC.[C-]#[N+]CC(C)(C)OC.[C-]#[N+]CC(C)(C)OC.[C-]#[N+]CC(C)(C)OC"",
        ""SMILES_type"": ""environment"",
        ""target"": 17.9
    }
]
"""

LU_PROMPT = """
Your task is to extract **every** mention of organometallic complexes and chelate ligands from scientific article, and output a **JSON array** of objects **only** (no markdown, no commentary, no extra text).
Fields for each object:
- `compound_id` (string): ID of a complex within the article, as cited in the text, e.g. `""L3""`, `""A31""`.  
- `compound_name` (string): abbreviated or full name of the complex or ligand as cited in the text, e.g. `""DOTA""`, `""tebroxime""`. 
- `SMILES` (string): full SMILES representation of ligand environment or single ligand.  If a complete organometallic complex is shown, extract all ligand structures without mentioning the metal (e.g., ""COc1cc(C=CC([O-])CC([O-])CC([O-])C=Cc2ccc(O)c(OC)c2)ccc1O. [C-]#[O+].[C-]#[O+].[C-]#[O+].[OH-]""). For a chelate ligand without a complete organometallic complex, extract only that ligand's structure (e.g., 'O=C(O)CN(CCN(CC(CC(=O)O)CC(=O)O)CCN(CC(=O)O)CC(=O)O').
- `SMILES_type` (string): one of `""ligand""` or `""environment""`. ""environment"" refers to the entire organometallic complex, including one or more ligands and a metal atom. ""ligand"" signifies a single chelate ligand, which is an organic molecule.
- `target_value` (number): the numeric value of logarithms of thermodynamic stability constants lgK or logK (without quotes). 
Extraction rules:
1. Extract **each** mention of `target_value` (lgK or logK) as a separate object.  
2. Do **not** filter, group, summarize, or deduplicate. Include repeated mentions and duplicates if they occur in different contexts.  
3. If a molecule is fully depicted in a figure, write it as a SMILES string. If a molecule is depicted as a scaffold and residues separately in different places of an article, connect them by compound ID or name into one molecule and write it a single SMILES string.
4. If multiple thermodynamic stability constants appear for the same complex or ligand extract each separately. 
5. Extract only structures that comply with these rules:
5.1. The complexes must contain **Lu** as the metal or the ligands must belong to complexes of that metal.
5.2. The complete molecular structure shall be given without errors in it or identifiers.
5.3. Compounds must contain more than one carbon (exclude CO, Me).
5.4. Compounds must not contain polymeric structures, attached biomolecules or carboranes, undefined radicals, undeciphered designations (e.g., amino acids) beyond the simplest abbreviations (i.e., Me, Et, Pr, Bu, Ph, Ac), names of radicals instead of their structure, or incomplete indication of the ligand structure (e.g., L = P, N).
5.5. Compounds must not be reaction intermediate or precursor.
6. If you cannot find a required field for an object, re-check the context; if it’s still absent, set that field’s value to `""NOT_DETECTED""`.  
7. The example of JSON below shows only two extracted samples, however your output should contain **all** mentions of organometallic complexes and / or chelate ligands present in the article.
Output **must** be a single JSON array, like:
[
    {
        ""compound_id"": ""L3"",
        ""compound_name"": ""DOTA"",
        ""SMILES"": ""O=C(O)CN(CCN(CC(=O)O)CC(=O)O)CC(=O)O"",
        ""SMILES_type"": ""ligand"",
        ""target"": 21.3
    },
    {
        ""compound_id"": ""A31"",
        ""compound_name"": ""tebroxime"",
        ""SMILES"": ""[C-]#[N+]CC(C)(C)OC.[C-]#[N+]CC(C)(C)OC.[C-]#[N+]CC(C)(C)OC.[C-]#[N+]CC(C)(C)OC.[C-]#[N+]CC(C)(C)OC.[C-]#[N+]CC(C)(C)OC"",
        ""SMILES_type"": ""environment"",
        ""target"": 17.9
    }
]
"""