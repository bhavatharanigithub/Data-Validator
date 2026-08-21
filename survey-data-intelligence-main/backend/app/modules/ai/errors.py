class AIUnavailableError(Exception):
    def __init__(self, reason: str, message: str = "AI provider unavailable") -> None:
        super().__init__(message)
        self.reason = reason
        self.message = message
