"""Run a deterministic POS plan over mutual TLS and write its JSON summary."""

import argparse
import json
from pathlib import Path

from .config import read_config
from .plan import generate
from .transport import run


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--config", required=True, type=Path)
    args = parser.parse_args()
    try:
        config = read_config(args.config)
        summary = run(config, generate(config))
        output = json.dumps(summary, indent=2, sort_keys=True)
        config.summary_file.write_text(output + "\n", encoding="utf-8")
    except (OSError, ValueError) as error:
        parser.exit(2, f"Simulator setup failed: {error}\n")
    print(output)


if __name__ == "__main__":
    main()
