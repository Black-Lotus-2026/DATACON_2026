from datacon_agent.domains import DOMAINS
from datacon_agent.schema import structured_output_schema


def test_structured_schema_contains_domain_columns() -> None:
    for domain in DOMAINS.values():
        schema = structured_output_schema(domain, include_evidence=True)
        item = schema["properties"]["samples"]["items"]
        properties = item["properties"]

        for column in domain.columns:
            assert column in properties
            assert column in item["required"]
        assert "_evidence" in properties
        assert "_page" in properties
