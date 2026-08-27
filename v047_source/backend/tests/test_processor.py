from __future__ import annotations

from datetime import datetime, timedelta

from sqlalchemy import create_engine, select
from sqlalchemy.orm import Session

from app.core.enums import AttemptState, FinalOutcome, WorkItemState
from app.db.base import Base
from app.db.models import Account, Community, Result, Run, WorkItem
from app.services.processor import WorkProcessor
from app.services.queue import QueueRepository
from app.vk.client import VkActionResult


class FakeAccounts:
    def get_token(self, account_id):
        return "token"


class FakeSettings:
    def __init__(self, retry=4):
        self.retry = retry

    def all(self):
        return {
            "message_text": "СТАРАЯ СТРОКА ЛС",
            "suggested_post_text": "СТАРАЯ СТРОКА ПРЕДЛОЖКИ",
            "message_texts": ["ЛС один", "ЛС два", "ЛС три"],
            "suggested_post_texts": ["Пост один", "Пост два", "Пост три"],
            "retry_max_attempts": self.retry,
        }


class FakeClient:
    def __init__(self, message_result, suggested_result):
        self.message_result = message_result
        self.suggested_result = suggested_result
        self.message_texts = []
        self.suggested_texts = []

    async def send_community_message(self, community_id, text, key):
        self.message_texts.append(text)
        return self.message_result

    async def send_suggested_post(self, community_id, text):
        self.suggested_texts.append(text)
        return self.suggested_result

    async def aclose(self):
        pass


def seed(tmp_path):
    engine = create_engine(
        f"sqlite+pysqlite:///{tmp_path / 'processor.sqlite3'}",
        connect_args={"check_same_thread": False},
    )
    Base.metadata.create_all(engine)
    with Session(engine) as session:
        account = Account(vk_user_id=1, first_name="Сергей", enabled=True, auth_status="ok")
        community = Community(vk_id=2, canonical_url="https://vk.com/club2")
        run = Run(state="running")
        session.add_all([account, community, run])
        session.flush()
        item = WorkItem(
            run_id=run.id,
            community_id=community.id,
            assigned_account_id=account.id,
            state=WorkItemState.ASSIGNED,
        )
        session.add(item)
        session.commit()
        return engine, account.id, item.id


async def test_partial_success_is_final_success(tmp_path):
    engine, account_id, item_id = seed(tmp_path)
    fake = FakeClient(
        VkActionResult(AttemptState.FAILED_FINAL, error_code=901, reason="ЛС закрыты"),
        VkActionResult(AttemptState.SENT, object_id=77),
    )
    processor = WorkProcessor(
        engine,
        QueueRepository(engine),
        FakeAccounts(),
        FakeSettings(),
        client_factory=lambda _: fake,
    )

    assert await processor.process_next(account_id, "worker") is True

    with Session(engine) as session:
        item = session.get(WorkItem, item_id)
        result = session.scalar(select(Result).where(Result.work_item_id == item_id))
        assert item.state is WorkItemState.SUCCESS
        assert result.outcome is FinalOutcome.SUCCESS
        assert result.destination == "Предложка"


async def test_known_rate_limit_is_scheduled_for_bounded_retry(tmp_path):
    engine, account_id, item_id = seed(tmp_path)
    temporary = VkActionResult(AttemptState.TEMPORARY_ERROR, error_code=6, error_class="rate_limit")
    processor = WorkProcessor(
        engine,
        QueueRepository(engine),
        FakeAccounts(),
        FakeSettings(),
        client_factory=lambda _: FakeClient(temporary, temporary),
    )

    await processor.process_next(account_id, "worker")
    with Session(engine) as session:
        item = session.get(WorkItem, item_id)
        assert item.state is WorkItemState.RETRY_WAIT
        assert item.next_retry_at is not None


async def test_ambiguous_network_result_requires_reconciliation(tmp_path):
    engine, account_id, item_id = seed(tmp_path)
    ambiguous = VkActionResult(AttemptState.TEMPORARY_ERROR, error_class="network", reason="обрыв")
    processor = WorkProcessor(
        engine,
        QueueRepository(engine),
        FakeAccounts(),
        FakeSettings(),
        client_factory=lambda _: FakeClient(ambiguous, ambiguous),
    )

    await processor.process_next(account_id, "worker")
    with Session(engine) as session:
        assert session.get(WorkItem, item_id).state is WorkItemState.RECONCILE_REQUIRED


async def test_retry_reuses_the_same_variant_for_each_direction(tmp_path):
    engine, account_id, item_id = seed(tmp_path)
    temporary = VkActionResult(AttemptState.TEMPORARY_ERROR, error_code=6, error_class="rate_limit")
    fake = FakeClient(temporary, temporary)
    processor = WorkProcessor(
        engine,
        QueueRepository(engine),
        FakeAccounts(),
        FakeSettings(),
        client_factory=lambda _: fake,
    )

    await processor.process_next(account_id, "worker-one")
    with Session(engine) as session:
        item = session.get(WorkItem, item_id)
        item.next_retry_at = datetime.utcnow() - timedelta(seconds=1)
        session.commit()
    await processor.process_next(account_id, "worker-two")

    assert len(fake.message_texts) == 2
    assert len(fake.suggested_texts) == 2
    assert fake.message_texts[0] == fake.message_texts[1]
    assert fake.suggested_texts[0] == fake.suggested_texts[1]
    assert fake.message_texts[0] == fake.suggested_texts[0]
    assert fake.message_texts[0] in {"ЛС один", "ЛС два", "ЛС три"}
