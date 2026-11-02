#!/bin/bash
# Run the Python pipeline and retain a local console transcript.
set -euo pipefail

FACTORY_DIR="$(cd "$(dirname "$0")/.." && pwd)"
exec > >(tee -a "$FACTORY_DIR/pipeline.log") 2>&1

printf 'Siesta · describe → review → build → verify\n\n'
exec env PYTHONPATH="$FACTORY_DIR${PYTHONPATH:+:$PYTHONPATH}" python3 -m pipeline "$@"
