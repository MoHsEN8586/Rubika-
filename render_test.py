import sys
from datetime import datetime, timezone

print("=== Render Python test ===", flush=True)
print("Python version:", sys.version, flush=True)
print("UTC time:", datetime.now(timezone.utc).isoformat(), flush=True)
print("Test status: SUCCESS — Python script ran.", flush=True)
