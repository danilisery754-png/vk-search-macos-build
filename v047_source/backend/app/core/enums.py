from enum import StrEnum


class AttemptState(StrEnum):
    NOT_ATTEMPTED = "not_attempted"
    SENDING = "sending"
    SENT = "sent"
    FAILED_FINAL = "failed_final"
    TEMPORARY_ERROR = "temporary_error"
    AUTH_REQUIRED = "auth_required"
    UNKNOWN = "unknown"


class FinalOutcome(StrEnum):
    PENDING = "pending"
    SUCCESS = "success"
    FAILED = "failed"


class WorkItemState(StrEnum):
    WAITING = "waiting"
    ASSIGNED = "assigned"
    PROCESSING = "processing"
    RETRY_WAIT = "retry_wait"
    RECONCILE_REQUIRED = "reconcile_required"
    PAUSED = "paused"
    SUCCESS = "success"
    FAILED = "failed"

