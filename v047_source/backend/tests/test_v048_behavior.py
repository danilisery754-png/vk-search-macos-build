from __future__ import annotations

from datetime import datetime

from sqlalchemy import create_engine
from sqlalchemy.orm import Session

from app.core.enums import AttemptState, FinalOutcome
from app.db.base import Base
from app.db.models import Account, Community, Dialog, Result, Run, WorkItem
from app.services.accounts import AccountService
from app.services.dashboard import DashboardService
from app.services.logs import EventLogService
from app.services.processor import WorkProcessor
from app.vk.client import VkActionResult, VkApiClient


def make_engine(tmp_path, name: str):
    engine = create_engine(
        f"sqlite+pysqlite:///{tmp_path / name}",
        connect_args={"check_same_thread": False},
    )
    Base.metadata.create_all(engine)
    return engine


def seed_unread_dialogs(engine):
    with Session(engine) as session:
        account = Account(
            vk_user_id=101,
            first_name="Иван",
            last_name="Иванов",
            enabled=True,
            auth_status="ok",
            unread_count=80,
        )
        session.add(account)
        session.flush()
        session.add_all(
            [
                Dialog(account_id=account.id, peer_id=-1, title="Один", unread_count=30),
                Dialog(account_id=account.id, peer_id=-2, title="Два", unread_count=50),
                Dialog(account_id=account.id, peer_id=-3, title="Три", unread_count=0),
            ]
        )
        session.commit()
        return account.id


def test_dashboard_unread_counts_dialogs_not_messages(tmp_path):
    engine = make_engine(tmp_path, "dashboard-v048.sqlite3")
    seed_unread_dialogs(engine)
    snapshot = DashboardService(engine).snapshot()
    assert snapshot["metrics"]["unread"] == 2


def test_account_unread_count_counts_unread_dialogs(tmp_path):
    engine = make_engine(tmp_path, "accounts-v048.sqlite3")
    account_id = seed_unread_dialogs(engine)
    profiles = tmp_path / "profiles"
    profiles.mkdir()
    service = AccountService(engine, profiles, tmp_path / "development-secret.key")
    rows = service.list_accounts()
    row = next(item for item in rows if item["id"] == account_id)
    assert row["unread_count"] == 2


def test_health_classifier_distinguishes_alive_blocked_deactivated_auth_and_temporary():
    alive = VkActionResult(AttemptState.SENT, object_id=1, raw={"id": 1})
    blocked = VkActionResult(AttemptState.FAILED_FINAL, error_class="account_banned", reason="Аккаунт заблокирован VK.")
    deactivated = VkActionResult(AttemptState.FAILED_FINAL, error_class="account_deactivated", reason="Аккаунт деактивирован VK.")
    auth = VkActionResult(AttemptState.AUTH_REQUIRED, error_class="authorization", reason="Нужен вход")
    temporary = VkActionResult(AttemptState.TEMPORARY_ERROR, error_class="network", reason="Сеть")
    assert AccountService.classify_health_result(alive)[0] == "alive"
    assert AccountService.classify_health_result(blocked)[0] == "blocked"
    assert AccountService.classify_health_result(deactivated)[0] == "deactivated"
    assert AccountService.classify_health_result(auth)[0] == "requires_login"
    assert AccountService.classify_health_result(temporary)[0] == "unknown"


class IdentityClient(VkApiClient):
    def __init__(self, response):
        self.response = response

    async def _call(self, method: str, **params):
        assert method == "users.get"
        return self.response, None


async def test_validate_identity_marks_explicit_vk_deactivation_without_guessing():
    banned = await IdentityClient([{"id": 10, "deactivated": "banned"}]).validate_identity()
    deleted = await IdentityClient([{"id": 11, "deactivated": "deleted"}]).validate_identity()
    alive = await IdentityClient([{"id": 12, "first_name": "A"}]).validate_identity()
    assert banned.state is AttemptState.FAILED_FINAL
    assert banned.error_class == "account_banned"
    assert deleted.state is AttemptState.FAILED_FINAL
    assert deleted.error_class == "account_deactivated"
    assert alive.state is AttemptState.SENT


def test_account_health_fields_are_persisted(tmp_path):
    engine = make_engine(tmp_path, "health-fields-v048.sqlite3")
    checked = datetime.utcnow()
    with Session(engine) as session:
        account = Account(vk_user_id=999, first_name="Health", enabled=True, auth_status="ok", health_status="alive", health_checked_at=checked, health_detail="Проверено VK API")
        session.add(account)
        session.commit()
        account_id = account.id
    with Session(engine) as session:
        row = session.get(Account, account_id)
        assert row.health_status == "alive"
        assert row.health_checked_at == checked
        assert row.health_detail == "Проверено VK API"


def seed_outreach_log_case(engine):
    with Session(engine) as session:
        account = Account(vk_user_id=500, first_name="Иван", last_name="Старов", note="Новая заметка", enabled=True, auth_status="ok")
        community = Community(vk_id=700, name="Группа", canonical_url="https://vk.com/club700")
        run = Run(state="running", original_count=1)
        session.add_all([account, community, run])
        session.flush()
        item = WorkItem(run_id=run.id, community_id=community.id, assigned_account_id=account.id, account_note_snapshot="Старая заметка")
        session.add(item)
        session.flush()
        session.add(Result(work_item_id=item.id, account_id=account.id))
        session.commit()
        return account.id, item.id


def test_new_outreach_log_prefers_current_account_note_over_snapshot(tmp_path):
    engine = make_engine(tmp_path, "log-current-note-v048.sqlite3")
    account_id, item_id = seed_outreach_log_case(engine)
    logs = EventLogService(engine)
    processor = WorkProcessor(engine, None, None, None, logs=logs)
    processor._log_outreach(item_id, account_id, FinalOutcome.SUCCESS, "ЛС")
    row = logs.list(category="outreach")[0]
    assert row["technical"]["account_name"] == "Новая заметка"


def test_historical_log_exposes_current_account_display_name(tmp_path):
    engine = make_engine(tmp_path, "log-enrichment-v048.sqlite3")
    account_id, _item_id = seed_outreach_log_case(engine)
    logs = EventLogService(engine)
    logs.add("Старая заметка написал", account_id=account_id, category="outreach", technical={"account_name": "Старая заметка"})
    row = logs.list(category="outreach")[0]
    assert row["account_display_name"] == "Новая заметка"
