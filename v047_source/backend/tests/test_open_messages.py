import asyncio

import pytest
from sqlalchemy import create_engine
from sqlalchemy.orm import Session

from app.core.secrets import DPAPIProtector
from app.db.base import Base
from app.db.models import Account, AccountSecret
from app.services.accounts import AccountService


class FakeMessagesBrowser:
    def __init__(self):
        self.paths = []
        self.release = asyncio.Event()

    async def open_messages(self, profile_path):
        self.paths.append(profile_path)
        await self.release.wait()


@pytest.mark.asyncio
async def test_open_messages_uses_saved_profile_and_is_single_flight(tmp_path):
    engine = create_engine(f"sqlite+pysqlite:///{tmp_path / 'accounts.sqlite3'}")
    Base.metadata.create_all(engine)
    profile = tmp_path / "profiles" / "account-1"
    protector = DPAPIProtector(tmp_path / "secret.key")
    with Session(engine) as session:
        session.add(Account(id=1, vk_user_id=123, auth_status="ok"))
        session.add(AccountSecret(
            account_id=1,
            encrypted_token=protector.protect("token"),
            token_fingerprint="fingerprint",
            browser_profile=str(profile),
        ))
        session.commit()
    browser = FakeMessagesBrowser()
    service = AccountService(engine, tmp_path / "profiles", tmp_path / "secret.key", messages_browser=browser)

    first = service.start_open_messages(1)
    await asyncio.sleep(0)
    with pytest.raises(ValueError, match="уже открыто"):
        service.start_open_messages(1)
    with pytest.raises(ValueError, match="закройте окно"):
        service.delete_account(1)

    assert first.state in {"opening", "opened"}
    assert browser.paths == [profile]
    browser.release.set()
    await asyncio.sleep(0)
    await asyncio.sleep(0)
    assert service.browser_status(first.id)["state"] == "closed"
