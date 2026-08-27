from __future__ import annotations

from datetime import datetime
from typing import Callable

from sqlalchemy import Engine, select
from sqlalchemy.orm import Session

from app.core.enums import AttemptState, FinalOutcome, WorkItemState
from app.db.models import Account, Community, Result, SendAttempt, WorkItem
from app.services.message_variants import select_variant
from app.services.outcomes import calculate_outcome
from app.services.queue import ClaimedWorkItem, QueueRepository
from app.services.retry import RetryPolicy
from app.vk.client import VkActionResult, VkApiClient, stable_random_id


class WorkProcessor:
    def __init__(
        self,
        engine: Engine,
        queue: QueueRepository,
        accounts,
        settings,
        *,
        client_factory: Callable[[str], VkApiClient] = VkApiClient,
        logs=None,
    ):
        self.engine = engine
        self.queue = queue
        self.accounts = accounts
        self.settings = settings
        self.client_factory = client_factory
        self.logs = logs

    async def process_next(self, account_id: int, owner: str) -> bool:
        config = self.settings.all()
        daily_limit = int(config.get("max_groups_per_account", 50))
        claimed = self.queue.claim_next(account_id, owner, daily_limit=daily_limit)
        if claimed is None:
            return False
        with Session(self.engine) as session:
            item = session.get(WorkItem, claimed.id)
            community = session.get(Community, claimed.community_id)
            community_vk_id = community.vk_id
            result = session.scalar(select(Result).where(Result.work_item_id == claimed.id))
            if result is None:
                result = Result(work_item_id=claimed.id, account_id=account_id)
                session.add(result)
                session.commit()
                session.refresh(result)
            message_state = result.message_state
            suggested_state = result.suggested_state

        outreach_text = select_variant(config["message_texts"], work_item_id=claimed.id)
        # A successful direction completes this community.  Never send the same
        # outreach to both LS and suggested posts just because both are available.
        if suggested_state is AttemptState.SENT:
            self._set_final_result(claimed.id, FinalOutcome.SUCCESS, "Предложка")
            self.queue.finalize(claimed.id, WorkItemState.SUCCESS)
            self._increment_account(account_id, success=True)
            self._log_outreach(claimed.id, account_id, FinalOutcome.SUCCESS, "Предложка")
            return True

        if message_state not in {AttemptState.SENT, AttemptState.FAILED_FINAL}:
            attempt = self._begin_attempt(claimed, "message")
            message_result = await self._run_vk(
                account_id,
                lambda client: client.send_community_message(
                    community_vk_id,
                    outreach_text,
                    attempt.idempotency_key,
                ),
            )
            self._finish_attempt(attempt.id, message_result)
            self._save_direction(claimed.id, "message", message_result)
            message_state = message_result.state

        if message_state is AttemptState.SENT:
            self._set_final_result(claimed.id, FinalOutcome.SUCCESS, "ЛС")
            self.queue.finalize(claimed.id, WorkItemState.SUCCESS)
            self._increment_account(account_id, success=True)
            self._log_outreach(claimed.id, account_id, FinalOutcome.SUCCESS, "ЛС")
            return True

        # Only a definite final LS denial proves it is safe and useful to try
        # the second route. Temporary/ambiguous/auth failures are handled below
        # without risking a duplicate message.
        if message_state is AttemptState.FAILED_FINAL and suggested_state not in {AttemptState.SENT, AttemptState.FAILED_FINAL}:
            attempt = self._begin_attempt(claimed, "suggested")
            suggested_result = await self._run_vk(
                account_id,
                lambda client: client.send_suggested_post(
                    community_vk_id,
                    outreach_text,
                ),
            )
            self._finish_attempt(attempt.id, suggested_result)
            self._save_direction(claimed.id, "suggested", suggested_result)
            suggested_state = suggested_result.state

        outcome = calculate_outcome(message_state, suggested_state)
        if outcome is FinalOutcome.SUCCESS:
            destination = self._destination(message_state, suggested_state)
            self._set_final_result(claimed.id, outcome, destination)
            self.queue.finalize(claimed.id, WorkItemState.SUCCESS)
            self._increment_account(account_id, success=True)
            self._log_outreach(claimed.id, account_id, outcome, destination)
            return True
        if outcome is FinalOutcome.FAILED:
            self._set_final_result(claimed.id, outcome, "")
            self.queue.finalize(claimed.id, WorkItemState.FAILED)
            self._increment_account(account_id, success=False)
            self._log_outreach(claimed.id, account_id, outcome, "")
            return True

        states = self._attempt_results(claimed.id)
        if any(item.state is AttemptState.AUTH_REQUIRED for item in states):
            self._require_login(account_id, claimed.id)
            return True
        if any(item.error_class in {"network", "network_ambiguous", "invalid_response"} for item in states):
            self.queue.mark_reconcile(
                claimed.id,
                "Ответ VK мог потеряться после отправки. Повтор заблокирован до безопасной сверки.",
            )
            return True

        policy = RetryPolicy(max_attempts=int(config["retry_max_attempts"]))
        delay = policy.delay_for(claimed.attempts_count)
        if delay is None:
            self._finalize_exhausted(claimed.id)
            self.queue.finalize(claimed.id, WorkItemState.FAILED)
            self._increment_account(account_id, success=False)
            self._log_outreach(claimed.id, account_id, FinalOutcome.FAILED, "")
        else:
            self.queue.schedule_retry(claimed.id, delay_seconds=delay, reason="Временная ошибка VK; повтор запланирован.")
        return True


    def _finalize_exhausted(self, item_id: int) -> None:
        with Session(self.engine) as session:
            result = session.scalar(select(Result).where(Result.work_item_id == item_id))
            if result is None:
                return
            if result.message_state not in {AttemptState.SENT, AttemptState.FAILED_FINAL}:
                previous = result.message_reason.strip() or "временная ошибка VK"
                result.message_state = AttemptState.FAILED_FINAL
                result.message_reason = f"Повторы исчерпаны: {previous}"
            if result.suggested_state not in {AttemptState.SENT, AttemptState.FAILED_FINAL}:
                previous = result.suggested_reason.strip() or "временная ошибка VK"
                result.suggested_state = AttemptState.FAILED_FINAL
                result.suggested_reason = f"Повторы исчерпаны: {previous}"
            result.outcome = FinalOutcome.FAILED
            result.destination = ""
            result.completed_at = datetime.utcnow()
            session.commit()

    def _log_outreach(self, item_id: int, account_id: int, outcome: FinalOutcome, destination: str) -> None:
        if self.logs is None:
            return
        with Session(self.engine) as session:
            item = session.get(WorkItem, item_id)
            account = session.get(Account, account_id)
            community = session.get(Community, item.community_id) if item else None
            result = session.scalar(select(Result).where(Result.work_item_id == item_id))
            if not item or not account or not community or not result:
                return
            account_name = account.display_name
            technical = {
                "account_name": account_name,
                "account_avatar_url": account.avatar_url,
                "community_name": community.name or community.canonical_url,
                "community_url": community.canonical_url,
                "community_avatar_url": community.avatar_url,
                "message_state": result.message_state.value,
                "message_reason": result.message_reason,
                "suggested_state": result.suggested_state.value,
                "suggested_reason": result.suggested_reason,
                "outcome": outcome.value,
                "destination": destination,
            }
        verb = "написал" if outcome is FinalOutcome.SUCCESS else "не удалось написать"
        self.logs.add(
            f"{technical['account_name']} {verb}: {technical['community_url']}",
            level="info" if outcome is FinalOutcome.SUCCESS else "warning",
            category="outreach",
            event_type="outreach_result",
            account_id=account_id,
            work_item_id=item_id,
            technical=technical,
        )

    async def _run_vk(self, account_id: int, operation):
        runner = getattr(self.accounts, "run_vk", None)
        if callable(runner):
            return await runner(account_id, operation, client_factory=self.client_factory)
        # Compatibility for lightweight test doubles and older integrations.
        token = self.accounts.get_token(account_id)
        client = self.client_factory(token)
        try:
            return await operation(client)
        finally:
            token = ""
            await client.aclose()

    def _begin_attempt(self, claimed: ClaimedWorkItem, direction: str) -> SendAttempt:
        key = f"run:{claimed.run_id}:item:{claimed.id}:{direction}:attempt:{claimed.attempts_count}"
        with Session(self.engine) as session:
            existing = session.scalar(select(SendAttempt).where(SendAttempt.idempotency_key == key))
            if existing:
                return existing
            attempt = SendAttempt(
                work_item_id=claimed.id,
                direction=direction,
                idempotency_key=key,
                random_id=stable_random_id(key) if direction == "message" else None,
                state=AttemptState.SENDING,
            )
            session.add(attempt)
            session.commit()
            session.refresh(attempt)
            session.expunge(attempt)
            return attempt

    def _finish_attempt(self, attempt_id: int, result: VkActionResult) -> None:
        with Session(self.engine) as session:
            attempt = session.get(SendAttempt, attempt_id)
            attempt.state = result.state
            attempt.vk_object_id = result.object_id
            attempt.error_code = result.error_code
            attempt.error_class = result.error_class
            attempt.reason = result.reason
            session.commit()

    def _save_direction(self, item_id: int, direction: str, value: VkActionResult) -> None:
        with Session(self.engine) as session:
            result = session.scalar(select(Result).where(Result.work_item_id == item_id))
            if direction == "message":
                result.message_state = value.state
                result.message_reason = value.reason
            else:
                result.suggested_state = value.state
                result.suggested_reason = value.reason
            session.commit()

    def _set_final_result(self, item_id: int, outcome: FinalOutcome, destination: str) -> None:
        with Session(self.engine) as session:
            result = session.scalar(select(Result).where(Result.work_item_id == item_id))
            result.outcome = outcome
            result.destination = destination
            result.completed_at = datetime.utcnow()
            session.commit()

    def _attempt_results(self, item_id: int) -> list[SendAttempt]:
        with Session(self.engine) as session:
            return list(
                session.scalars(
                    select(SendAttempt).where(SendAttempt.work_item_id == item_id).order_by(SendAttempt.id.desc())
                ).all()
            )

    def _require_login(self, account_id: int, item_id: int) -> None:
        with Session(self.engine) as session:
            account = session.get(Account, account_id)
            account.auth_status = "requires_login"
            account.work_status = "requires_login"
            session.commit()
        self.queue.mark_paused(item_id, "Требуется повторный вход в VK")

    def _increment_account(self, account_id: int, *, success: bool) -> None:
        with Session(self.engine) as session:
            account = session.get(Account, account_id)
            account.processed_count += 1
            if success:
                account.success_count += 1
            else:
                account.failed_count += 1
            account.last_action_at = datetime.utcnow()
            session.commit()

    @staticmethod
    def _destination(message: AttemptState, suggested: AttemptState) -> str:
        if message is AttemptState.SENT and suggested is AttemptState.SENT:
            return "ЛС + Предложка"
        if message is AttemptState.SENT:
            return "ЛС"
        return "Предложка"
