"""Build a reproducible PB-39 or DS-09 scenario 7 simulator configuration."""

import argparse
from pathlib import Path

import yaml


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("scenario", choices=("normal", "peak", "duplicate-storm"))
    parser.add_argument("--run-id", required=True)
    parser.add_argument("--output", type=Path, required=True)
    parser.add_argument("--duration-minutes", type=float, default=30)
    args = parser.parse_args()
    if args.duration_minutes <= 0:
        parser.error("--duration-minutes must be positive")

    root = Path(__file__).resolve().parent
    config = yaml.safe_load((root / "config.example.yaml").read_text(encoding="utf-8"))
    del config["event_count"]
    config.update(
        duration_minutes=args.duration_minutes,
        run_id=args.run_id,
        base_url="https://pos-gateway:9443/api/v1",
        rate_per_pos_per_second=6 if args.scenario == "peak" else 2,
        stores=[
            {"store_id": f"STORE-DN{i}", "pos": [f"POS-DN{i}-01", f"POS-DN{i}-02"]}
            for i in range(1, 4)
        ],
        fault_injection={
            "duplicate_rate": 0.3 if args.scenario == "duplicate-storm" else 0,
            "conflict_rate": 0,
            "timeout_retry_rate": 0,
        },
        ca_file="/repo/.certs/ca.crt",
        terminal_cert_dir="/repo/.certs/pos",
        tokens_file="/repo/.tokens/demo_tokens.json",
        summary_file=f"{args.scenario}-summary.json",
    )
    args.output.write_text(yaml.safe_dump(config, sort_keys=False), encoding="utf-8")


if __name__ == "__main__":
    main()
