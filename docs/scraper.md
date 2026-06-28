# Архитектура скрапера

Скрапер нужен не для финального извлечения ChemX-записей за один проход, а для
подготовки проверяемого слоя свидетельств (`evidence`). Он разбирает PDF на
небольшие прослеживаемые фрагменты и сохраняет их в SQLite: текстовые блоки,
подписи (`caption`), строки таблиц, изображения, кандидаты химических структур
и распознанные SMILES.

Главная идея: следующий RAG/LLM-экстрактор должен работать не со всем PDF сразу,
а с релевантными кусками, у которых есть ссылка на страницу, таблицу, подпись,
вырез изображения (`crop`) или исходный парсер.

## Чем это отличается от ChemX

В локальном `ChemX/LLM` baseline нет отдельного химического OCR/OCSR-пайплайна.
Там используются три основных режима:

- `from_pdf`: PDF загружается в OpenAI Assistants, включается `file_search`, и
  `gpt-4o` сразу просят вернуть JSON по схеме датасета.
- `from_image`: PDF сначала рендерится в JPEG-страницы, затем все страницы
  отправляются в `gpt-4o` Vision с prompt'ом под конкретный датасет.
- `from_single_agent`: используются уже подготовленные prediction/metrics.

То есть ChemX в основном полагается на рассуждение GPT-4o поверх PDF или
картинок страниц. Наш скрапер делает промежуточный слой явным: каждый вывод
парсера сохраняется, индексируется, связан с источником и может быть отдельно
проверен до финального LLM-извлечения.

Полезные файлы ChemX для сравнения:

- `ChemX/LLM/src/pdf_extraction.py`
- `ChemX/LLM/src/pdf_to_images.py`
- `ChemX/LLM/src/images_extraction.py`

## Общий пайплайн

1. `pdf_scraper.py`

   Базовый PDF-разбор. Он:

   - читает выделяемый текст (`selectable text`) через PyMuPDF;
   - выделяет страницы, параграфы, заголовки секций и подписи;
   - извлекает таблицы через эвристики верстки и `pdfplumber`;
   - сохраняет строки таблиц как отдельные блоки свидетельств;
   - экспортирует таблицы в CSV для ручной проверки;
   - вырезает рисунки и схемы, связанные с подписями;
   - создает очередь визуальных задач;
   - пишет результат в SQLite.

2. `visual_router.py`

   Легкий маршрутизатор, который решает, какие тяжелые визуальные операции
   потенциально нужны. Он не запускает OCR/OCSR сам, а только создает задачи:

   - `document_ocr`, если на странице мало выделяемого текста;
   - `table_ocr`, если страница упоминает таблицу, но таблица не восстановлена;
   - `chemical_structure_detection`, если рисунок или схема похожи на химические;
   - `ocsr`, если после поиска структур нужно получить SMILES;
   - `vlm_describe` или `image_text_ocr` для информативных изображений.

3. `visual_executor.py`

   Исполнитель для `chemical_structure_detection`. Сейчас есть два режима:

   - `heuristic`: локальная легкая эвристика по связанным компонентам;
   - `decimer`: DECIMER Segmentation, более сильный вариант для химических схем.

   Результат сохраняется в `structure_detections`: путь к вырезу, провайдер,
   уверенность (`confidence`), метаданные и связь с исходным рисунком или схемой.

4. `ocsr_executor.py`

   Исполнитель для распознавания структурных вырезов в SMILES. Сейчас
   используется MolScribe:

   - берет вырезы из `structure_detections`;
   - отбрасывает слишком маленькие или странные вырезы;
   - запускает MolScribe;
   - применяет порог уверенности;
   - валидирует SMILES через RDKit;
   - пишет принятые SMILES обратно в `structure_detections.smiles`;
   - создает готовые для RAG блоки свидетельств `chemical_structure_smiles`.

## Что считается результатом

В скрапере есть несколько уровней результата, их важно не путать:

- `figures/*.png` — сырые вырезы рисунков и схем из PDF.
- `visual_tasks` — очередь задач, то есть намерение что-то проверить визуально.
- `structure_detections` без `smiles` — вырезы-кандидаты химических структур.
- `structure_detections.smiles` — OCSR-результат, прошедший фильтры.
- `evidence_blocks` — то, что готово для RAG, поиска и LLM-экстракции.

