"""POS API request/response logging for Docker Compose logs.

Pure ASGI middleware: it only observes a POS request. The request body is
buffered and replayed, so the route handler still receives every byte, and each
response message is forwarded unchanged. No header is logged, so the bearer
token, the gateway secret and the forwarded certificate never reach the log.
"""

import json
from datetime import datetime
from http import HTTPStatus
from time import perf_counter


POS_PREFIX = "/api/v1/pos"
BODY_LIMIT = 4000
TRUNCATED = "\n... (truncated)"


def _pretty(raw: bytes) -> str:
    """Render a JSON body for the log; never raise on a body that is not JSON."""
    if not raw:
        return "(no JSON body)"
    text = raw.decode(errors="replace")
    try:
        pretty = json.dumps(json.loads(text), ensure_ascii=False, indent=2)
    except ValueError:
        pretty = text
    if len(pretty) > BODY_LIMIT:
        return pretty[:BODY_LIMIT] + TRUNCATED
    return pretty


def _status_line(status: int) -> str:
    try:
        return f"{status} {HTTPStatus(status).phrase}".strip()
    except ValueError:
        return str(status)


def _emit(block: str) -> None:
    """Write one block to stdout without letting a logging failure touch the response."""
    try:
        print(block, flush=True)
    except Exception:  # pragma: no cover - stdout is normally always writable
        pass


def _log_request(method: str, path: str, body: bytes) -> None:
    now = datetime.now().strftime("%Y-%m-%d %H:%M:%S")
    _emit(
        "========== POS API REQUEST ==========\n"
        f"Time: {now}\n"
        f"Method: {method}\n"
        f"Path: {path}\n"
        "\nRequest JSON:\n"
        f"{_pretty(body)}"
    )


def _log_response(status: int | None, body: bytes, elapsed_ms: float,
                  failure: BaseException | None, failure_status: int) -> None:
    if status is None:
        failure_line = _status_line(failure_status)
        status_line = (f"{failure_line} (unhandled {type(failure).__name__})"
                       if failure else "unknown")
    else:
        status_line = _status_line(status)
    text = _pretty(body)
    if failure is not None and not body:
        text = f"(no JSON body: unhandled {type(failure).__name__}: {failure})"
    _emit(
        "\n========== POS API RESPONSE ==========\n"
        f"Status: {status_line}\n"
        "\nResponse JSON:\n"
        f"{text}\n"
        "\nDuration: "
        f"{elapsed_ms:.0f}ms\n"
        "=====================================\n"
    )


class PosRequestLoggingMiddleware:
    """Log one POS request/response pair; every other request passes straight through.

    ``failure_status`` is the status this application returns for an unhandled
    exception (503 through the global handler in ``app.core.errors``). It is a
    parameter because the middleware cannot see that response: the handler runs
    outside this layer.
    """

    def __init__(self, app, failure_status: int = 500):
        self.app = app
        self.failure_status = failure_status

    async def __call__(self, scope, receive, send):
        if scope["type"] != "http" or not scope.get("path", "").startswith(POS_PREFIX):
            await self.app(scope, receive, send)
            return

        started = perf_counter()
        buffered = []
        while True:
            message = await receive()
            buffered.append(message)
            if message["type"] == "http.disconnect":
                break
            if not message.get("more_body", False):
                break
        request_body = b"".join(
            message.get("body", b"") for message in buffered
            if message["type"] == "http.request"
        )

        replay = iter(buffered)

        async def replay_receive():
            try:
                return next(replay)
            except StopIteration:
                return await receive()

        _log_request(scope.get("method", ""), scope.get("path", ""), request_body)

        state = {"status": None}
        response_chunks = []

        async def capture_send(message):
            if message["type"] == "http.response.start":
                state["status"] = message["status"]
            elif message["type"] == "http.response.body":
                response_chunks.append(message.get("body", b""))
            await send(message)

        failure = None
        try:
            await self.app(scope, replay_receive, capture_send)
        except BaseException as error:
            failure = error
            raise
        finally:
            elapsed = (perf_counter() - started) * 1000
            _log_response(state["status"], b"".join(response_chunks), elapsed, failure,
                          self.failure_status)
