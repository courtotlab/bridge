"""Maps known library / connection exceptions to plain-language strings."""


def translate(exc: Exception, context: str = "") -> str:
    msg = str(exc).lower()

    if "connection" in msg and "refused" in msg:
        if "11434" in str(exc):
            return "Could not reach Ollama — is it running at localhost:11434?"
        if context:
            return f"Could not connect to {context} — is the server running?"
        return "Connection refused — is the server running?"

    if "timeout" in msg or "timed out" in msg:
        return f"Connection timed out{' to ' + context if context else ''} — the server took too long to respond."

    if "401" in msg or "unauthorized" in msg or "authentication" in msg:
        return "Invalid API key — please check your credentials."

    if "403" in msg or "forbidden" in msg:
        return "Access denied — your API key may not have the required permissions."

    if (
        "name or service not known" in msg
        or "nodename nor servname" in msg
        or "getaddrinfo" in msg
    ):
        return f"Could not resolve host{' ' + context if context else ''} — check your internet connection and server URL."

    if "sslerror" in msg or "ssl" in msg:
        return "SSL certificate error — the server's certificate could not be verified."

    return str(exc)
