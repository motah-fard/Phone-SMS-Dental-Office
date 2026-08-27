"""integrations/telnyx_client.py -- no real network calls, requests.post
is mocked throughout."""
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


def test_send_sms_network_failure_raises_telnyx_error(monkeypatch):
    monkeypatch.setattr(tc, "TELNYX_API_KEY", "fake_key")
    monkeypatch.setattr(tc, "TELNYX_PHONE_NUMBER", "+15559990000")

    with patch.object(tc.requests, "post", side_effect=requests.ConnectionError("network down")):
        with pytest.raises(tc.TelnyxError):
            tc.send_sms("+15551230001", "hi there")


def test_send_sms_non_2xx_response_raises_telnyx_error(monkeypatch):
    monkeypatch.setattr(tc, "TELNYX_API_KEY", "fake_key")
    monkeypatch.setattr(tc, "TELNYX_PHONE_NUMBER", "+15559990000")

    def raise_http_error():
        raise requests.HTTPError("400 Bad Request")

    fake_response = SimpleNamespace(raise_for_status=raise_http_error)
    with patch.object(tc.requests, "post", return_value=fake_response):
        with pytest.raises(tc.TelnyxError):
            tc.send_sms("+15551230001", "hi there")
