"""Exercise the real local translation route against fixed PostgreSQL examples."""

import json
import re
import statistics
import sys
import time
from pathlib import Path

root = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(root))
import app  # noqa: E402

cases = json.loads((root / "tests/translation-cases.json").read_text(encoding="utf8"))
results = []
for source, required, forbidden in cases:
    start = time.monotonic()
    try:
        answer = app.translate(source)
        good = (
            app.safe_instruction(source, answer)
            and app.reasons_supported(source, answer)
            and app.terms_preserved(app.glossary_for(source), answer)
            and sorted(app.TECHNICAL.findall(source))
            == sorted(app.TECHNICAL.findall(answer))
            and all(re.search(p, answer, re.I) for p in required)
            and not any(re.search(p, answer, re.I) for p in forbidden)
        )
    except Exception as exc:
        answer, good = str(exc), False
    results.append(
        dict(
            en=source,
            tr=answer,
            accepted=bool(good),
            seconds=round(time.monotonic() - start, 2),
        )
    )
    print(len(results), bool(good), answer, flush=True)
    Path(sys.argv[1]).write_text(
        json.dumps(results, ensure_ascii=False, indent=2), encoding="utf8"
    )
print(
    "Passed",
    sum(r["accepted"] for r in results),
    "of",
    len(results),
    "median",
    statistics.median(r["seconds"] for r in results),
)
