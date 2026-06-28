from app.main import normalize_model_config
from app.services import jobs
from app.services.jobs import records_from_full_pipeline, records_from_llm, summarize_job


def test_model_config_keeps_api_key_private_in_summary() -> None:
    model_config = normalize_model_config(
        router_url="https://api.example.test/v1",
        api_key="sk-secret",
        model="model-a",
    )
    job = {
        "id": "job-1",
        "filename": "paper.pdf",
        "file_size": 123,
        "domain": {"name": "Benzimidazoles"},
        "source_type": "pdf",
        "saved_path": None,
        "status": "queued",
        "progress": 0,
        "stage_index": 0,
        "stage": {},
        "created_at": 1.0,
        "updated_at": 1.0,
        "logs": [],
        "source_summary": {},
        "model_config": model_config,
        "preview_rows": [],
        "records": [],
        "metrics": None,
        "artifacts": {},
    }

    public = summarize_job(job)

    assert public["model_config"]["router_url"] == "https://api.example.test/v1"
    assert public["model_config"]["api_key_configured"] is True
    assert "api_key" not in public["model_config"]


def test_limited_pdf_for_full_pipeline_caps_pages_before_scraper(tmp_path, monkeypatch) -> None:
    import sys
    import types

    pdf_path = tmp_path / "paper.pdf"
    pdf_path.write_bytes(b"%PDF-1.4\n")

    class FakeReader:
        def __init__(self, path) -> None:
            self.path = path
            self.pages = ["page-1", "page-2", "page-3"]

    class FakeWriter:
        def __init__(self) -> None:
            self.pages = []

        def add_page(self, page) -> None:
            self.pages.append(page)

        def write(self, handle) -> None:
            handle.write(f"pages={len(self.pages)}".encode())

    monkeypatch.setitem(sys.modules, "pypdf", types.SimpleNamespace(PdfReader=FakeReader, PdfWriter=FakeWriter))

    limited = jobs.limited_pdf_for_full_pipeline(pdf_path, tmp_path / "run" / "full_pipeline", 1)

    assert limited != pdf_path
    assert limited.name == "paper-first-1.pdf"
    assert limited.read_bytes() == b"pages=1"
    assert jobs.limited_pdf_for_full_pipeline(pdf_path, tmp_path / "run2", None) == pdf_path


def test_full_pipeline_domain_mapping_covers_web_domains() -> None:
    from datacon_agent.domains import DOMAINS

    web_domain_names = {domain["name"] for domain in jobs.CHEMX_DOMAINS}

    assert web_domain_names <= set(jobs.FULL_PIPELINE_DOMAIN_KEYS)
    for domain_key in jobs.FULL_PIPELINE_DOMAIN_KEYS.values():
        assert domain_key in DOMAINS


def test_metrics_payload_uses_completed_jobs_not_projected_scores(monkeypatch) -> None:
    domain = next(item for item in jobs.CHEMX_DOMAINS if item["name"] == "Benzimidazoles")
    monkeypatch.setattr(
        jobs,
        "JOBS",
        {
            "done-1": {
                "id": "done-1",
                "status": "completed",
                "domain": domain,
                "updated_at": 20,
                "records": [{"object_id": "mol-1"}, {"object_id": "mol-2"}],
                "metrics": {
                    "macro_f1": 0.612,
                    "record_count": 2,
                },
            },
            "running-1": {
                "id": "running-1",
                "status": "running",
                "domain": domain,
                "updated_at": 30,
                "records": [{"object_id": "mol-3"}],
                "metrics": {
                    "macro_f1": 0.999,
                    "record_count": 1,
                },
            },
        },
    )

    payload = jobs.metrics_payload()
    benzimidazoles = next(item for item in payload["domains"] if item["name"] == "Benzimidazoles")
    eyedrops = next(item for item in payload["domains"] if item["name"] == "EyeDrops")

    assert payload["summary"]["completed_runs"] == 1
    assert payload["summary"]["tracked_domains"] == 1
    assert payload["summary"]["total_rows"] == 2
    assert payload["summary"]["avg_current"] == 0.612
    assert benzimidazoles["current"] == 0.612
    assert benzimidazoles["projected"] == 0.612
    assert benzimidazoles["record_count"] == 2
    assert benzimidazoles["job_id"] == "done-1"
    assert eyedrops["current"] is None
    assert eyedrops["projected"] is None
    assert eyedrops["status"] == "no completed runs"


