from pathlib import Path

from datacon_agent.agent import AgentSettings, ChemExtractionAgent
from datacon_agent.domains import get_domain
from datacon_agent.pdf import DocumentContext, PageContext


def test_review_context_can_be_disabled() -> None:
    agent = ChemExtractionAgent(
        get_domain("nanozymes"),
        settings=AgentSettings(review_context_chars=0),
        client=object(),
    )
    document = DocumentContext(Path("paper.pdf"), [PageContext(1, "article text")])

    assert agent.review_context(document) == ""


def test_review_context_is_truncated() -> None:
    agent = ChemExtractionAgent(
        get_domain("nanozymes"),
        settings=AgentSettings(review_context_chars=20),
        client=object(),
    )
    document = DocumentContext(Path("paper.pdf"), [PageContext(1, "line one\nline two\nline three")])

    context = agent.review_context(document)

    assert "Article text and tables:" in context
    assert "[article context truncated]" in context
