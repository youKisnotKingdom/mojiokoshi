from app.services import worker


def test_cleanup_due_runs_immediately_then_after_interval(monkeypatch):
    monkeypatch.setattr(worker.time, "monotonic", lambda: 100.0)

    assert worker._cleanup_due(None, 3600) is True
    assert worker._cleanup_due(50.0, 60) is False
    assert worker._cleanup_due(39.0, 60) is True
    assert worker._cleanup_due(None, 0) is False