Для RAG основная таблица — `evidence_blocks`, а не папка с картинками. Картинки
нужны для проверки источника и как вход для визуальных исполнителей.

## SQLite-схема

Основной артефакт:

```text
runs/<имя-запуска>/scrape.sqlite
```

Ключевые таблицы:

- `documents`: один PDF-документ, его путь и hash.
- `files`: файлы внутри документа; сейчас обычно один PDF с `file_id = main`.
- `pages`: страницы PDF, размеры и выделяемый текст.
- `evidence_blocks`: главная таблица фрагментов свидетельств для RAG.
- `evidence_fts`: FTS5-индекс по `evidence_blocks`.
- `tables`: восстановленные таблицы, подпись, колонки, bbox, парсер.
- `table_rows`: строки таблиц и связь со свидетельством уровня строки.
- `figures`: вырезанные изображения и схемы, подпись, тип, bbox.
- `visual_tasks`: очередь тяжелых OCR/OCSR/VLM задач.
- `structure_detections`: вырезы химических структур и OCSR-результаты.
- `ocr_blocks`: зарезервировано под будущие OCR-исполнители.
- `diagnostics`: агрегированные счетчики и notes по документу.

Типы `evidence_blocks.source_type`, которые сейчас используются:

- `paragraph`
- `section_heading`
- `table_caption`
- `table_row`
- `figure_caption`
- `figure_image`
- `scheme_image`
- `chemical_structure_image`
- `chemical_structure_smiles`

## Structured evidence agents

После базового скрапера можно запустить локальный слой `datacon_agent`
evidence-agents. Это не LLM-агенты, а воспроизводимые правила поверх SQLite,
которые превращают сырые строки таблиц и SMILES-блоки в более удобные факты для
финального ChemX-экстрактора.

Главный поток:

```text
tables/table_rows
  -> TablePlanner
  -> TableMeasurementAgent
  -> CompoundLinkingAgent
  -> ConflictResolverAgent
  -> ScaffoldResolverAgent
  -> agent_* tables + evidence_blocks
```

`TablePlanner` строит план один раз на таблицу:

- где находится столбец соединения (`compound_column_index`);
- какие столбцы являются измерениями;
- какой `target_type` у таблицы или столбца (`MIC`, `INHIBITION_ZONE`, `IC50`);
- какие units следует использовать (`µg/mL`, `µmol mL−1`, `mm`);
- какой организм соответствует столбцу (`S. aureus`, `E. coli`, ...).

Например таблица вида:

```text
Compound | S. aureus | P. aeruginosa | E. coli | S. typhosa
63a      | 28        | 26            | 21      | 19
```

после планирования превращается не в одну строку, а в четыре measurement facts:

```text
63a + Staphylococcus aureus -> INHIBITION_ZONE 28 mm
63a + Pseudomonas aeruginosa -> INHIBITION_ZONE 26 mm
63a + Escherichia coli -> INHIBITION_ZONE 21 mm
63a + Salmonella typhosa -> INHIBITION_ZONE 19 mm
```

План сохраняется в `agent_table_measurements.metadata_json` в полях
`table_plan` и `column_plan`. Это важно для отладки: можно понять, почему агент
решил, что конкретный столбец является measurement-столбцом.

Таблицы structured evidence layer:

- `agent_table_measurements`: нормализованные измерения из таблиц.
- `agent_compound_links`: связь `compound_id + measurement + SMILES`.
- `agent_conflict_decisions`: выбор canonical record или `needs_review`.
- `agent_scaffold_resolutions`: найденные scaffold/R-group случаи.

Каждая запись также публикуется обратно в `evidence_blocks` с source type:

- `agent_table_measurement`
- `agent_compound_link`
- `agent_conflict_decision`
- `agent_scaffold_resolution`

Так финальный `ChemExtractionAgent` видит не только сырой текст PDF, но и
структурированный контекст, который уже связан со страницей, таблицей и исходной
строкой.

## Команды запуска

Базовый PDF-скрапер:

```bash
source .venv/bin/activate
python -m app.services.scraper pdf-dataset/antibiotics-12-01220-v2.pdf \
  --out runs/scrape-antibiotics \
  --doc-id antibiotics_1220
```

Главные файлы после запуска:

```text
runs/scrape-antibiotics/scrape.sqlite
runs/scrape-antibiotics/tables/*.csv
runs/scrape-antibiotics/images/figures/*.png
runs/scrape-antibiotics/visual_tasks.csv
```

DECIMER Segmentation для поиска вырезов структур:

```bash
mamba run -n DECIMER_IMGSEG python -m app.services.scraper.visual_executor \
  runs/scrape-antibiotics/scrape.sqlite \
  --provider decimer
```

MolScribe OCSR по найденным вырезам:

```bash
mamba run -n DECIMER_IMGSEG python -m app.services.scraper.ocsr_executor \
  runs/scrape-antibiotics/scrape.sqlite \
  --provider molscribe \
  --device cpu \
  --min-confidence 0.5
```

Почему `--device cpu`: на Mac PyTorch/MolScribe может упереться в операции,
которые не реализованы для MPS. CPU медленнее, но надежнее для текущего MVP.

## Как смотреть результат

Счетчики по evidence:

```bash
sqlite3 runs/scrape-antibiotics/scrape.sqlite \
  "select source_type, count(*) from evidence_blocks group by source_type;"
```

Первые таблицы:

```bash
sqlite3 runs/scrape-antibiotics/scrape.sqlite \
  "select page_number, label, substr(caption, 1, 100) from tables limit 10;"
```

Строки конкретной таблицы:

```bash
sqlite3 runs/scrape-antibiotics/scrape.sqlite \
  "select row_index, normalized_text from table_rows where table_id = 'TABLE_ID' order by row_index;"
```

Распознанные SMILES:

```bash
sqlite3 runs/scrape-antibiotics/scrape.sqlite \
  "select parent_figure_id, smiles, confidence, image_path from structure_detections where smiles is not null;"
```

Поиск через FTS:

```bash
sqlite3 runs/scrape-antibiotics/scrape.sqlite \
  "select source_type, substr(text, 1, 180) from evidence_fts where evidence_fts match 'antimicrobial' limit 10;"
```

Очередь визуальных задач:

```bash
sqlite3 runs/scrape-antibiotics/scrape.sqlite \
  "select priority, task_type, provider_hint, page_number, reason from visual_tasks order by priority desc limit 20;"
```

## Почему не нужно обрабатывать все изображения одинаково

Не каждое изображение полезно для химического извлечения. Поэтому пайплайн
разделен на два этапа:

1. Сначала сохраняются вырезы рисунков и схем как проверяемые свидетельства.
2. Потом `visual_router.py` решает, какие изображения действительно требуют
   OCR, поиска структур, OCSR или VLM-описания.

Это позволяет не гонять тяжелые модели по всему PDF. Например:

- если страница уже имеет хороший выделяемый текст, OCR всей страницы не нужен;
- если таблица восстановлена текстовым парсером, table OCR можно не запускать;
- если рисунок не похож на химически насыщенную схему, OCSR ему не нужен;
- если DECIMER-вырез оказался реакционной схемой с несколькими компонентами,
  MolScribe-результат должен проходить RDKit/confidence-фильтры.

## Текущие ограничения

- Таблицы извлекаются полезно, но не идеально. Некоторые PDF-верстки все еще
  требуют ремонта под конкретный тип таблиц или отдельного table OCR/parser.
- Вырезы по подписям иногда слишком широкие: в них может попасть соседний текст,
  стрелка, условия реакции или часть другой структуры.
- DECIMER хорошо ищет химические области, но в схемах часто возвращает
  фрагменты реакции, а не отдельные молекулы.
- MolScribe полезен для одиночных структур, но его вывод по фрагментам
  реакционных схем нельзя считать финальной химической записью.
- `visual_tasks` могут быть многочисленными. Это нормально: задача router'а —
  сохранить план возможных тяжелых проверок, а не гарантировать, что все они
  должны быть выполнены.

## Что улучшать следующим шагом

- Добавить OCR executor для `document_ocr`, `table_ocr`, `image_text_ocr`.
- Сделать более строгий classifier для рисунков и схем перед OCSR.
- Разделять реакционные схемы на отдельные molecule-level вырезы до MolScribe.
- Добавить экспорт принятых свидетельств в JSONL для будущего RAG-индекса.
- Добавить viewer/CLI-команду, которая рядом показывает вырез, подпись и SMILES.
