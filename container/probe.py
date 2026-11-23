import json
import sys
from urllib.request import urlopen

url = (
    "http://127.0.0.1:18081/health"
    if sys.argv[1] == "model"
    else "http://127.0.0.1:8080/health/ready"
)
with urlopen(url, timeout=4) as response:
    result = json.load(response)
if result.get("status") != "ok":
    sys.exit(1)
if len(sys.argv) > 2 and result.get("version") != sys.argv[2]:
    sys.exit(1)
if len(sys.argv) > 2 and sys.argv[1] == "web":
    with urlopen("http://127.0.0.1:8080/api/bulletin", timeout=8) as response:
        if not isinstance(json.load(response).get("items"), list):
            sys.exit(1)
