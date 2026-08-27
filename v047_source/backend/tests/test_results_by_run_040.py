from datetime import datetime

from sqlalchemy import create_engine
from sqlalchemy.orm import Session

from app.core.enums import AttemptState, FinalOutcome, WorkItemState
from app.db.base import Base
from app.db.models import Account, Community, Result, Run, WorkItem
from app.services.results import ResultsService


def seed_results(tmp_path):
    engine = create_engine(f"sqlite+pysqlite:///{tmp_path / 'results-runs.sqlite3'}")
    Base.metadata.create_all(engine)
    with Session(engine) as session:
        account = Account(vk_user_id=1, first_name="Иван", note="Основной")
        old = Run(state="completed", original_count=1)
        new = Run(state="completed", original_count=1)
        session.add_all([account, old, new])
        session.flush()
        c1 = Community(vk_id=101, name="Старая", canonical_url="https://vk.com/old")
        c2 = Community(vk_id=102, name="Новая", canonical_url="https://vk.com/new")
        session.add_all([c1, c2])
        session.flush()
        i1 = WorkItem(run_id=old.id, community_id=c1.id, assigned_account_id=account.id, state=WorkItemState.SUCCESS)
        i2 = WorkItem(run_id=new.id, community_id=c2.id, assigned_account_id=account.id, state=WorkItemState.SUCCESS)
        session.add_all([i1, i2])
        session.flush()
        session.add_all([
            Result(work_item_id=i1.id, account_id=account.id, message_state=AttemptState.SENT, outcome=FinalOutcome.SUCCESS, destination="ЛС", completed_at=datetime.now()),
            Result(work_item_id=i2.id, account_id=account.id, message_state=AttemptState.SENT, outcome=FinalOutcome.SUCCESS, destination="ЛС", completed_at=datetime.now()),
        ])
        session.commit()
        return engine, old.id, new.id


def test_result_listing_isolated_by_run(tmp_path):
    engine, old_id, new_id = seed_results(tmp_path)
    service = ResultsService(engine)

    old_rows = service.list(FinalOutcome.SUCCESS, run_id=old_id)
    new_rows = service.list(FinalOutcome.SUCCESS, run_id=new_id)

    assert {row["run_id"] for row in old_rows["items"]} == {old_id}
    assert {row["url"] for row in old_rows["items"]} == {"https://vk.com/old"}
    assert {row["run_id"] for row in new_rows["items"]} == {new_id}
    assert {row["url"] for row in new_rows["items"]} == {"https://vk.com/new"}


def test_omitted_run_defaults_to_newest_and_export_respects_run(tmp_path):
    engine, old_id, new_id = seed_results(tmp_path)
    service = ResultsService(engine)

    default_rows = service.list(FinalOutcome.SUCCESS)
    old_export = service.export_rows(FinalOutcome.SUCCESS, run_id=old_id)

    assert {row["run_id"] for row in default_rows["items"]} == {new_id}
    assert [row.url for row in old_export] == ["https://vk.com/old"]
