# HF ChemX full OA bench run

Дата: 2026-06-28.

Источник датасетов: Hugging Face collection `ai-chem/chemx`.

## Что именно запускалось

Это полный прогон по **всем PDF, которые текущий downloader смог скачать** из
open-access subset ChemX. Это не полный benchmark по всем строкам датасетов:
ChemX truth лежит на Hugging Face, но сами PDF доступны не для всех `access=1`
записей через текущий OpenAlex-only downloader.

Режим extraction:

```text
PDF -> datacon_agent direct page text loader -> GPT-4.1 -> CSV -> evaluator
```

Параметры:

- model: `gpt-4.1`;
- endpoint: OpenAI-compatible `OPENAI_BASE_URL` из `.env`;
- mode: `text/no-review`;
- flags: `--no-images --no-review`;
- SQLite scraper, OCR, OCSR, DECIMER, MolScribe не использовались.

## Download coverage

| Domain | Manifest rows | PDF files | Downloaded | Exists | Not found |
| --- | ---: | ---: | ---: | ---: | ---: |
| EyeDrops | 0 | 0 | 0 | 0 | 0 |
| Benzimidazoles | 9 | 1 | 1 | 0 | 8 |
| Oxazolidinones | 2 | 0 | 0 | 0 | 2 |
| Co-crystals | 13 | 2 | 2 | 0 | 11 |
| Complexes | 4 | 1 | 1 | 0 | 3 |
| Nanozymes | 39 | 9 | 9 | 0 | 30 |
| Nanomag | 121 | 37 | 37 | 3 | 81 |
| Cytotox | 58 | 17 | 17 | 0 | 41 |
| SelTox | 140 | 24 | 24 | 0 | 116 |
| Synergy | 53 | 15 | 15 | 0 | 38 |

## Метрики

| Domain | EyeDrops | Benzimidazoles | Oxazolidinones | Co-crystals | Complexes | Nanozymes | Synergy | Nanomag | Cytotox | SelTox |
| --- | ---: | ---: | ---: | ---: | ---: | ---: | ---: | ---: | ---: | ---: |
| Baseline | - | 0.217 | 0.491 | 0.296 | 0.290 | 0.164 | 0.080 | 0.034 | 0.182 | 0.045 |
| Current | - | 0.142 | - | 0.321 | 0.080 | 0.511 | 0.104 | 0.121 | 0.151 | 0.115 |
| Delta | - | -0.075 | - | +0.025 | -0.210 | +0.347 | +0.024 | +0.087 | -0.031 | +0.070 |
| PDFs | 0 | 1 | 0 | 2 | 1 | 9 | 15 | 37 | 17 | 24 |

Выше published single-agent baseline на текущем downloaded subset:

- `Co-crystals`: `0.321429` vs `0.296`;
- `Nanozymes`: `0.511045` vs `0.164`;
- `Synergy`: `0.103502` vs `0.080`;
- `Nanomag`: `0.120786` vs `0.034`;
- `SelTox`: `0.115027` vs `0.045`.

Ниже baseline:

- `Benzimidazoles`: `0.142180` vs `0.217`;
- `Complexes`: `0.080000` vs `0.290`;
- `Cytotox`: `0.150907` vs `0.182`.

Не запущены:

- `EyeDrops`: в датасете нет `access=1` PDF;
- `Oxazolidinones`: оба open-access DOI не дали PDF через текущий downloader.

## Команды

Download:

```bash
for domain in benzimidazole oxazolidinone cocrystals complexes nanozymes magnetic cytotoxicity seltox synergy eyedrops; do
  python -m datacon_agent.cli download-pdfs \
    --domain "$domain" \
    --out-dir "runs/hf-full-bench/pdfs_$domain" \
    --mailto kamilisxakof@gmail.com \
    --no-supplementary
done
```

Extraction:

```bash
for domain in benzimidazole cocrystals complexes nanozymes magnetic cytotoxicity seltox synergy; do
  python -m datacon_agent.cli batch \
    --domain "$domain" \
    --pdf-dir "runs/hf-full-bench/pdfs_$domain" \
    --out "runs/hf-full-bench/outputs/${domain}_gpt41_text_noreview.csv" \
    --pages-per-window 5 \
    --no-images \
    --no-review
done
```

Evaluation artifacts:

```text
runs/hf-full-bench/outputs/*_articles.txt
runs/hf-full-bench/outputs/*_gpt41_text_noreview.csv
runs/hf-full-bench/outputs/*_metrics_gpt41_text_noreview.csv
```

## Вывод

Этот прогон покрывает оба направления ChemX на downloaded PDF subset и
подтверждает, что даже стабильный text/no-review режим бьет published baseline
на 5 доменах. Но это все еще не финальный leaderboard full-domain score:
главное ограничение сейчас не LLM extraction, а PDF acquisition. Следующий
приоритет для полного benchmark coverage — расширить downloader beyond OpenAlex
и добавить resume/skip для проблемных PDF источников.
