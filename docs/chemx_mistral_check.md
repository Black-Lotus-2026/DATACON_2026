# ChemX-проверка на Mistral

Дата локального прогона: 2026-06-28.

Цель проверки — не заменить полный ChemX benchmark, а быстро проверить, как
актуальный scraper-first контур ведет себя на настоящих ChemX PDF из домена
`benzimidazole`.

## Конфигурация

LLM endpoint:

```env
OPENAI_BASE_URL=https://api.mistral.ai/v1
OPENAI_API_KEY=<local secret>
```

Модель:

```text
mistral-large-latest
```

Ключ хранится только локально в `.env` и не коммитится.

## Данные

Команда загрузки PDF:

```bash
.venv/bin/python -m datacon_agent.cli download-pdfs \
  --domain benzimidazole \
  --out-dir runs/chemx-check/pdfs_benzimidazole \
  --limit 20 \
  --mailto kamilisxakof@gmail.com \
  --no-supplementary
```

Из 9 open-access статей downloader смог скачать 4 PDF:

```text
d2ra06667j
intechopen.108949
s13065-018-0479-1
s41598-022-21435-6
```

Список зафиксирован в:

```text
runs/chemx-check/articles_benzimidazole_downloaded.txt
```

## Проверка evaluator

Перед LLM-прогоном был проверен evaluator на готовом ChemX baseline:

```bash
.venv/bin/python -m datacon_agent.cli evaluate \
  --domain benzimidazole \
  --pred ChemX/LLM/result/from_single_agent/benzimidazole/pred.csv \
  --truth-csv ChemX/datasets/Benzimidazoles.csv \
  --out runs/chemx-check/metrics_benzimidazole_single_agent_datacon.csv
```

Результат:

```text
Macro-F1: 0.216976
```

На тех же 4 скачанных PDF baseline single-agent дает:

```text
Macro-F1: 0.295098
```

## TablePlanner-only

Чтобы отделить deterministic evidence layer от LLM, был собран prediction CSV
только из `agent_conflict_decisions` после scraper + evidence agents.

Результат на 4 PDF:

```text
Macro-F1: 0.240386
```

Это не финальная система, а проверка того, что structured table evidence само по
себе извлекает полезные факты. Сильнее всего ловятся `target_type` и
`target_relation`; слабые поля — `smiles`, exact `bacteria`, `target_value`.

## Mistral smoke с review

Один PDF был прогнан в полном scraper-first режиме с review-pass:

```bash
.venv/bin/python -m datacon_agent.cli extract \
  --domain benzimidazole \
  --pdf runs/chemx-check/pdfs_benzimidazole/s13065-018-0479-1.pdf \
  --out runs/chemx-check/pred_smoke_mistral_s13065.csv \
  --model mistral-large-latest \
  --review-model mistral-large-latest \
  --base-url https://api.mistral.ai/v1 \
  --use-scraper \
  --run-evidence-agents \
  --no-images
```

Результат:

```text
Macro-F1: 0.714286
```

По этому PDF модель идеально попала в `compound_id`, `target_type`,
`target_relation`, `target_value`, `target_units`. Поля `smiles` и exact
`bacteria` остались проблемными: SMILES не извлекались, а ChemX сравнивает
исходные строки `Ec`/`Sa`, тогда как модель часто возвращает полные названия
организмов.

## Mistral no-review на 4 PDF

Полный batch с review-pass уперся в лимит Mistral:

```text
429 Rate limit exceeded
```

Поэтому 4 PDF были прогнаны по одному в режиме `--no-review` с паузами между
запросами:

```bash
.venv/bin/python -m datacon_agent.cli extract \
  --domain benzimidazole \
  --pdf <pdf> \
  --out runs/chemx-check/pred_mistral_<article>_noreview.csv \
  --model mistral-large-latest \
  --base-url https://api.mistral.ai/v1 \
  --use-scraper \
  --run-evidence-agents \
  --no-images \
  --no-review
```

Итоговый объединенный файл:

```text
runs/chemx-check/pred_benzimidazole_mistral_scraper_noreview_4pdf.csv
```

Метрика:

```text
Macro-F1: 0.274310
```

По полям:

```text
compound_id      F1 0.435367
smiles           F1 0.000000
target_type      F1 0.522576
target_relation  F1 0.522576
target_value     F1 0.439650
target_units     F1 0.000000
bacteria         F1 0.000000
```

## Вывод

1. `TablePlanner` полезен: без LLM он дает проверяемые structured facts и
   приближается к baseline на части полей.
2. Без review-pass Mistral генерирует много лишних строк: recall высокий, но
   precision проседает.
3. Review-pass резко улучшает качество на `s13065-018-0479-1`, но текущий
   Mistral rate limit мешает прогнать batch без backoff/retry.
4. Главные следующие задачи:
   - добавить retry/backoff для `RateLimitError`;
   - нормализовать `bacteria` под ChemX exact strings или использовать
     `bacteria_unified` при диагностике;
   - подключить visual/OCSR/chemical-agent слой, иначе `smiles` останется
     нулевым;
   - улучшить units normalization: `μg/mL`, `µg/mL`, `µg mL−1` должны лучше
     совпадать с truth.

