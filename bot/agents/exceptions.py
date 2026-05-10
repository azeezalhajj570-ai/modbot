"""Domain exceptions for the agent subsystem."""


class AgentError(Exception):
    """Base exception for agent subsystem."""


class AgentSessionError(AgentError):
    """Session file missing, expired, or corrupted."""


class AgentSessionRevokedError(AgentSessionError):
    """Agent session is no longer authorized and must be linked again."""


class AgentFloodWaitError(AgentError):
    def __init__(self, retry_after: int):
        self.retry_after = retry_after
        super().__init__(f"Flood wait: retry after {retry_after}s")


class AgentBannedError(AgentError):
    """Agent account has been banned by Telegram."""


class AgentAuthError(AgentError):
    """Authentication step failed."""
