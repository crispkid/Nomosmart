class Rejected(Exception):
    """Safe error code only; never include tool stderr or document content."""
    def __init__(self, code):
        self.code = code
        super().__init__(code)


def need(condition, code="invalid_request"):
    if not condition:
        raise Rejected(code)
