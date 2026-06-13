class ToolPermissionError(PermissionError):
    pass


class ToolRateLimitError(RuntimeError):
    pass


class ToolValidationError(ValueError):
    pass
