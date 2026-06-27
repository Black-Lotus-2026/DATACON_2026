# DataCon'26 ChemX FastAPI Web

FastAPI-приложение для финальной задачи DataCon'26: загрузка PDF/CSV/TSV/TXT/MD/ZIP, real-time отображение пайплайна химической экстракции, просмотр результатов и страницы с метриками ChemX.

## Что внутри

- `FastAPI` backend с HTML-страницами и JSON API.
- Главная страница для загрузки статьи или датасета ChemX.
- Real-time страница на Server-Sent Events для этапов `ingest -> preprocessing -> image evidence -> extraction -> evaluation`.
- Страница метрик с Macro-F1 baseline по доменам ChemX и результатами завершённых запусков.
- Экспорт результатов в CSV и JSON.
- Отмена активного запуска.
- Сохранение загруженных файлов в `uploads/`.
- Сохранение отчётов и артефактов запусков в `runs/`.
- Локальная эвристическая экстракция из CSV/TSV, текстовых файлов и PDF с selectable text.

## Запуск

```bash
python3 -m venv .venv
source .venv/bin/activate
pip install -r requirements.txt
uvicorn app.main:app --reload
```

Откройте:

```text
http://127.0.0.1:8000
```

## Scraper MVP

Первый слой scraper'а сохраняет PDF-разбор в SQLite: страницы, evidence-блоки,
caption'ы, таблицы, строки таблиц и FTS5-индекс для текстового поиска.
Подробная карта пайплайна лежит в `docs/scraper.md`.

```bash
source .venv/bin/activate
python -m app.services.scraper pdf-dataset/antibiotics-12-01220-v2.pdf \
  --out runs/scrape-antibiotics \
  --doc-id antibiotics_1220
```

Главный артефакт:

```text
runs/scrape-antibiotics/scrape.sqlite
runs/scrape-antibiotics/tables/*.csv
runs/scrape-antibiotics/images/figures/*.png
runs/scrape-antibiotics/visual_tasks.csv
```

Быстрые проверки:

```bash
sqlite3 runs/scrape-antibiotics/scrape.sqlite \
  "select source_type, count(*) from evidence_blocks group by source_type;"

sqlite3 runs/scrape-antibiotics/scrape.sqlite \
  "select page_number, label, substr(caption, 1, 100) from tables limit 10;"

sqlite3 runs/scrape-antibiotics/scrape.sqlite \
  "select source_type, substr(text, 1, 180) from evidence_fts where evidence_fts match 'antibio*' limit 5;"

sqlite3 runs/scrape-antibiotics/scrape.sqlite \
  "select priority, task_type, provider_hint, page_number, reason from visual_tasks order by priority desc limit 20;"
```

Structure detection executor:

```bash
python -m app.services.scraper.visual_executor \
  runs/scrape-antibiotics/scrape.sqlite \
  --provider heuristic
```

SOTA/optional DECIMER Segmentation provider:

```bash
conda create -n DECIMER_IMGSEG python=3.10
conda activate DECIMER_IMGSEG
pip install -r requirements-visual.txt
python -m app.services.scraper.visual_executor \
  runs/scrape-antibiotics/scrape.sqlite \
  --provider decimer
```

Structure crops and debug overlays:

```text
runs/scrape-antibiotics/images/structures/**/structure_*.png
runs/scrape-antibiotics/images/structures/**/_detections.png
```

OCSR executor over detected structure crops:

```bash
python -m app.services.scraper.ocsr_executor \
  runs/scrape-antibiotics/scrape.sqlite \
  --provider molscribe \
  --device cpu \
  --min-confidence 0.5
```

It writes recognized SMILES back to `structure_detections.smiles` and creates
RAG-ready `chemical_structure_smiles` evidence blocks. Scheme fragments are
kept with quality flags in metadata, so downstream extraction can treat
wildcards/R-groups separately from complete molecules.

```bash
sqlite3 runs/scrape-antibiotics/scrape.sqlite \
  "select parent_figure_id, smiles, image_path from structure_detections where smiles is not null limit 10;"
```

## Single-agent checker

Для текущего MVP можно проверить упрощённый контур без второго агента:

```text
PDF -> scraper -> structured SQLite evidence -> checker agent -> reports
```

```bash
python -m app.services.agent pdf-dataset/antibiotics-12-01220-v2.pdf \
  --out runs/agent-antibiotics \
  --domain Benzimidazoles \
  --doc-id antibiotics_1220
```

Checker использует локальные prompt-skill templates из ChemX:

```text
app/services/agent/skills/chemx_prompts/
```

Для реального LLM-вызова через VseGPT создайте локальный `.env`:

```bash
cp .env.example .env
```

```text
VSEGPT_API_KEY=sk-...
VSEGPT_BASE_URL=https://api.vsegpt.ru/v1
VSEGPT_MODEL=openai/gpt-4o-mini
```

И запустите агент с `--run-llm`:

```bash
python -m app.services.agent runs/agent-antibiotics/scrape/scrape.sqlite \
  --out runs/agent-antibiotics/agent_check \
  --domain Benzimidazoles \
  --run-llm
```

