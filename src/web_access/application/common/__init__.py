"""Common application contracts."""

from web_access.application.common.context import ExecutionContext, PrincipalContext
from web_access.application.common.results import OperationOutcome, OperationResult

__all__ = ["ExecutionContext", "OperationOutcome", "OperationResult", "PrincipalContext"]
