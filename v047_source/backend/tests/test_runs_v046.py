from sqlalchemy import create_engine
from sqlalchemy.orm import Session
from app.db.base import Base
from app.db.models import Account, Community, Run, WorkItem
from app.core.enums import WorkItemState
from app.services.runs import RunService
from app.services.settings import SettingsService


def test_resume_can_recover_legacy_needs_attention_with_waiting_work(tmp_path):
    engine = create_engine(f"sqlite+pysqlite:///{tmp_path/'runs.sqlite3'}", connect_args={"check_same_thread":False})
    Base.metadata.create_all(engine)
    with Session(engine) as session:
        account = Account(vk_user_id=1, enabled=True, auth_status='ok')
        run = Run(state='needs_attention', original_count=1)
        community = Community(vk_id=1, canonical_url='https://vk.com/club1')
        session.add_all([account, run, community]); session.flush()
        session.add(WorkItem(run_id=run.id, community_id=community.id, state=WorkItemState.WAITING)); session.commit()
    service = RunService(engine, SettingsService(engine))
    assert service.resume()['state'] == 'running'
