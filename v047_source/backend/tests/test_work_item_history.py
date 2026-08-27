from sqlalchemy import create_engine
from sqlalchemy.orm import Session

from app.core.enums import AttemptState, FinalOutcome, WorkItemState
from app.db.base import Base
from app.db.models import Account, Community, EventLog, Result, Run, SendAttempt, WorkItem
from app.services.worklist import WorkListService


class NoAccounts:
    pass


def test_work_item_history_contains_both_directions_and_technical_events(tmp_path):
    engine = create_engine(f"sqlite+pysqlite:///{tmp_path / 'history.sqlite3'}")
    Base.metadata.create_all(engine)
    with Session(engine) as session:
        account = Account(vk_user_id=101, note="Основной", auth_status="ok")
        community = Community(vk_id=501, name="Тестовая группа", canonical_url="https://vk.com/test")
        run = Run(state="completed")
        session.add_all([account, community, run])
        session.flush()
        item = WorkItem(
            run_id=run.id,
            community_id=community.id,
            assigned_account_id=account.id,
            state=WorkItemState.SUCCESS,
            attempts_count=1,
        )
        session.add(item)
        session.flush()
        session.add_all([
            Result(
                work_item_id=item.id,
                account_id=account.id,
                message_state=AttemptState.SENT,
                suggested_state=AttemptState.FAILED_FINAL,
                outcome=FinalOutcome.SUCCESS,
                destination="ЛС",
            ),
            SendAttempt(
                work_item_id=item.id,
                direction="message",
                idempotency_key="message-1",
                state=AttemptState.SENT,
                vk_object_id=777,
            ),
            EventLog(
                work_item_id=item.id,
                account_id=account.id,
                user_message="Сообщение отправлено",
                technical_json='{"method":"messages.send"}',
            ),
        ])
        session.commit()
        item_id = item.id

    history = WorkListService(engine, NoAccounts()).history(item_id)

    assert history["group_name"] == "Тестовая группа"
    assert history["result"]["destination"] == "ЛС"
    assert history["attempts"][0]["direction"] == "message"
    assert history["events"][0]["technical"]["method"] == "messages.send"
