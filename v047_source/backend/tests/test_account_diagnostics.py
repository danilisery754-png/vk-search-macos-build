from datetime import datetime

from sqlalchemy import create_engine
from sqlalchemy.orm import Session

from app.core.enums import WorkItemState
from app.db.base import Base
from app.db.models import Account, AccountSecret, Community, Run, WorkItem
from app.services.accounts import AccountService


def test_account_panel_contains_operational_diagnostics(tmp_path):
    engine = create_engine(f"sqlite+pysqlite:///{tmp_path / 'accounts.sqlite3'}")
    Base.metadata.create_all(engine)
    checked = datetime(2026, 8, 25, 10, 30)
    (tmp_path / "profile").mkdir()
    with Session(engine) as session:
        account = Account(
            vk_user_id=101,
            first_name="Иван",
            auth_status="ok",
            work_status="working",
            last_checked_at=checked,
        )
        community = Community(vk_id=501, canonical_url="https://vk.com/club501")
        run = Run(state="running")
        session.add_all([account, community, run])
        session.flush()
        session.add_all([
            AccountSecret(
                account_id=account.id,
                encrypted_token=b"test",
                token_fingerprint="fingerprint",
                browser_profile=str(tmp_path / "profile"),
            ),
            WorkItem(
                run_id=run.id,
                community_id=community.id,
                assigned_account_id=account.id,
                state=WorkItemState.ASSIGNED,
            ),
        ])
        session.commit()

    row = AccountService(engine, tmp_path / "profiles", tmp_path / "key").list_accounts()[0]

    assert row["api_status"] == "ok"
    assert row["session_status"] == "ok"
    assert row["assigned_groups"] == 1
    assert row["last_checked_at"] == checked.isoformat()
