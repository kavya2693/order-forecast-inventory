"""How intermittent the customer x SKU lines are (`make profile`), for the README's framing."""

import argparse
import json

from order_forecast.pipeline import connect, run_sql

QUERY = """
SELECT
    MEDIAN(rate) AS median_line_order_rate,
    AVG(CASE WHEN rate < 0.5 THEN 1.0 ELSE 0.0 END) AS share_lines_ordering_under_half_of_weeks,
    (SELECT AVG(CASE WHEN qty > 0 THEN 0.0 ELSE 1.0 END) FROM panel) AS share_zero_line_weeks
FROM (
    SELECT customer_id, sku_id, AVG(CASE WHEN qty > 0 THEN 1.0 ELSE 0.0 END) AS rate
    FROM panel
    GROUP BY customer_id, sku_id
)
"""


def main() -> None:
    ap = argparse.ArgumentParser(description=__doc__)
    ap.add_argument("--data", default="data/raw")
    ap.add_argument("--out", default="outputs/data_profile.json")
    args = ap.parse_args()
    con = connect(args.data)
    run_sql(con)
    row = con.execute(QUERY).fetchone()
    con.close()
    assert row is not None
    names = ["median_line_order_rate", "share_lines_ordering_under_half_of_weeks", "share_zero_line_weeks"]
    profile = {k: round(float(v), 4) for k, v in zip(names, row, strict=True)}
    with open(args.out, "w") as f:
        json.dump(profile, f, indent=2)
    print(json.dumps(profile, indent=2))


if __name__ == "__main__":
    main()
