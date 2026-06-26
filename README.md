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

Для production-качества ChemX можно заменить функции `records_from_text`, `records_from_rows` и `build_metrics` на LLM/RAG/fine-tuned pipeline, сохранив тот же контракт API для фронтенда.
