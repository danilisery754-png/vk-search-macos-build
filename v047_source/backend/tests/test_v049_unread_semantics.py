from __future__ import annotations

from sqlalchemy import create_engine
from sqlalchemy.orm import Session

from app.db.base import Base
from app.db.models import Account, Dialog, DialogFolder, DialogFolderMember
from app.services.accounts_v049 import AccountService
from app.services.inbox_v049_runtime import InboxService


def make_accounts(tmp_path, engine):
    profiles = tmp_path / "profiles"
    profiles.mkdir(exist_ok=True)
    return AccountService(engine, profiles, tmp_path / "secret.key")


def test_account_unread_count_counts_only_non_archived_unread_dialogs(tmp_path):
    engine = create_engine(
        f"sqlite+pysqlite:///{tmp_path / 'unread-account.sqlite3'}",
        connect_args={"check_same_thread": False},
    )
    Base.metadata.create_all(engine)
    with Session(engine) as session:
        account = Account(vk_user_id=101, first_name="Иван", enabled=True, auth_status="ok")
        session.add(account)
        session.flush()
        account_id = account.id
        session.add_all([
            Dialog(account_id=account.id, peer_id=201, title="A", unread_count=4, is_archived=False),
            Dialog(account_id=account.id, peer_id=202, title="B", unread_count=2, is_archived=False),
            Dialog(account_id=account.id, peer_id=203, title="Архив", unread_count=9, is_archived=True),
        ])
        session.commit()

    accounts = make_accounts(tmp_path, engine)
    service = InboxService(engine, accounts)

    # Preserve the v0.4.8 semantic: this is a count of dialogs with unread
    # messages, not a sum of unread messages. Archive must not contribute.
    with Session(engine) as session:
        assert service._account_unread_dialogs(session, account_id) == 2

    public = accounts.list_accounts()
    assert len(public) == 1
    assert public[0]["unread_count"] == 2


def test_folder_count_hides_archived_dialog_but_membership_survives_for_restore(tmp_path):
    engine = create_engine(
        f"sqlite+pysqlite:///{tmp_path / 'folder-archive.sqlite3'}",
        connect_args={"check_same_thread": False},
    )
    Base.metadata.create_all(engine)
    with Session(engine) as session:
        account = Account(vk_user_id=101, first_name="Иван", enabled=True, auth_status="ok")
        session.add(account)
        session.flush()
        folder = DialogFolder(account_id=account.id, name="Рабочие")
        normal = Dialog(account_id=account.id, peer_id=201, title="Обычный", is_archived=False)
        archived = Dialog(account_id=account.id, peer_id=202, title="Архивный", is_archived=True)
        session.add_all([folder, normal, archived])
        session.flush()
        session.add_all([
            DialogFolderMember(folder_id=folder.id, dialog_id=normal.id),
            DialogFolderMember(folder_id=folder.id, dialog_id=archived.id),
        ])
        session.commit()
        folder_id = folder.id
        archived_id = archived.id

    service = InboxService(engine, make_accounts(tmp_path, engine))
    folders = service.list_folders()
    assert folders == [{"id": folder_id, "account_id": 1, "name": "Рабочие", "dialogs_count": 1}]

    with Session(engine) as session:
        membership = session.query(DialogFolderMember).filter_by(
            folder_id=folder_id,
            dialog_id=archived_id,
        ).one_or_none()
        assert membership is not None
