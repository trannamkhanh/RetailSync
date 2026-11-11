"""Generate all events and fault payloads before making any network requests."""

from dataclasses import dataclass
from datetime import timedelta
from hashlib import sha256
from random import Random

from .config import Config


@dataclass(frozen=True)
class PlannedEvent:
    offset: float
    payload: dict
    fault: str | None
    resend: dict | None


def _fault(config: Config, random: Random, payload: dict) -> tuple[str | None, dict | None]:
    roll = random.random()
    rates = config.fault_injection
    if roll < rates.duplicate_rate:
        return "duplicate", payload
    roll -= rates.duplicate_rate
    if roll < rates.conflict_rate:
        if payload["event_type"] != "SALE":
            return None, None
        first, *rest = payload["items"]
        return "conflict", {**payload, "items": [{**first, "quantity": first["quantity"] + 1}, *rest]}
    if roll < rates.conflict_rate + rates.timeout_retry_rate:
        return "timeout_retry", payload
    return None, None


def generate(config: Config) -> list[PlannedEvent]:
    random = Random(config.seed)
    terminals = config.terminals
    count = config.event_count
    if count is None:
        count = max(1, round(config.duration_minutes * 60 * config.rate_per_pos_per_second * len(terminals)))
    prefix = sha256(f"{config.run_id}/{config.seed}".encode()).hexdigest()[:16]
    sales: dict[str, dict[str, tuple[list[dict], bool]]] = {pos: {} for _, pos in terminals}
    events = []
    kinds = ("SALE", "RETURN", "CANCELLATION")
    for index in range(count):
        store, pos = terminals[index % len(terminals)]
        offset = (index // len(terminals)) / config.rate_per_pos_per_second
        candidates = sales[pos]
        kind = random.choices(kinds, [config.mix[key] for key in kinds])[0]
        eligible = [key for key, (remaining, returned) in candidates.items()
                    if remaining and (kind == "RETURN" or not returned)]
        txn = f"SIM-{prefix}-{index:08d}"
        original = None
        if kind == "SALE" or not eligible:
            kind = "SALE"
            skus = random.sample(sorted(config.catalogue), random.randint(
                config.items_per_sale.min, config.items_per_sale.max,
            ))
            items = [{"sku": sku, "quantity": random.randint(1, 3), "unit_price": config.catalogue[sku]}
                     for sku in skus]
            candidates[txn] = ([item.copy() for item in items], False)
        else:
            original = random.choice(eligible)
            remaining, _ = candidates[original]
            items = []
            if kind == "RETURN":
                item = random.choice(remaining)
                items = [{**item, "quantity": random.randint(1, item["quantity"])}]
                item["quantity"] -= items[0]["quantity"]
                candidates[original] = ([line for line in remaining if line["quantity"]], True)
            else:
                del candidates[original]

        payload = {
            "transaction_id": txn, "event_type": kind, "store_id": store, "pos_id": pos,
            "timestamp": (config.start_at + timedelta(seconds=offset)).isoformat(),
            "original_transaction_id": original, "items": items,
        }
        fault, resend = _fault(config, random, payload)
        events.append(PlannedEvent(offset, payload, fault, resend))
    return events
