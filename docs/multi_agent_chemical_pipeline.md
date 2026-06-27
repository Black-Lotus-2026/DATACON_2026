# Multi-agent image and chemical OCR pipeline

Текущий контур разделяет понимание научной схемы и распознавание молекулярного
графа:

```text
PDF scraper
  -> structured SQLite + figures + DECIMER crops + optional MolScribe candidates
  -> DataImageAnalysisAgent
  -> ChemicalOCRAgent
  -> RDKit validation
  -> JSON + CSV
```

## Agent 1: data and image analysis

Код:

```text
app/services/agent/data_image_agent.py
```

Skill:

```text
app/services/agent/skills/specialized/data_image_analysis/SKILL.md
```

Агент получает:

- исходную фигуру или схему;
- подписанные DECIMER crops;
- caption и текст страницы;
- соседние paragraph/table evidence;
- существующие MolScribe-кандидаты как недоверенные hints.

Он возвращает метки соединений, связи `compound_id -> crop_label`, scaffold
описания и unresolved cases. Этот агент не имеет права генерировать SMILES.

## Agent 2: chemical OCR

Код:

```text
app/services/agent/chemical_ocr_agent.py
```

Skill:

```text
app/services/agent/skills/specialized/chemical_ocr/SKILL.md
```

Агент получает один crop, mapping первого агента и необязательный MolScribe
кандидат. Он возвращает SMILES-кандидат, confidence, decision и issue codes.

Код после LLM-вызова:

1. отклоняет wildcard/R-group SMILES;
2. валидирует синтаксис и канонизирует молекулу через RDKit;
3. использует валидный MolScribe candidate как fallback;
4. помечает результат `accepted`, `needs_review` или `rejected`;
5. запрещает финальный SMILES для unresolved scaffold.

## Подготовка данных

До запуска агентов должны быть выполнены scraper, structure detection и
MolScribe baseline:

```bash
python -m app.services.scraper pdf-dataset/antibiotics-12-01220-v2.pdf \
  --out runs/agent-antibiotics/scrape \
  --doc-id antibiotics_1220

.venv-ocsr/bin/python -m app.services.scraper.visual_executor \
  runs/agent-antibiotics/scrape/scrape.sqlite \
  --provider decimer

.venv-ocsr/bin/python -m app.services.scraper.ocsr_executor \
  runs/agent-antibiotics/scrape/scrape.sqlite \
  --provider molscribe \
  --device cpu \
  --min-confidence 0.5
```

## Запуск

Обе выбранные модели должны поддерживать изображения в OpenAI-compatible
`chat/completions`.

Для первого безопасного теста ограничьте число запросов:

```bash
.venv-ocsr/bin/python -m app.services.agent.multi_agent_pipeline \
  runs/agent-antibiotics/scrape/scrape.sqlite \
  --out runs/agent-antibiotics/multi_agent \
  --data-model openai/gpt-4o-mini \
  --chemical-model openai/gpt-4o-mini \
  --data-limit 1 \
  --chemical-limit 3 \
  --max-crops-per-figure 8 \
  --no-response-format
```

`--no-response-format` полезен для VseGPT backends, которые не принимают
`response_format=json_output`.

## Артефакты

```text
data_image_analysis.json
data_image_raw/*.txt
chemical_ocr_results.json
chemical_ocr_results.csv
chemical_ocr_raw/*.txt
multi_agent_summary.json
```

`chemical_ocr_results.csv` содержит:

```text
compound_id
figure_id
page_number
detection_id
smiles
canonical_smiles
smiles_source
validation_status
validation_error
mapping_confidence
agent_confidence
molscribe_confidence
```

## Ограничения

- Первый агент сопоставляет только видимые и обоснованные labels.
- Агент не назначает один scaffold всем соединениям диапазона.
- Для таблиц `R/R1/R2` нужен отдельный substituent resolver на RDKit.
- При отсутствии RDKit результат LLM получает статус `needs_review`.
- Vision-модель не заменяет RDKit и не является источником ground truth.

