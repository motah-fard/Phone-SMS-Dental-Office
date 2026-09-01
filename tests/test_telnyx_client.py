"""integrations/telnyx_client.py -- no real network calls, requests.post
is mocked throughout. time.sleep is patched away in retry tests so they
run instantly instead of actually waiting out the backoff."""
from types import SimpleNamespace
from unittest.mock import patch

import pytest
import requests

import telnyx_client as tc


def test_send_sms_without_credentials_raises_telnyx_error(monkeypatch):
    monkeypatch.setattr(tc, "TELNYX_API_KEY", None)
    monkeypatch.setattr(tc, "TELNYX_PHONE_NUMBER", None)
    with pytest.raises(tc.TelnyxError):
        tc.send_sms("+15551230001", "hello")


def test_send_sms_success_returns_parsed_json(monkeypatch):
    monkeypatch.setattr(tc, "TELNYX_API_KEY", "fake_key")
    monkeypatch.setattr(tc, "TELNYX_PHONE_NUMBER", "+15559990000")

    fake_response = SimpleNamespace(
        status_code=200,
        raise_for_status=lambda: None,
        json=lambda: {"data": {"id": "msg_123"}},
    )
    with patch.object(tc.requests, "post", return_value=fake_response) as mock_post:
        result = tc.send_sms("+15551230001", "hi there")

    assert result == {"data": {"id": "msg_123"}}
    call_kwargs = mock_post.call_args.kwargs
    assert call_kwargs["json"]["to"] == "+15551230001"
    assert call_kwargs["json"]["text"] == "hi there"
    assert call_kwargs["headers"]["Authorization"] == "Bearer fake_key"


def test_send_sms_network_failure_exhausts_retries_then_raises(monkeypatch):
    monkeypatch.setattr(tc, "TELNYX_API_KEY", "fake_key")
    monkeypatch.setattr(tc, "TELNYX_PHONE_NUMBER", "+15559990000")
    monkeypatch.setattr(tc.time, "sleep", lambda seconds: None)

    with patch.object(tc.requests, "post", side_effect=requests.ConnectionError("network down")) as mock_post:
        with pytest.raises(tc.TelnyxError):
            tc.send_sms("+15551230001", "hi there")

    assert mock_post.call_count == tc.MAX_RETRIES + 1  # retried the transient failure, then gave up


def test_send_sms_non_transient_4xx_fails_immediately_without_retry(monkeypatch):
    """A malformed request or bad auth should never be retried -- it'll
    fail identically every time, retrying just wastes time."""
    monkeypatch.setattr(tc, "TELNYX_API_KEY", "fake_key")
    monkeypatch.setattr(tc, "TELNYX_PHONE_NUMBER", "+15559990000")
    monkeypatch.setattr(tc.time, "sleep", lambda seconds: (_ for _ in ()).throw(AssertionError("should not sleep/retry on a 4xx")))

    def raise_http_error():
        raise requests.HTTPError("400 Bad Request")

    fake_response = SimpleNamespace(status_code=400, raise_for_status=raise_http_error)
    with patch.object(tc.requests, "post", return_value=fake_response) as mock_post:
        with pytest.raises(tc.TelnyxError):
            tc.send_sms("+15551230001", "hi there")

    assert mock_post.call_count == 1


def test_send_sms_transient_http_error_retries_then_succeeds(monkeypatch):
    """A 503 on the first attempt, then a real 200 -- must retry and
    return the eventual success, not give up after the first failure."""
    monkeypatch.setattr(tc, "TELNYX_API_KEY", "fake_key")
    monkeypatch.setattr(tc, "TELNYX_PHONE_NUMBER", "+15559990000")
    monkeypatch.setattr(tc.time, "sleep", lambda seconds: None)

    responses = [
        SimpleNamespace(status_code=503, raise_for_status=lambda: (_ for _ in ()).throw(requests.HTTPError("503"))),
        SimpleNamespace(status_code=200, raise_for_status=lambda: None, json=lambda: {"data": {"id": "msg_456"}}),
    ]
    with patch.object(tc.requests, "post", side_effect=responses) as mock_post:
        result = tc.send_sms("+15551230001", "hi there")

    assert result == {"data": {"id": "msg_456"}}
    assert mock_post.call_count == 2


def test_send_sms_transient_http_error_exhausts_retries_then_raises(monkeypatch):
    monkeypatch.setattr(tc, "TELNYX_API_KEY", "fake_key")
    monkeypatch.setattr(tc, "TELNYX_PHONE_NUMBER", "+15559990000")
    monkeypatch.setattr(tc.time, "sleep", lambda seconds: None)

    fake_response = SimpleNamespace(
        status_code=503, raise_for_status=lambda: (_ for _ in ()).throw(requests.HTTPError("503")),
    )
    with patch.object(tc.requests, "post", return_value=fake_response) as mock_post:
        with pytest.raises(tc.TelnyxError):
            tc.send_sms("+15551230001", "hi there")

    assert mock_post.call_count == tc.MAX_RETRIES + 1
