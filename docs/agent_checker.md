# Single-agent checker

Этот слой проверяет минимальный MVP-контур:

```text
PDF -> scraper -> structured SQLite evidence -> single checker agent -> report artifacts
```

Он не заменяет финальный LLM extractor. Задача checker-а: понять, достаточно ли
структурированных данных из `scrape.sqlite`, какой ChemX prompt-skill лучше
подходит к статье, какие поля уже имеют evidence, и какие фрагменты стоит
передать первому LLM-агенту.

## Prompt skills

Локальные skill templates лежат в:

```text
app/services/agent/skills/chemx_prompts/
```

Они импортированы из ChemX:

```text
https://github.com/ai-chem/ChemX/tree/main/LLM/data/prompts
```

Маппинг доменов:

- `Benzimidazoles` -> `benzimidazole.py`
- `Oxazolidinones` -> `oxazolidinone.py`
- `Co-crystals` -> `cocrystals.py`
- `Complexes` -> `complexes.py`
- `Nanozymes` -> `nanozymes.py`
- `Synergy` -> `synergy.py`
- `Nanomag` -> `magnetic.py`
- `Cytotox` -> `cytotoxicity.py`
- `SelTox` -> `seltox.py`

В upstream-папке ChemX prompt templates нет отдельного prompt-а для `EyeDrops`.
Старый checker поэтому запускает sniffing по всем доступным skills и добавляет
warning в отчёт. Основной `datacon_agent` поддерживает `eyedrops` отдельно
через schema-driven домен с колонками `smiles`, `name`, `perm (cm/s)`, `logP`.

## Запуск от PDF

```bash
python -m app.services.agent pdf-dataset/antibiotics-12-01220-v2.pdf \
  --out runs/agent-antibiotics \
  --domain Benzimidazoles \
  --doc-id antibiotics_1220
```

Агент сначала создаст:

```text
runs/agent-antibiotics/scrape/scrape.sqlite
```

Потом запишет:

```text
runs/agent-antibiotics/agent_check/agent_report.json
runs/agent-antibiotics/agent_check/agent_report.md
runs/agent-antibiotics/agent_check/candidate_evidence.jsonl
```

## Подключение VseGPT API

VseGPT поддерживает OpenAI-compatible `chat/completions` API:

```text
https://api.vsegpt.ru/v1/chat/completions
```

В коде используется base URL:

```text
https://api.vsegpt.ru/v1
```

Создайте локальный `.env` рядом с `.env.example`:

```bash
cp .env.example .env
```

И впишите ключ:

```text
VSEGPT_API_KEY=sk-...
VSEGPT_BASE_URL=https://api.vsegpt.ru/v1
VSEGPT_MODEL=openai/gpt-4o-mini
```

Настоящий `.env` игнорируется git-ом.

Запуск checker-а с LLM extraction:

```bash
python -m app.services.agent runs/agent-antibiotics/scrape/scrape.sqlite \
  --out runs/agent-antibiotics/agent_check \
  --domain Benzimidazoles \
  --run-llm
```

Можно выбрать другую модель из VseGPT Docs/Models:

```bash
python -m app.services.agent runs/agent-antibiotics/scrape/scrape.sqlite \
  --out runs/agent-antibiotics/agent_check \
  --domain Benzimidazoles \
  --run-llm \
  --llm-model openai/gpt-5.4-mini
```

LLM-артефакты:

```text
runs/agent-antibiotics/agent_check/llm_result.json
runs/agent-antibiotics/agent_check/llm_raw.txt
```

`llm_result.json` содержит распарсенный JSON, raw-ответ модели, usage и
публичную конфигурацию провайдера без полного API-ключа.

## Запуск от готового scraper run

```bash
python -m app.services.agent runs/scrape-antibiotics \
  --domain Benzimidazoles
```

или напрямую:

```bash
python -m app.services.agent runs/scrape-antibiotics/scrape.sqlite \
  --out runs/scrape-antibiotics/agent_check \
  --domain Benzimidazoles
```

## Как читать результат

- `pipeline_checks` показывает, прошёл ли PDF через scraper и есть ли таблицы,
  captions, visual tasks и OCSR SMILES.
- `skill_checks[].field_checks` показывает, какие поля из prompt-а имеют
  evidence-кандидаты.
- `candidate_evidence.jsonl` содержит ranked snippets, которые можно передавать
  в первый LLM extraction pass вместе с соответствующим prompt-skill.
- Статус `needs_visual_or_ocsr` означает, что текст/таблицы найдены, но prompt
  требует SMILES, а OCSR evidence ещё не создан.
