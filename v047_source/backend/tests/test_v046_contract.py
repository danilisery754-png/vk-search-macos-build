from __future__ import annotations

import json

import httpx
import pytest
from fastapi.testclient import TestClient
from sqlalchemy.orm import Session

from app.core.config import AppConfig
from app.db.models import Account, Community, Dialog, Message, Run, WorkItem
from app.core.enums import WorkItemState
from app.main import create_app
from app.vk.client import VkApiClient


def make_app(tmp_path):
    return create_app(AppConfig(data_dir=tmp_path, frontend_dir=tmp_path / "frontend"))


def seed_account(session: Session, vk_user_id: int = 101, note: str = "мой") -> Account:
    account = Account(
        vk_user_id=vk_user_id,
        first_name="Иван",
        last_name="Иванов",
        profile_url=f"https://vk.com/id{vk_user_id}",
        note=note,
        enabled=True,
        auth_status="ok",
        work_status="stopped",
    )
    session.add(account)
    session.flush()
    return account


def test_start_resumes_legacy_needs_attention_when_waiting_work_exists(tmp_path):
    app = make_app(tmp_path)
    with TestClient(app):
        with Session(app.state.services.engine) as session:
            seed_account(session)
            run = Run(state="needs_attention", original_count=1)
            community = Community(vk_id=500, screen_name="club500", name="Test", canonical_url="https://vk.com/club500")
            session.add_all([run, community])
            session.flush()
            session.add(WorkItem(run_id=run.id, community_id=community.id, state=WorkItemState.WAITING))
            session.commit()
            run_id = run.id
        result = app.state.services.runs.start()
        assert result["state"] == "running"
        assert result["run_id"] == run_id


def test_quick_replies_have_no_defaults_and_support_crud(tmp_path):
    app = make_app(tmp_path)
    with TestClient(app) as client:
        assert client.get("/api/quick-replies").json() == []
        created = client.post("/api/quick-replies", json={"text": "Здравствуйте, какая цена?"})
        assert created.status_code == 201
        item = created.json()
        assert item["text"] == "Здравствуйте, какая цена?"
        assert item["id"]
        listed = client.get("/api/quick-replies").json()
        assert [row["id"] for row in listed] == [item["id"]]
        edited = client.patch(f"/api/quick-replies/{item['id']}", json={"text": "Можно статистику?"})
        assert edited.status_code == 200
        assert edited.json()["text"] == "Можно статистику?"
        deleted = client.delete(f"/api/quick-replies/{item['id']}")
        assert deleted.status_code == 200
        assert client.get("/api/quick-replies").json() == []


def test_dialog_pin_is_local_to_account_and_pinned_rows_sort_first(tmp_path):
    app = make_app(tmp_path)
    with TestClient(app) as client:
        with Session(app.state.services.engine) as session:
            a1 = seed_account(session, 101, "A")
            a2 = seed_account(session, 202, "B")
            d1 = Dialog(account_id=a1.id, peer_id=-500, title="Same peer A", unread_count=0)
            d2 = Dialog(account_id=a1.id, peer_id=-600, title="Other A", unread_count=0)
            d3 = Dialog(account_id=a2.id, peer_id=-500, title="Same peer B", unread_count=0)
            session.add_all([d1, d2, d3])
            session.commit()
            ids = d1.id, d2.id, d3.id
            account_ids = a1.id, a2.id
        patched = client.patch(f"/api/inbox/dialogs/{ids[1]}", json={"is_pinned": True})
        assert patched.status_code == 200
        rows_a = client.get(f"/api/inbox/dialogs?account_id={account_ids[0]}").json()
        assert [row["id"] for row in rows_a[:2]] == [ids[1], ids[0]]
        assert rows_a[0]["is_pinned"] is True
        rows_b = client.get(f"/api/inbox/dialogs?account_id={account_ids[1]}").json()
        assert rows_b[0]["id"] == ids[2]
        assert rows_b[0]["is_pinned"] is False
        assert not hasattr(Dialog, "is_archived")


def test_message_payload_exposes_attachments_reply_and_forwards(tmp_path):
    app = make_app(tmp_path)
    with TestClient(app):
        with Session(app.state.services.engine) as session:
            account = seed_account(session)
            dialog = Dialog(account_id=account.id, peer_id=-500, title="Test", unread_count=0)
            session.add(dialog)
            session.flush()
            message = Message(
                account_id=account.id,
                dialog_id=dialog.id,
                vk_message_id=77,
                from_id=-500,
                outgoing=False,
                body="",
                sent_at=__import__("datetime").datetime.utcnow(),
                is_read=True,
                attachments_json=json.dumps([{"type": "sticker", "sticker": {"sticker_id": 9}}]),
            )
            session.add(message)
            session.commit()
            dialog_id = dialog.id
        payload = app.state.services.inbox.list_messages(dialog_id)
        row = payload["messages"][0]
        assert row["attachments"][0]["type"] == "sticker"
        assert "reply_message" in row
        assert "forwarded_messages" in row


@pytest.mark.asyncio
async def test_vk_send_message_supports_real_reply_and_forward_fields():
    captured = {}

    async def handler(request: httpx.Request):
        captured.update(dict(httpx.QueryParams(request.content.decode())))
        return httpx.Response(200, json={"response": 123})

    async with httpx.AsyncClient(transport=httpx.MockTransport(handler)) as http:
        client = VkApiClient("token", http=http)
        result = await client.send_message(
            -500,
            "reply",
            "key",
            reply_to=77,
            forward={"peer_id": -500, "conversation_message_ids": [4, 5]},
        )
    assert result.object_id == 123
    assert captured["reply_to"] == "77"
    assert json.loads(captured["forward"])["conversation_message_ids"] == [4, 5]
