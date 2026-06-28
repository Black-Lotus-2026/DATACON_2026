# ChemX domain sweep

Дата проверки: 2026-06-28.

## Вывод

По ТЗ DataCon26 в ChemX есть 10 датасетов. В `datacon_agent` теперь
зарегистрированы все 10 доменов, включая `eyedrops`.

`EyeDrops` отличается от остальных датасетов:

- в локальном `ChemX/datasets/EyeDrops.csv` нет колонки `pdf`;
- все 163 строки имеют `access=0`;
- автоматический `download-pdfs --domain eyedrops` поэтому не скачивает PDF;
- evaluator синтезирует article id из `PMID`, затем `doi`, затем `title`.

## Open-access покрытие в локальных ChemX CSV

| Домен | Строк | `access=1` строк | Уникальных PDF | Open-access PDF |
| --- | ---: | ---: | ---: | ---: |
| Benzimidazoles | 1721 | 456 | 34 | 9 |
| Oxazolidinones | 2923 | 215 | 23 | 2 |
| Co-crystals | 70 | 27 | 33 | 13 |
| Complexes | 907 | 214 | 22 | 4 |
| Nanozymes | 1135 | 111 | 395 | 39 |
| Nanomag | 2578 | 704 | 386 | 120 |
| Cytotox | 5476 | 1990 | 169 | 58 |
| SelTox | 3244 | 2512 | 163 | 135 |
| Synergy | 3232 | 2158 | 87 | 53 |
| EyeDrops | 163 | 0 | 0 | 0 |

## Smoke-download по первым 2 статьям домена

Команда:

```bash
for domain in benzimidazole oxazolidinone cocrystals complexes nanozymes magnetic cytotoxicity seltox synergy eyedrops; do
  python -m datacon_agent.cli download-pdfs \
    --domain "$domain" \
    --out-dir "runs/chemx-all-domains/pdfs_$domain" \
    --limit 2 \
    --mailto kamilisxakof@gmail.com \
    --no-supplementary
done
```

Результат:

| Домен | Manifest rows | PDF files | Downloaded | Not found |
| --- | ---: | ---: | ---: | ---: |
| benzimidazole | 2 | 0 | 0 | 2 |
| oxazolidinone | 2 | 0 | 0 | 2 |
| cocrystals | 2 | 1 | 1 | 1 |
| complexes | 2 | 0 | 0 | 2 |
| nanozymes | 2 | 0 | 0 | 2 |
| magnetic | 2 | 0 | 0 | 2 |
| cytotoxicity | 2 | 0 | 0 | 2 |
| seltox | 2 | 0 | 0 | 2 |
| synergy | 2 | 1 | 1 | 1 |
| eyedrops | 0 | 0 | 0 | 0 |

Этот smoke не означает, что домены недоступны. Он показывает, что стратегия
`первые N open-access DOI -> OpenAlex pdf_url` слишком слабая для доменного
прогона. Следующий приоритет для баллов: улучшить downloader/fallback, чтобы
выбирать реально скачиваемые статьи, а не первые строки датасета.

## OpenRouter

Для запуска через OpenRouter в `.env` нужны:

```text
OPENAI_API_KEY=...
OPENAI_BASE_URL=https://openrouter.ai/api/v1
OPENROUTER_MODEL=provider/model-slug
```

Если VPN работает системным туннелем, отдельный proxy не нужен. Если нужен
локальный proxy, добавьте:

```text
HTTPS_PROXY=socks5h://127.0.0.1:<port>
HTTP_PROXY=socks5h://127.0.0.1:<port>
```

Без точного `OPENROUTER_MODEL` LLM batch не запускался, чтобы не тратить лимиты
на ошибочный model id.
