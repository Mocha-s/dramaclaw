"""Shared service-boundary exception types.

These were previously defined in ``newapi_provisioner``; moved here so the
gateway route layer does not need to import the provisioner module just for
the exception type.
"""

from __future__ import annotations


class ServiceControlEgressDenied(PermissionError):
    """Stable denial for an invalid NewAPI management service boundary."""

    code = "ORG_SERVICE_EGRESS_DENIED"

    def __init__(self) -> None:
        super().__init__(
            "ORG_SERVICE_EGRESS_DENIED: model gateway management is only available in CE"
        )


class ServiceOperationNotReplayable(RuntimeError):
    """Raised when a durable service operation was already claimed."""


class ServiceInvocationFailed(RuntimeError):
    """Secret-free failure after a claimed service invocation."""

    def __init__(self) -> None:
        super().__init__("service operation failed")
