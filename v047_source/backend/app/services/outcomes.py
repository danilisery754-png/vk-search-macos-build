from app.core.enums import AttemptState, FinalOutcome


def calculate_outcome(message_state: AttemptState, suggested_state: AttemptState) -> FinalOutcome:
    states = {message_state, suggested_state}
    if AttemptState.SENT in states:
        return FinalOutcome.SUCCESS
    if states == {AttemptState.FAILED_FINAL}:
        return FinalOutcome.FAILED
    return FinalOutcome.PENDING

