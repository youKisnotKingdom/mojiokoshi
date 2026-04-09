"""Tests for health check endpoints."""


class TestHealth:
    def test_health_check(self, client):
        response = client.get("/health")
        assert response.status_code == 200
        assert response.json()["status"] == "healthy"

    def test_index_page_renders(self, client):
        response = client.get("/")
        assert response.status_code == 200
