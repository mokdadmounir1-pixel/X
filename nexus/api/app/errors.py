class NexusError(Exception):
    status = 400
    code = "error"

    def __init__(self, message: str = "", code: str | None = None):
        super().__init__(message or self.code)
        if code:
            self.code = code
        self.message = message or self.code


class Forbidden(NexusError):
    status, code = 403, "forbidden"


class Unauthorized(NexusError):
    status, code = 401, "unauthorized"


class NotFound(NexusError):
    status, code = 404, "not_found"


class Conflict(NexusError):
    status, code = 409, "conflict"


class Invalid(NexusError):
    status, code = 422, "invalid"


class EmergencyStopped(NexusError):
    status, code = 423, "emergency_stop"


class LLMUnavailable(NexusError):
    """Ollama injoignable, trop lent ou réponse inutilisable. Erreur transitoire."""
    status, code = 503, "llm_unavailable"


class LLMBadOutput(NexusError):
    status, code = 502, "llm_bad_output"
