"""Send the fixed plan with one authenticated HTTPS session per terminal."""

import json
from collections import Counter, defaultdict
from concurrent.futures import ThreadPoolExecutor
from math import ceil
from time import monotonic, sleep

import requests

from .config import Config
from .plan import PlannedEvent


def _send(session: requests.Session, config: Config, payload: dict,
          latencies: list[float], counts: Counter, rejected: Counter) -> bool:
    for attempt in range(config.max_attempts):
        started = monotonic()
        counts["sent"] += 1
        try:
            response = session.post(f"{config.base_url.rstrip('/')}/pos/events",
                                    json=payload, timeout=config.request_timeout)
        except requests.Timeout:
            counts["timeouts"] += 1
            code = "TIMEOUT"
        except requests.ConnectionError:
            counts["connection_errors"] += 1
            code = "CONNECTION_ERROR"
        else:
            if response.status_code == 503:
                counts["service_unavailable"] += 1
                code = "SERVICE_UNAVAILABLE"
            else:
                try:
                    body = response.json()
                except ValueError:
                    body = {}
                if response.ok and body.get("outcome") in ("OK", "DUPLICATE"):
                    counts[body["outcome"].lower()] += 1
                    return True
                rejected[body.get("code", f"HTTP_{response.status_code}")] += 1
                return False
        finally:
            latencies.append((monotonic() - started) * 1000)
        if attempt + 1 < config.max_attempts:
            sleep(min(0.1 * 2 ** min(attempt, 4), 1))
    rejected[code] += 1
    return False


def run(config: Config, events: list[PlannedEvent]) -> dict:
    tokens = json.loads(config.tokens_file.read_text(encoding="utf-8-sig"))
    by_pos = defaultdict(list)
    for event in events:
        by_pos[event.payload["pos_id"]].append(event)
    credentials = {}
    for pos in by_pos:
        cert, key = (config.terminal_cert_dir / f"{pos}.{suffix}" for suffix in ("crt", "key"))
        if not config.ca_file.is_file() or not cert.is_file() or not key.is_file():
            raise ValueError(f"Missing CA or client certificate/key for {pos}.")
        if not isinstance(tokens.get(pos), str) or not tokens[pos]:
            raise ValueError(f"Missing token for {pos}.")
        credentials[pos] = (str(cert), str(key))

    started = monotonic()

    def send_terminal(pos: str) -> tuple[Counter, Counter, list[float]]:
        accepted: set[str] = set()
        counts, rejected, latencies = Counter(), Counter(), []
        with requests.Session() as session:
            session.verify = str(config.ca_file)
            session.cert = credentials[pos]
            session.headers["Authorization"] = f"Bearer {tokens[pos]}"
            for event in by_pos[pos]:
                payload = event.payload
                original = payload["original_transaction_id"]
                if original and original not in accepted:
                    counts["skipped_unaccepted_sale"] += 1
                    continue
                sleep(max(0, started + event.offset - monotonic()))
                if not _send(session, config, payload, latencies, counts, rejected):
                    continue
                if payload["event_type"] == "SALE":
                    accepted.add(payload["transaction_id"])
                if event.resend is not None:
                    counts[f"fault_{event.fault}"] += 1
                    _send(session, config, event.resend, latencies, counts, rejected)
        return counts, rejected, latencies

    counts, rejected, latencies = Counter(), Counter(), []
    with ThreadPoolExecutor(max_workers=len(by_pos)) as executor:
        for local_counts, local_rejected, local_latencies in executor.map(send_terminal, by_pos):
            counts.update(local_counts)
            rejected.update(local_rejected)
            latencies.extend(local_latencies)
    latencies.sort()
    return {
        "planned": len(events),
        **{key: counts[key] for key in ("sent", "ok", "duplicate", "skipped_unaccepted_sale",
                                        "timeouts", "service_unavailable", "connection_errors",
                                        "fault_duplicate", "fault_conflict", "fault_timeout_retry")},
        "rejected": dict(rejected),
        "latency_ms": {
            f"p{percent}": round(latencies[ceil(len(latencies) * percent / 100) - 1], 2)
            if latencies else None for percent in (50, 95, 99)
        },
    }