def test_records_from_llm_uses_submitted_router_config(monkeypatch) -> None:
    captured = {}

    class FakeClient:
        def __init__(self, config) -> None:
            captured["config"] = config

        def complete(self, *, system: str, user: str):
            captured["system"] = system
            captured["user"] = user
            return {
                "parsed_json": {
                    "records": [
                        {
                            "object_id": "mol-1",
                            "primary_value": "CCO",
                            "property": "MIC 1 ug/mL",
                            "evidence": "table 1",
                            "confidence": 0.91,
                        }
                    ]
                },
                "parse_error": None,
                "usage": {"total_tokens": 42},
            }

    monkeypatch.setattr(jobs, "ChatCompletionsClient", FakeClient)
    job = {
        "filename": "paper.txt",
        "domain": {"name": "Benzimidazoles", "description": "MIC extraction"},
        "source_summary": {"text_tokens": 8},
        "source_text": "Compound CCO had MIC 1 ug/mL in table 1.",
        "table_rows": [],
        "model_config": normalize_model_config(
            router_url="https://router.example/v1",
            api_key="sk-secret",
            model="model-a",
        ),
    }

    records, result = records_from_llm(job)

    assert captured["config"].base_url == "https://router.example/v1"
    assert captured["config"].api_key == "sk-secret"
    assert captured["config"].model == "model-a"
    assert records == [
        {
            "object_id": "mol-1",
            "primary_value": "CCO",
            "property": "MIC 1 ug/mL",
            "evidence": "table 1",
            "confidence": "0.91",
        }
    ]
    assert result["status"] == "completed"
    assert result["usage"] == {"total_tokens": 42}


def test_full_pipeline_enables_table_column_agents(monkeypatch, tmp_path) -> None:
    captured = {}

    class FakeSettings:
        def __init__(self, **kwargs) -> None:
            self.__dict__.update(kwargs)

    class FakeScraperPipelineConfig:
        def __init__(self, **kwargs) -> None:
            self.__dict__.update(kwargs)
            captured["scraper_config"] = self

    class FakeAgent:
        def __init__(self, domain, *, settings, api_key, base_url) -> None:
            captured["domain"] = domain
            captured["settings"] = settings
            captured["api_key"] = api_key
            captured["base_url"] = base_url

        def extract_document(self, document):
            captured["document"] = document
            return [
                {
                    "compound_id": "1",
                    "smiles": "CCO",
                    "target_type": "MIC",
                    "target_value": "1",
                    "target_units": "ug/mL",
                    "bacteria": "S. aureus",
                    "_evidence": "Table 1",
                }
            ]

    class FakeDomain:
        key = "benzimidazole"
        columns = ["compound_id", "smiles", "target_type", "target_value", "target_units", "bacteria"]

    def fake_scrape_run_dir(pdf_path, scraper_dir):
        return tmp_path / "scrapes" / "paper"

    def fake_scrape_pdf_to_document(pdf_path, *, render_pages, dpi, config):
        captured["pdf_path"] = pdf_path
        captured["render_pages"] = render_pages
        captured["dpi"] = dpi
        captured["config"] = config
        return object()

    monkeypatch.setattr(
        jobs,
        "_full_pipeline_dependencies",
        lambda: {
            "AgentSettings": FakeSettings,
            "ChemExtractionAgent": FakeAgent,
            "ScraperPipelineConfig": FakeScraperPipelineConfig,
            "get_datacon_domain": lambda key: FakeDomain(),
            "scrape_pdf_to_document": fake_scrape_pdf_to_document,
            "scrape_run_dir": fake_scrape_run_dir,
        },
    )
    monkeypatch.setattr(
        jobs,
        "evidence_agent_counts",
        lambda sqlite_path: {
            "agent_table_measurements": 2,
            "agent_compound_links": 2,
            "agent_conflict_decisions": 1,
            "agent_scaffold_resolutions": 1,
        },
    )

    pdf_path = tmp_path / "paper.pdf"
    pdf_path.write_bytes(b"%PDF-1.4\n")
    job = {
        "id": "job-full",
        "filename": "paper.pdf",
        "saved_path": str(pdf_path),
        "source_type": "pdf",
        "run_dir": str(tmp_path / "run"),
        "domain": {"name": "Benzimidazoles"},
        "model_config": normalize_model_config(
            router_url="https://router.example/v1",
            api_key="sk-secret",
            model="model-a",
            review_model="model-b",
            pages_per_window=3,
            send_images=True,
            review_pass=True,
        ),
    }

    records, result = records_from_full_pipeline(job)
    scraper_config = captured["scraper_config"]

    assert scraper_config.run_visual is True
    assert scraper_config.visual_provider == "heuristic"
    assert scraper_config.run_evidence_agents is True
    assert scraper_config.run_table_agent is True
    assert scraper_config.run_linking_agent is True
    assert scraper_config.run_conflict_resolver is True
    assert scraper_config.run_scaffold_resolver is True
    assert captured["api_key"] == "sk-secret"
    assert captured["settings"].model == "model-a"
    assert captured["settings"].review_model == "model-b"
    assert records[0]["primary_value"] == "CCO"
    assert result["mode"] == "full_scraper_evidence_llm_pipeline"
    assert result["evidence_agents"][0]["agent_counts"]["agent_table_measurements"] == 2