Артефакты:

```text
runs/agent-antibiotics/scrape/scrape.sqlite
runs/agent-antibiotics/agent_check/agent_report.json
runs/agent-antibiotics/agent_check/agent_report.md
runs/agent-antibiotics/agent_check/candidate_evidence.jsonl
runs/agent-antibiotics/agent_check/llm_result.json
runs/agent-antibiotics/agent_check/llm_raw.txt
```

Подробности: `docs/agent_checker.md`.

## Evaluator-backed ChemX agent

Добавлен отдельный контур `datacon_agent`: schema-driven LLM extractor для ChemX
доменов, OpenAlex downloader для open-access PDF/SI и evaluator-compatible
подсчёт Macro-F1 по настоящему truth dataset, а не по projected UI-оценке.

Запуск через OpenAI-compatible endpoint:

```bash
export OPENAI_API_KEY=...
export OPENAI_BASE_URL=https://caila.io/api/adapters/openai

python -m datacon_agent.cli download-pdfs \
  --domain nanozymes \
  --out-dir data/pdfs/nanozymes

python -m datacon_agent.cli batch \
  --domain nanozymes \
  --pdf-dir data/pdfs/nanozymes \
  --out outputs/nanozymes_gpt41_candidates.csv \
  --model just-ai/openai-proxy/gpt-4.1 \
  --review-model just-ai/openai-proxy/gpt-4.1 \
  --pages-per-window 5 \
  --max-image-pages-per-window 3 \
  --review-context-chars 60000

python -m datacon_agent.cli review-csv \
  --domain nanozymes \
  --pred outputs/nanozymes_gpt41_candidates.csv \
  --pdf-dir data/pdfs/nanozymes \
  --out outputs/nanozymes_gpt41_reviewed.csv \
  --model just-ai/openai-proxy/gpt-4.1 \
  --review-model just-ai/openai-proxy/gpt-4.1 \
  --review-context-chars 60000 \
  --passes 2

find data/pdfs/nanozymes -maxdepth 1 -type f -name '*.pdf' \
  -printf '%f\n' | sed 's/\.pdf$//' | sort > outputs/nanozymes_articles.txt

python -m datacon_agent.cli evaluate \
  --domain nanozymes \
  --pred outputs/nanozymes_gpt41_reviewed.csv \
  --articles outputs/nanozymes_articles.txt \
  --out outputs/nanozymes_metrics_gpt41.csv
```

Контрольный прогон на 9 скачанных Nanozymes PDF показал Macro-F1 `0.615949`
против `0.290701` у single-agent baseline на той же подвыборке статей
(`+0.325248`). На 5 PDF после финальной нормализации получено `0.625000`
против `0.349333` у baseline. Для официальной оценки нужно догрузить все
доступные PDF/SI и прогнать тот же evaluator по полному article subset.

## Multi-agent chemical image pipeline

Для анализа научных схем и отдельного chemical OCR добавлен контур:

```text
scraper SQLite
  -> DataImageAnalysisAgent
  -> ChemicalOCRAgent
  -> RDKit validation
  -> JSON/CSV
```

Специализированные prompt skills:

```text
app/services/agent/skills/specialized/data_image_analysis/SKILL.md
app/services/agent/skills/specialized/chemical_ocr/SKILL.md
```

Ограниченный тестовый запуск:

```bash
.venv-ocsr/bin/python -m app.services.agent.multi_agent_pipeline \
  runs/agent-antibiotics/scrape/scrape.sqlite \
  --out runs/agent-antibiotics/multi_agent \
  --data-model openai/gpt-4o-mini \
  --chemical-model openai/gpt-4o-mini \
  --data-limit 1 \
  --chemical-limit 3 \
  --no-response-format
```

Подробности: `docs/multi_agent_chemical_pipeline.md`.

## API

- `GET /` - страница загрузки.
- `GET /realtime` - live pipeline.
- `GET /metrics` - метрики ChemX.
- `POST /api/upload` - загрузка файла, поля формы: `dataset`, `domain`.
- `POST /api/demo-job` - демо-запуск без файла.
- `GET /api/jobs/{job_id}` - состояние запуска.
- `GET /api/jobs/{job_id}/events` - real-time события.
- `POST /api/jobs/{job_id}/cancel` - отмена активного запуска.
- `GET /api/jobs/{job_id}/export.csv` - экспорт извлечённых записей.
- `GET /api/jobs/{job_id}/export.json` - экспорт полного отчёта.
- `GET /api/metrics` - агрегированные метрики.

## Экстракция

В `app/services/jobs.py` уже есть локальный extractor:

- CSV/TSV нормализуются в ChemX-like записи.
- PDF обрабатывается через `pypdf`; поддерживаются PDF с selectable text.
- TXT/MD проходят через regex-эвристики для SMILES, DOI и экспериментальных свойств.
- ZIP сохраняется для подключения внешнего extractor.

Production-контур для ChemX-метрики вынесен в `datacon_agent`, чтобы UI-MVP
оставался быстрым, а leaderboard-оценка считалась воспроизводимо через
ChemX-compatible evaluator.
