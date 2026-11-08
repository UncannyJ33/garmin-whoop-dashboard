"""OpenAPI documents readiness/today's 204 alongside its 200 model."""

from __future__ import annotations

from src.api.main import app


def test_readiness_today_documents_204_and_200_model() -> None:
    responses = app.openapi()["paths"]["/api/readiness/today"]["get"]["responses"]
    assert "204" in responses
    assert "200" in responses
    schema = responses["200"]["content"]["application/json"]["schema"]
    assert "ReadinessResponse" in schema.get("$ref", "")
