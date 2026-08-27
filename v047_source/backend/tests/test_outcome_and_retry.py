from app.core.enums import AttemptState, FinalOutcome
from app.services.outcomes import calculate_outcome
from app.services.retry import RetryPolicy


def test_partial_and_full_success_are_successful():
    assert calculate_outcome(AttemptState.FAILED_FINAL, AttemptState.SENT) is FinalOutcome.SUCCESS
    assert calculate_outcome(AttemptState.SENT, AttemptState.FAILED_FINAL) is FinalOutcome.SUCCESS
    assert calculate_outcome(AttemptState.SENT, AttemptState.SENT) is FinalOutcome.SUCCESS


def test_two_confirmed_failures_are_failed():
    assert calculate_outcome(AttemptState.FAILED_FINAL, AttemptState.FAILED_FINAL) is FinalOutcome.FAILED


def test_temporary_or_unknown_result_stays_unresolved():
    assert calculate_outcome(AttemptState.TEMPORARY_ERROR, AttemptState.FAILED_FINAL) is FinalOutcome.PENDING
    assert calculate_outcome(AttemptState.UNKNOWN, AttemptState.FAILED_FINAL) is FinalOutcome.PENDING


def test_retry_policy_is_bounded_and_monotonic_without_jitter():
    policy = RetryPolicy(max_attempts=4, base_seconds=5, max_seconds=30, jitter_ratio=0)
    assert [policy.delay_for(attempt) for attempt in range(1, 6)] == [5, 10, 20, 30, None]

