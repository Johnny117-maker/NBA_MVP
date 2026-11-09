"""Retentativas com espera progressiva e registro do estado das fontes (sem rede real)."""

from __future__ import annotations

import json
import logging

import pytest
import requests

from src.http_retry import TransientHTTPError, backoff_delays, retry_with_backoff
from src.live_providers import FeedClient, ProviderError
from src.source_health import read_source_health, record_source_result


class FakeResponse:
    def __init__(self, status_code: int = 200, payload: object | None = None):
        self.status_code = status_code
        self.ok = status_code < 400
        self._payload = {"ok": True} if payload is None else payload
        self.content = json.dumps(self._payload).encode()

    def json(self):
        return self._payload


def _sequence(monkeypatch, outcomes):
    calls = []

    def fake_get(url, **kwargs):
        calls.append(url)
        outcome = outcomes[min(len(calls), len(outcomes)) - 1]
        if isinstance(outcome, BaseException):
            raise outcome
        return outcome

    monkeypatch.setattr("src.live_providers.requests.get", fake_get)
    return calls


def test_backoff_delays_double_and_respect_the_limit():
    assert backoff_delays(4, 0.5, 8.0) == [0.5, 1.0, 2.0]
    assert backoff_delays(6, 2.0, 5.0) == [2.0, 4.0, 5.0, 5.0, 5.0]
    assert backoff_delays(1, 1.0, 8.0) == []


def test_transient_failures_are_retried_with_growing_waits_and_logged(caplog):
    waits, attempts = [], []

    def operation():
        attempts.append(1)
        if len(attempts) < 3:
            raise requests.ConnectionError("rede caiu")
        return "ok"

    with caplog.at_level(logging.WARNING, logger="src.http_retry"):
        assert retry_with_backoff(operation, attempts=3, base_delay=1.0, sleep=waits.append) == "ok"
    assert waits == [1.0, 2.0]
    assert sum("nova tentativa" in record.getMessage() for record in caplog.records) == 2


def test_last_failure_is_raised_and_permanent_errors_are_not_retried():
    waits = []

    def always_down():
        raise requests.Timeout("lento")

    with pytest.raises(requests.Timeout):
        retry_with_backoff(always_down, attempts=3, sleep=waits.append)
    assert len(waits) == 2
    waits.clear()
    calls = []

    def permanent():
        calls.append(1)
        raise ValueError("corpo inválido")

    with pytest.raises(ValueError, match="corpo"):
        retry_with_backoff(permanent, attempts=3, sleep=waits.append)
    assert calls == [1] and waits == []
    with pytest.raises(ValueError, match="attempts"):
        retry_with_backoff(permanent, attempts=0)


def test_feed_client_recovers_from_a_503_and_records_the_source_as_healthy(tmp_path, monkeypatch):
    calls = _sequence(monkeypatch, [FakeResponse(503), FakeResponse(200, {"games": []})])
    client = FeedClient(tmp_path / "nba.db")
    assert client.get("ESPN", "https://exemplo.invalid/placar") == {"games": []}
    assert len(calls) == 2
    health = read_source_health(tmp_path / "nba.db")
    assert "last_ok" in health["ESPN"] and "last_error" not in health["ESPN"]


def test_feed_client_does_not_retry_a_404_and_reports_the_error(tmp_path, monkeypatch):
    calls = _sequence(monkeypatch, [FakeResponse(404)])
    client = FeedClient(tmp_path / "nba.db")
    with pytest.raises(ProviderError, match="HTTP 404"):
        client.get("ESPN", "https://exemplo.invalid/placar")
    assert len(calls) == 1
    entry = read_source_health(tmp_path / "nba.db")["ESPN"]
    assert "HTTP 404" in entry["last_error_type"] and "last_ok" not in entry


def test_feed_client_gives_up_after_repeated_503_with_the_usual_http_error(tmp_path, monkeypatch):
    calls = _sequence(monkeypatch, [FakeResponse(503)])
    client = FeedClient(tmp_path / "nba.db")
    with pytest.raises(ProviderError, match="HTTP 503"):
        client.get("NBA", "https://exemplo.invalid/placar")
    assert len(calls) == 2


def test_feed_client_network_failure_becomes_provider_error_after_retry(tmp_path, monkeypatch):
    calls = _sequence(monkeypatch, [requests.ConnectionError("sem rede")])
    client = FeedClient(tmp_path / "nba.db")
    with pytest.raises(ProviderError, match="indisponível"):
        client.get("NBA", "https://exemplo.invalid/placar")
    assert len(calls) == 2
    assert read_source_health(tmp_path / "nba.db")["NBA"]["last_error_type"] == "ConnectionError"


def test_source_health_keeps_the_last_ok_and_the_last_error_and_never_raises(tmp_path, caplog):
    db = tmp_path / "nba.db"
    record_source_result(db, "ESPN")
    record_source_result(db, "ESPN", "Timeout")
    entry = read_source_health(db)["ESPN"]
    assert set(entry) == {"last_ok", "last_error", "last_error_type"}
    blocked = tmp_path / "arquivo.txt"
    blocked.write_text("não é uma pasta", encoding="utf-8")
    with caplog.at_level(logging.WARNING, logger="src.source_health"):
        record_source_result(blocked / "nba.db", "ESPN")  # caminho impossível: só registra em log
    assert read_source_health(blocked / "nba.db") == {}


def test_transient_error_keeps_the_response_for_callers_that_run_out_of_attempts():
    response = FakeResponse(429)
    error = TransientHTTPError(response)  # type: ignore[arg-type]
    assert error.reply is response and "429" in str(error)
