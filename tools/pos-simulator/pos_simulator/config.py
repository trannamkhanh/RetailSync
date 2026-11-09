"""Validate the simulator configuration before generating or sending events."""

from pathlib import Path
from typing import Annotated

import yaml
from pydantic import AwareDatetime, BaseModel, Field, model_validator


Sku = Annotated[str, Field(min_length=1, max_length=20, pattern=r"^[A-Za-z0-9_-]+$")]
Price = Annotated[str, Field(pattern=r"^\d{1,10}(\.\d{1,2})?$")]
Probability = Annotated[float, Field(ge=0, le=1)]


class Store(BaseModel):
    store_id: str = Field(min_length=1, max_length=10, pattern=r"^[A-Za-z0-9_-]+$")
    pos: list[Sku] = Field(min_length=1)


class ItemRange(BaseModel):
    min: int = Field(ge=1, le=100)
    max: int = Field(ge=1, le=100)


class Faults(BaseModel):
    duplicate_rate: Probability = 0
    conflict_rate: Probability = 0
    timeout_retry_rate: Probability = 0


class Config(BaseModel):
    seed: int
    run_id: str = Field(min_length=1)
    start_at: AwareDatetime
    duration_minutes: float | None = Field(default=None, gt=0, allow_inf_nan=False)
    event_count: int | None = Field(default=None, gt=0)
    base_url: str = Field(pattern=r"^https://[^\s/]+/api/v1/?$")
    stores: list[Store] = Field(min_length=1)
    rate_per_pos_per_second: float = Field(gt=0, allow_inf_nan=False)
    mix: dict[str, Probability]
    items_per_sale: ItemRange
    fault_injection: Faults = Field(default_factory=Faults)
    catalogue: dict[Sku, Price] = Field(min_length=1)
    ca_file: Path
    terminal_cert_dir: Path
    tokens_file: Path
    summary_file: Path = Path("summary.json")
    request_timeout: float = Field(default=5, gt=0, allow_inf_nan=False)
    max_attempts: int = Field(default=5, ge=1)

    @model_validator(mode="after")
    def check_plan(self) -> "Config":
        if (self.event_count is None) == (self.duration_minutes is None):
            raise ValueError("Set exactly one of event_count and duration_minutes.")
        if len({store.store_id for store in self.stores}) != len(self.stores):
            raise ValueError("Store IDs must be unique.")
        if len({pos for _, pos in self.terminals}) != len(self.terminals):
            raise ValueError("Terminal IDs must be unique.")
        if set(self.mix) != {"SALE", "RETURN", "CANCELLATION"} or not any(self.mix.values()):
            raise ValueError("Set weights for SALE, RETURN and CANCELLATION, with at least one above zero.")
        if not self.items_per_sale.min <= self.items_per_sale.max <= len(self.catalogue):
            raise ValueError("Invalid items_per_sale range for this catalogue.")
        if sum(self.fault_injection.model_dump().values()) > 1:
            raise ValueError("Fault probabilities must add up to at most one.")
        return self

    @property
    def terminals(self) -> list[tuple[str, str]]:
        return [(store.store_id, pos) for store in self.stores for pos in store.pos]


def read_config(path: Path) -> Config:
    config = Config.model_validate(yaml.safe_load(path.read_text(encoding="utf-8")))
    for field in ("ca_file", "terminal_cert_dir", "tokens_file", "summary_file"):
        setattr(config, field, path.parent / getattr(config, field))
    return config
