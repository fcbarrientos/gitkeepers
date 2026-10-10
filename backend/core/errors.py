"""Errors a service function raises for the client to see. api.py renders them as JSON."""


class ApiError(Exception):
    """A failure with the HTTP status to report and a JSON-serializable detail."""

    def __init__(self, status_code: int, detail):
        super().__init__(detail)
        self.status_code = status_code
        self.detail = detail
