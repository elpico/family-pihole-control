import os
import tempfile

os.environ.setdefault("PIHOLE_URL", "http://testpihole.local")
os.environ.setdefault(
    "SCHEDULE_DIR", tempfile.mkdtemp(prefix="family-pihole-tests-")
)
os.environ.setdefault("SCHEDULER_TICK_SECONDS", "3600")
