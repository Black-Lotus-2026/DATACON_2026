# Hackathon ChemX bench run

Дата: 2026-06-28.

## Что запускалось

Запускался локальный `datacon_agent` на ChemX-style evaluator из проекта.
Отдельного runner-а в `DataCon26` нет: README хакатона требует Macro-F1 по
ChemX-доменам относительно опубликованного single-agent baseline.

API smoke через текущий `.env` прошел:

- `OPENAI_API_KEY` задан;
- `OPENAI_BASE_URL` задан;
- model по умолчанию: `gpt-4.1`;
- короткий JSON-запрос успешно вернулся.

## Результаты

### Сводная таблица

| Domain | EyeDrops | Benzimidazoles | Oxazolidinones | Co-crystals | Complexes | Nanozymes | Synergy | Nanomag | Cytotox | SelTox |
| --- | ---: | ---: | ---: | ---: | ---: | ---: | ---: | ---: | ---: | ---: |
| Baseline | - | 0.217 | 0.491 | 0.296 | 0.290 | 0.164 | 0.080 | 0.034 | 0.182 | 0.045 |
| Current | - | 0.393 | - | 0.286 | 0.056 | 0.648 | 0.138 | 0.148 | 0.154 | 0.094 |
| Delta | - | +0.176 | - | -0.010 | -0.234 | +0.484 | +0.058 | +0.114 | -0.028 | +0.049 |

`Current` заполнен только для доменов, которые реально запускались в этом
bench-run. EyeDrops не имеет опубликованного single-agent baseline в README
хакатона и в локальном CSV не содержит open-access PDF (`access=1`).
Oxazolidinones не запущен: оба open-access DOI из локального ChemX CSV не
скачались через текущий OpenAlex-only downloader.

| Домен | PDF subset | Режим | Macro-F1 | Published single-agent baseline | Итог |
| --- | ---: | --- | ---: | ---: | --- |
| Benzimidazoles | 4 PDF | text, no review | 0.393453 | 0.217 | выше baseline |
| Co-crystals | 1 PDF | vision + review | 0.285714 | 0.296 | чуть ниже baseline |
| Complexes | 1 PDF | text, no review | 0.055556 | 0.290 | ниже baseline |
| Nanozymes | 5 PDF | text, no review | 0.647500 | 0.164 | выше baseline |
| Synergy | 1 PDF | vision + review | 0.137931 | 0.080 | выше baseline |
| Nanomag | 9 PDF | text, no review | 0.147530 | 0.034 | выше baseline |
| Cytotox | 2 PDF | text, no review | 0.153509 | 0.182 | ниже baseline |
| SelTox | 8 PDF | text, no review | 0.094281 | 0.045 | выше baseline |

Для Benzimidazoles есть еще более честное сравнение на той же 4-PDF
подвыборке с локальным ChemX single-agent artifact: `0.393453` против
`0.295098`.

## Локальные артефакты

Файлы лежат локально в ignored-директории:

```text
runs/hackathon-bench/outputs/benzimidazole_gpt41_text_noreview.csv
runs/hackathon-bench/outputs/benzimidazole_metrics_gpt41_text_noreview.csv
runs/hackathon-bench/outputs/cocrystals_gpt41.csv
runs/hackathon-bench/outputs/cocrystals_metrics_gpt41.csv
runs/hackathon-bench/outputs/complexes_gpt41_text_noreview.csv
runs/hackathon-bench/outputs/complexes_metrics_gpt41_text_noreview.csv
runs/hackathon-bench/outputs/nanozymes_gpt41_text_noreview.csv
runs/hackathon-bench/outputs/nanozymes_metrics_gpt41_text_noreview.csv
runs/hackathon-bench/outputs/synergy_gpt41.csv
runs/hackathon-bench/outputs/synergy_metrics_gpt41.csv
runs/hackathon-bench/outputs/magnetic_gpt41_text_noreview.csv
runs/hackathon-bench/outputs/magnetic_metrics_gpt41_text_noreview.csv
runs/hackathon-bench/outputs/cytotoxicity_gpt41_text_noreview.csv
runs/hackathon-bench/outputs/cytotoxicity_metrics_gpt41_text_noreview.csv
runs/hackathon-bench/outputs/seltox_gpt41_text_noreview.csv
runs/hackathon-bench/outputs/seltox_metrics_gpt41_text_noreview.csv
```

