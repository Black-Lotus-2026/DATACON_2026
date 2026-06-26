# Scraper Architecture

This scraper is an evidence builder for the later ChemX/RAG extraction layer. It
does not try to solve final relation extraction in one pass. Instead, it stores
small, traceable document fragments in SQLite so downstream steps can retrieve
only the relevant text, table rows, figure crops, and recognized structures.

## How ChemX Baseline Works

The local `ChemX/LLM` baseline does not use a dedicated chemical OCR/OCSR stack.
It has three main modes:

- `from_pdf`: uploads the PDF to OpenAI Assistants with `file_search` and asks
  `gpt-4o` for JSON matching a dataset schema.
- `from_image`: converts PDF pages to JPEG images and sends all page images to
  `gpt-4o` Vision with the same schema-first prompt style.
- `from_single_agent`: stores already produced predictions/metrics.

So ChemX recognition is mostly model-side GPT-4o reasoning over PDF or rendered
page images. Our scraper is more explicit: every parser output is persisted,
queryable, and linked to its page/caption/crop before LLM extraction.

Relevant ChemX files:

- `ChemX/LLM/src/pdf_extraction.py`
- `ChemX/LLM/src/pdf_to_images.py`
- `ChemX/LLM/src/images_extraction.py`

## Pipeline

1. `pdf_scraper.py`
   - reads selectable PDF text with PyMuPDF;
   - splits paragraphs, section headings, captions;
   - extracts table candidates with layout heuristics and `pdfplumber`;
   - exports table CSV files for manual inspection;
   - crops caption-linked figures/schemes;
   - writes everything into SQLite.

2. `visual_router.py`
   - decides which visual tasks are worth running;
   - creates tasks for document OCR, table OCR, structure detection, OCSR,
     VLM description, or light image OCR;
   - does not run heavy models itself.

3. `visual_executor.py`
   - runs chemical structure detection tasks;
   - supports a lightweight heuristic provider and optional DECIMER Segmentation;
   - stores structure crop candidates in `structure_detections`.

4. `ocsr_executor.py`
   - runs OCSR over structure crops using MolScribe;
   - validates output with confidence threshold and RDKit parsing;
   - writes accepted SMILES back to `structure_detections.smiles`;
   - creates `chemical_structure_smiles` evidence blocks for RAG.

## Main SQLite Tables

- `documents`, `files`, `pages`: document identity and page text.
- `evidence_blocks`: RAG-ready fragments. This includes paragraphs, captions,
  table rows, figure references, structure crop references, and accepted SMILES.
- `evidence_fts`: FTS5 index over evidence text.
- `tables`, `table_rows`: structured table extraction plus row-level evidence.
- `figures`: cropped figures/schemes with captions and local image paths.
- `visual_tasks`: deferred heavy-model work queue.
- `structure_detections`: structure crop candidates and OCSR results.
- `ocr_blocks`: reserved for future OCR executors.

## Commands

Run the base PDF scraper:

```bash
source .venv/bin/activate
python -m app.services.scraper pdf-dataset/antibiotics-12-01220-v2.pdf \
  --out runs/scrape-antibiotics \
  --doc-id antibiotics_1220
```

Run DECIMER structure segmentation in the optional visual environment:

```bash
mamba run -n DECIMER_IMGSEG python -m app.services.scraper.visual_executor \
  runs/scrape-antibiotics/scrape.sqlite \
  --provider decimer
```

Run MolScribe OCSR over detected crops:

```bash
mamba run -n DECIMER_IMGSEG python -m app.services.scraper.ocsr_executor \
  runs/scrape-antibiotics/scrape.sqlite \
  --provider molscribe \
  --device cpu \
  --min-confidence 0.5
```

Inspect stored evidence:

```bash
sqlite3 runs/scrape-antibiotics/scrape.sqlite \
  "select source_type, count(*) from evidence_blocks group by source_type;"

sqlite3 runs/scrape-antibiotics/scrape.sqlite \
  "select parent_figure_id, smiles, confidence, image_path from structure_detections where smiles is not null;"
```

## Current Limitations

- Table extraction is useful but not final. Some PDF layouts still need
  table-specific repair or a stronger table OCR/parser.
- Caption-based figure crops can be too broad. This is acceptable for routing,
  but reaction schemes often need finer segmentation before OCSR.
- DECIMER crops from schemes can contain multiple reactants, arrows, labels, or
  conditions. MolScribe output for those crops should be treated as draft
  evidence, not a final chemical record.
- The scraper intentionally creates many visual tasks but only heavy executors
  decide what becomes accepted evidence.
