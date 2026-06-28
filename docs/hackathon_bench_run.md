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

| Домен | PDF subset | Режим | Macro-F1 | Published single-agent baseline | Итог |
| --- | ---: | --- | ---: | ---: | --- |
| Benzimidazoles | 4 PDF | text, no review | 0.393453 | 0.217 | выше baseline |
| Synergy | 1 PDF | vision + review | 0.137931 | 0.080 | выше baseline |
| Co-crystals | 1 PDF | vision + review | 0.285714 | 0.296 | чуть ниже baseline |

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
runs/hackathon-bench/outputs/synergy_gpt41.csv
runs/hackathon-bench/outputs/synergy_metrics_gpt41.csv
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

- Vision + review прошел на коротких `cocrystals` и `synergy`.
- 4-PDF `benzimidazole` в vision + review режиме завис на OpenRouter network
  read больше чем на 6 минут на первом window-запросе, поэтому был остановлен.
- `benzimidazole` в text/no-review режиме стабильно прошел 4 PDF за 2 минуты.
- Главный следующий bottleneck для полноценного multi-domain bench: downloader.
  По первым двум open-access строкам на домен скачались только `cocrystals` и
  `synergy`; остальные DOI часто дают `not_found` через текущий OpenAlex-only
  путь.