## Команды

```bash
python -m datacon_agent.cli batch \
  --domain cocrystals \
  --pdf-dir runs/chemx-all-domains/pdfs_cocrystals \
  --out runs/hackathon-bench/outputs/cocrystals_gpt41.csv \
  --pages-per-window 5 \
  --max-image-pages-per-window 3 \
  --review-context-chars 60000

python -m datacon_agent.cli evaluate \
  --domain cocrystals \
  --pred runs/hackathon-bench/outputs/cocrystals_gpt41.csv \
  --truth-csv ChemX/datasets/Co-crystals.csv \
  --articles runs/hackathon-bench/outputs/cocrystals_articles.txt \
  --out runs/hackathon-bench/outputs/cocrystals_metrics_gpt41.csv

python -m datacon_agent.cli batch \
  --domain synergy \
  --pdf-dir runs/chemx-all-domains/pdfs_synergy \
  --out runs/hackathon-bench/outputs/synergy_gpt41.csv \
  --pages-per-window 5 \
  --max-image-pages-per-window 3 \
  --review-context-chars 60000

python -m datacon_agent.cli evaluate \
  --domain synergy \
  --pred runs/hackathon-bench/outputs/synergy_gpt41.csv \
  --truth-csv ChemX/datasets/Synergy.csv \
  --articles runs/hackathon-bench/outputs/synergy_articles.txt \
  --out runs/hackathon-bench/outputs/synergy_metrics_gpt41.csv

python -m datacon_agent.cli batch \
  --domain benzimidazole \
  --pdf-dir runs/chemx-check/pdfs_benzimidazole \
  --out runs/hackathon-bench/outputs/benzimidazole_gpt41_text_noreview.csv \
  --pages-per-window 4 \
  --no-images \
  --no-review

python -m datacon_agent.cli evaluate \
  --domain benzimidazole \
  --pred runs/hackathon-bench/outputs/benzimidazole_gpt41_text_noreview.csv \
  --truth-csv ChemX/datasets/Benzimidazoles.csv \
  --articles runs/hackathon-bench/outputs/benzimidazole_articles.txt \
  --out runs/hackathon-bench/outputs/benzimidazole_metrics_gpt41_text_noreview.csv
```

## Наблюдения

- По текущему subset выше published baseline вышли 5 доменов:
  `Benzimidazoles`, `Nanozymes`, `Synergy`, `Nanomag`, `SelTox`.
- Это покрывает оба направления ChemX: малые молекулы (`Benzimidazoles`) и
  наноматериалы (`Nanozymes`, `Synergy`, `Nanomag`, `SelTox`).
- Vision + review прошел на коротких `cocrystals` и `synergy`.
- 4-PDF `benzimidazole` в vision + review режиме завис на OpenRouter network
  read больше чем на 6 минут на первом window-запросе, поэтому был остановлен.
- `benzimidazole` в text/no-review режиме стабильно прошел 4 PDF за 2 минуты.
- `Complexes`, `Nanozymes`, `Nanomag`, `Cytotox`, `SelTox` запускались в
  стабильном text/no-review режиме после расширенного скачивания PDF.
- Главный следующий bottleneck для полноценного multi-domain bench: downloader
  и resume/timeout для тяжелых PDF streams. `Cytotox` и `SelTox` частично
  скачались даже при прерванном download, но manifest в таких случаях не
  отражает все уже сохраненные PDF.
