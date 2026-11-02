"""Optional local status channel, separate from model-controlled console output."""
import json
import os
from pathlib import Path


def update(**fields) -> None:
    destination = os.environ.get('SIESTA_STATUS_FILE')
    if not destination:
        return
    path = Path(destination)
    state = json.loads(path.read_text()) if path.exists() else {}
    state.update(fields)
    temporary = path.with_suffix('.tmp')
    temporary.write_text(json.dumps(state))
    temporary.replace(path)
