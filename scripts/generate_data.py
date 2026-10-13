"""Generate the three source systems (`make data`). Seeded, so every run is identical."""

import argparse

from order_forecast.config import FULL, SMALL
from order_forecast.data import generate


def main() -> None:
    ap = argparse.ArgumentParser(description=__doc__)
    ap.add_argument("--small", action="store_true", help="CI-sized dataset")
    ap.add_argument("--out", default="data/raw")
    args = ap.parse_args()
    tables = generate(SMALL if args.small else FULL, args.out)
    for name, df in tables.items():
        print(f"{name:18s} {len(df):>9,d} rows")


if __name__ == "__main__":
    main()
