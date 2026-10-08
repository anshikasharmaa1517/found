"""Domain errors. Each maps to one HTTP status and error code."""


class FoundError(Exception):
    code = "INTERNAL"
    http_status = 500

    def __init__(self, message: str = "", **details: object) -> None:
        super().__init__(message)
        self.message = message
        self.details = details


class BadRequest(FoundError):
    code = "BAD_REQUEST"
    http_status = 400


class Unauthenticated(FoundError):
    code = "UNAUTHENTICATED"
    http_status = 401


class ValidationFailed(FoundError):
    code = "VALIDATION_FAILED"
    http_status = 422


class Forbidden(FoundError):
    code = "FORBIDDEN"
    http_status = 403


class NotFound(FoundError):
    code = "NOT_FOUND"
    http_status = 404


class ReferenceConflict(FoundError):
    code = "REFERENCE_CONFLICT"
    http_status = 409


class VersionConflict(FoundError):
    code = "VERSION_CONFLICT"
    http_status = 409


class InProgress(FoundError):
    code = "IN_PROGRESS"
    http_status = 409


class BudgetLimit(FoundError):
    code = "BUDGET_LIMIT"
    http_status = 429


class ServiceUnavailable(FoundError):
    code = "DEPENDENCY_UNAVAILABLE"
    http_status = 503
