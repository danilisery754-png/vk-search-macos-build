from datetime import datetime, timedelta

import pytest
from sqlalchemy import create_engine, select
from sqlalchemy.orm import Session

from app.core.enums import AttemptState, FinalOutcome, WorkItemState
from app.db.base import Base
from app.db.models import Account, Community, Dialog, Result, Run, WorkItem
from app.services.runs import RunService
from app.services.settings import SettingsService


def seed_history(tmp_path):
    engine = create_engine(f"sqlite+pysqlite:///{tmp_path / 'run-history.sqlite3'}")
    Base.metadata.create_all(engine)
    now = datetime.now()
    with Session(engine) as session:
        account = Account(vk_user_id=101, first_name="Иван", auth_status="ok")
        dialog = Dialog(account_id=1, peer_id=-900, title="Диалог")
        old = Run(state="completed", started_at=now - timedelta(hours=2), finished_at=now - timedelta(hours=1), original_count=2)
        current = Run(state="completed", started_at=now - timedelta(minutes=30), finished_at=now, original_count=1)
        session.add(account)
        session.flush()
        dialog.account_id = account.id
        session.add_all([dialog, old, current])
        session.flush()
        communities = [
            Community(vk_id=501, name="A", canonical_url="https://vk.com/a"),
            Community(vk_id=502, name="B", canonical_url="https://vk.com/b"),
            Community(vk_id=503, name="C", canonical_url="https://vk.com/c"),
        ]
        session.add_all(communities)
        session.flush()
        items = [
            WorkItem(run_id=old.id, community_id=communities[0].id, state=WorkItemState.SUCCESS, assigned_account_id=account.id),
            WorkItem(run_id=old.id, community_id=communities[1].id, state=WorkItemState.FAILED, assigned_account_id=account.id),
            WorkItem(run_id=current.id, community_id=communities[2].id, state=WorkItemState.SUCCESS, assigned_account_id=account.id),
        ]
        session.add_all(items)
        session.flush()
        session.add_all([
            Result(work_item_id=items[0].id, account_id=account.id, outcome=FinalOutcome.SUCCESS, message_state=AttemptState.SENT, completed_at=now - timedelta(hours=1)),
            Result(work_item_id=items[1].id, account_id=account.id, outcome=FinalOutcome.FAILED, message_state=AttemptState.FAILED_FINAL, completed_at=now - timedelta(hours=1)),
            Result(work_item_id=items[2].id, account_id=account.id, outcome=FinalOutcome.SUCCESS, message_state=AttemptState.SENT, completed_at=now),
        ])
        session.commit()
        return engine, account.id, dialog.id, old.id, current.id


def test_list_history_returns_newest_first_aggregated_summaries(tmp_path):
    engine, _, _, old_id, current_id = seed_history(tmp_path)
    service = RunService(engine, SettingsService(engine))

    history = service.list_history()

    assert history["current_run_id"] == current_id
    assert [item["id"] for item in history["items"]] == [current_id, old_id]
    current = history["items"][0]
    assert current["state"] == "completed"
    assert current["original_count"] == 1
    assert current["processed_count"] == 1
    assert current["success_count"] == 1
    assert current["failure_count"] == 0
    assert current["started_at"] is not None
    assert current["finished_at"] is not None
    old = history["items"][1]
    assert old["processed_count"] == 2
    assert old["success_count"] == 1
    assert old["failure_count"] == 1


def test_delete_history_removes_only_selected_old_run(tmp_path):
    engine, account_id, dialog_id, old_id, current_id = seed_history(tmp_path)
    service = RunService(engine, SettingsService(engine))

    assert service.delete_history(old_id) is True

    with Session(engine) as session:
        assert session.get(Run, old_id) is None
        assert session.get(Run, current_id) is not None
        assert session.get(Account, account_id) is not None
        assert session.get(Dialog, dialog_id) is not None
        assert session.scalar(select(WorkItem).where(WorkItem.run_id == old_id)) is None

    with pytest.raises(ValueError, match="Нельзя удалить текущий запуск"):
        service.delete_history(current_id)
    assert service.delete_history(999999) is False
