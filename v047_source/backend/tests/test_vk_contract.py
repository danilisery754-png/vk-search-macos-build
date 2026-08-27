from __future__ import annotations

import json

import httpx
import pytest

from app.core.enums import AttemptState
from app.vk.client import VkApiClient, stable_random_id
from app.vk.errors import classify_vk_error, redact_secrets


def test_stable_random_id_is_non_zero_and_deterministic():
    assert stable_random_id("run:1:item:2:message") == stable_random_id("run:1:item:2:message")
    assert stable_random_id("run:1:item:2:message") != 0


@pytest.mark.asyncio
async def test_messages_send_uses_negative_community_peer_and_random_id():
    captured = {}

    def handler(request: httpx.Request):
        captured["path"] = request.url.path
        captured["form"] = dict(httpx.QueryParams(request.content.decode()))
        return httpx.Response(200, json={"response": 456})

    transport = httpx.MockTransport(handler)
    async with httpx.AsyncClient(transport=transport) as http:
        client = VkApiClient("secret-token", http=http)
        result = await client.send_community_message(123, "Привет", "attempt-key")

    assert captured["path"].endswith("/method/messages.send")
    assert captured["form"]["peer_id"] == "-123"
    assert captured["form"]["message"] == "Привет"
    assert int(captured["form"]["random_id"]) != 0
    assert captured["form"]["v"] == "5.199"
    assert result.state is AttemptState.SENT
    assert result.object_id == 456


@pytest.mark.asyncio
async def test_wall_post_contract_for_suggested_post_attempt():
    captured = {}

    def handler(request: httpx.Request):
        captured.update(dict(httpx.QueryParams(request.content.decode())))
        return httpx.Response(200, json={"response": {"post_id": 77}})

    async with httpx.AsyncClient(transport=httpx.MockTransport(handler)) as http:
        result = await VkApiClient("token", http=http).send_suggested_post(321, "Текст")

    assert captured["owner_id"] == "-321"
    assert captured["message"] == "Текст"
    assert result.state is AttemptState.SENT
    assert result.object_id == 77


@pytest.mark.asyncio
async def test_messages_mark_as_read_contract():
    captured = {}

    def handler(request: httpx.Request):
        captured["path"] = request.url.path
        captured["form"] = dict(httpx.QueryParams(request.content.decode()))
        return httpx.Response(200, json={"response": 1})

    async with httpx.AsyncClient(transport=httpx.MockTransport(handler)) as http:
        result = await VkApiClient("token", http=http).mark_as_read(-321)

    assert captured["path"].endswith("/method/messages.markAsRead")
    assert captured["form"]["peer_id"] == "-321"
    assert result.state is AttemptState.SENT


@pytest.mark.asyncio
async def test_vk_error_is_normalized_without_leaking_token():
    payload = {"error": {"error_code": 901, "error_msg": "denied token=super-secret"}}

    async with httpx.AsyncClient(transport=httpx.MockTransport(lambda _: httpx.Response(200, json=payload))) as http:
        result = await VkApiClient("super-secret", http=http).send_community_message(1, "x", "key")

    assert result.state is AttemptState.FAILED_FINAL
    assert "super-secret" not in result.reason


@pytest.mark.parametrize(
    ("code", "expected"),
    [
        (5, AttemptState.AUTH_REQUIRED),
        (6, AttemptState.TEMPORARY_ERROR),
        (9, AttemptState.TEMPORARY_ERROR),
        (10, AttemptState.TEMPORARY_ERROR),
        (15, AttemptState.FAILED_FINAL),
        (900, AttemptState.FAILED_FINAL),
        (901, AttemptState.FAILED_FINAL),
        (902, AttemptState.FAILED_FINAL),
        (99999, AttemptState.UNKNOWN),
    ],
)
def test_error_classifier_is_conservative(code, expected):
    assert classify_vk_error(code).state is expected


def test_secret_redaction_handles_urls_json_and_plain_text():
    source = json.dumps({"access_token": "abc", "url": "https://x/?access_token=def", "text": "token=ghi"})
    cleaned = redact_secrets(source, extra_values=["ghi"])
    assert "abc" not in cleaned and "def" not in cleaned and "ghi" not in cleaned
    assert "[СКРЫТО]" in cleaned
