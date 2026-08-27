from __future__ import annotations

from sqlalchemy import create_engine, select
from sqlalchemy.orm import Session

from app.core.enums import AttemptState, FinalOutcome, WorkItemState
from app.db.base import Base
from app.db.models import Account, Community, Result, Run, WorkItem
from app.services.processor import WorkProcessor
from app.services.queue import QueueRepository
from app.vk.client import VkActionResult
from app.vk.errors import classify_vk_error


class FakeAccounts:
    def get_token(self, account_id):
        return "token"


class FakeSettings:
    def __init__(self, retry=1):
        self.retry = retry

    def all(self):
        return {
            "max_groups_per_account": 50,
            "message_texts": ["Привет"],
            "suggested_post_texts": ["Привет"],
            "retry_max_attempts": self.retry,
        }


class FakeClient:
    def __init__(self, message_result, suggested_result):
        self.message_result = message_result
        self.suggested_result = suggested_result

    async def send_community_message(self, community_id, text, key):
        return self.message_result

    async def send_suggested_post(self, community_id, text):
        return self.suggested_result

    async def aclose(self):
        pass


def seed(tmp_path):
    engine = create_engine(
        f"sqlite+pysqlite:///{tmp_path / 'processor-v046.sqlite3'}",
        connect_args={"check_same_thread": False},
    )
    Base.metadata.create_all(engine)
    with Session(engine) as session:
        account = Account(vk_user_id=1, first_name="Сергей", enabled=True, auth_status="ok")
        community = Community(vk_id=2, name="Закрытая", canonical_url="https://vk.com/club2")
        run = Run(state="running", original_count=1)
        session.add_all([account, community, run])
        session.flush()
        item = WorkItem(run_id=run.id, community_id=community.id, state=WorkItemState.WAITING)
        session.add(item)
        session.commit()
        return engine, account.id, item.id


def test_suggested_post_access_denied_is_final_not_unknown():
    value = classify_vk_error(214)
    assert value.state is AttemptState.FAILED_FINAL
    assert value.category == "suggested_post_forbidden"


async def test_unknown_vk_error_is_bounded_retry_not_manual_reconcile(tmp_path):
    engine, account_id, item_id = seed(tmp_path)
    unknown = VkActionResult(AttemptState.UNKNOWN, error_code=777, error_class="unknown", reason="VK error 777")
    processor = WorkProcessor(
        engine, QueueRepository(engine), FakeAccounts(), FakeSettings(retry=1),
        client_factory=lambda _: FakeClient(unknown, unknown),
    )
    await processor.process_next(account_id, "worker")
    with Session(engine) as session:
        item = session.get(WorkItem, item_id)
        assert item.state is WorkItemState.RETRY_WAIT


async def test_exhausted_non_ambiguous_retries_become_failed_result(tmp_path):
    engine, account_id, item_id = seed(tmp_path)
    temporary = VkActionResult(AttemptState.TEMPORARY_ERROR, error_code=6, error_class="rate_limit", reason="лимит")
    processor = WorkProcessor(
        engine, QueueRepository(engine), FakeAccounts(), FakeSettings(retry=1),
        client_factory=lambda _: FakeClient(temporary, temporary),
    )
    await processor.process_next(account_id, "worker-one")
    with Session(engine) as session:
        item = session.get(WorkItem, item_id)
        # force the second claim: attempt #2 is beyond max_attempts=1
        item.next_retry_at = __import__("datetime").datetime.utcnow()
        session.commit()
    await processor.process_next(account_id, "worker-two")
    with Session(engine) as session:
        item = session.get(WorkItem, item_id)
        result = session.scalar(select(Result).where(Result.work_item_id == item_id))
        assert item.state is WorkItemState.FAILED
        assert result.outcome is FinalOutcome.FAILED
        assert result.message_state is AttemptState.FAILED_FINAL
        assert result.suggested_state is AttemptState.FAILED_FINAL
        assert "Повторы исчерпаны" in result.message_reason
