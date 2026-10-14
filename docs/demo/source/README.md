# Video and audit report sources

Everything needed to rebuild the silent walkthrough (`docs/demo/demo.mp4`) and the audit report
(`docs/demo/AUDIT_REPORT.*`) from this repository alone. Paths below are relative to the repo root.

## What is here

| Path | What it is |
|---|---|
| `index.html` | Root of the video: theme (colours, type), and the timing of every slide |
| `compositions/bg.html`, `compositions/chrome.html` | Background grid, and the persistent project label, slide counter and progress bar |
| `compositions/s01-context.html` | Slide 01, the industry and four everyday problems |
| `compositions/s02-hook.html` | Slide 02, the project in one sentence |
| `compositions/explainer.html` | Slides 03-04, the white "how it works" chapter (edit its `CONFIG` block) |
| `compositions/s03-architecture.html` | Slide 05, the layered architecture diagram (sources, SQL feature layer, models, decision, evaluation) |
| `compositions/s04-routes.html` | Slide 06, one SKU's forecasts and the weekly stock value at 98% fill (data injected by `tools/inject_sheet.py`) |
| `compositions/value.html` | Slide 07, the planner's replenishment order list and warehouse scene (data injected by `tools/inject_sheet.py`) |
| `compositions/s05-results.html`, `s06-twist.html`, `s07-end.html` | Slides 08-10, results, what didn't win, end card |
| `assets/order_list.json` | Friday 2025-09-26 order list for all 150 SKUs, the slide 06 traces, exported by `tools/export_order_list.py` |
| `audit/facts.yaml` | Every figure (F-xx), assumption (A-xx), slide text and check expression used by the report |
| `tools/build_audit_report.py` | Builds the slide stills, re-checks every figure against the repo outputs, writes MD, DOCX and PDF |
| `tools/export_order_list.py` | Re-runs the repo's own backtest for the two-stage LightGBM and ETS forecasters, asserts it matches `outputs/inventory.csv`, and exports the order list and traces as JSON |
| `tools/inject_sheet.py` | Inlines that JSON into `compositions/value.html` and `compositions/s04-routes.html` (renders cannot fetch files) |
| `package.json`, `hyperframes.json`, `meta.json` | HyperFrames project files (CLI pinned to 0.8.156) |

The repo writes no plots, so the series has no `darkmap.py` step: both charts on slide 06 are drawn
from the exported JSON. Fonts (Inter, JetBrains Mono, Montserrat) are referenced by name and
embedded by the HyperFrames renderer; all three are SIL Open Font License.

## Requirements

- Node 22 and `npx` (HyperFrames 0.8.156 is fetched by `npx`), plus Chrome/Chromium for rendering.
- `ffmpeg` for compressing the video and extracting slide stills.
- LibreOffice (`soffice`) to convert the report to PDF.
- The repo's own environment (`uv sync`) for `make run` and `export_order_list.py`.
- For `build_audit_report.py` and `inject_sheet.py` (any Python 3.11+, not added to the repo's
  `pyproject.toml`): `pip install pyyaml pandas pyarrow python-docx pillow numpy matplotlib`.

## Rebuild the numbers, the video and the report

```bash
# 1. repo outputs (about 9 minutes)
make run

# 2. inputs for the video (the export re-fits two forecasters, about 4 minutes)
PYTHONPATH=src .venv/bin/python docs/demo/source/tools/export_order_list.py docs/demo/source/assets/order_list.json
python3 docs/demo/source/tools/inject_sheet.py docs/demo/source/assets/order_list.json \
  docs/demo/source/compositions/value.html docs/demo/source/compositions/s04-routes.html \
  --rows S0108,S0014,S0005,S0066,S0131,S0044

# 3. render (88.8 s, 1920x1080, 30 fps, silent) and compress
cd docs/demo/source
npx --yes hyperframes@0.8.156 check
npx --yes hyperframes@0.8.156 render -f 30 -q looks -o renders/order-forecast-inventory-master.mp4
cd -
ffmpeg -y -i docs/demo/source/renders/order-forecast-inventory-master.mp4 -c:v libx264 -preset slow -crf 25 \
  -pix_fmt yuv420p -movflags +faststart -an docs/demo/demo.mp4

# 4. audit report: slide stills, automated checks, AUDIT_REPORT.md/.docx/.pdf
python3 docs/demo/source/tools/build_audit_report.py docs/demo/source/audit/facts.yaml
```

`build_audit_report.py` exits with code 1 if any figure on screen no longer matches the repo outputs.
`export_order_list.py` stops with an assertion error if its re-run does not reproduce
`outputs/inventory.csv`, so the order list always comes from the same simulation as the published
numbers. The report lists which figures and slides each input affects (change-impact matrix).

The `renders/` folder (about 15 MB) is not committed; step 3 recreates it.
