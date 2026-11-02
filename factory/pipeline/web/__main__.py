"""Run with PYTHONPATH=factory python3 -m pipeline.web."""
import argparse
import os
from pathlib import Path
import signal

from .runner import Desktop
from .server import make_server


def main():
    parser = argparse.ArgumentParser(description='Siesta local retro desktop')
    parser.add_argument('--port', type=int, default=8765)
    parser.add_argument('--factory', type=Path,
                        default=Path(os.environ.get('SIESTA_FACTORY', Path(__file__).resolve().parents[2])))
    args = parser.parse_args()
    if not (args.factory / 'config/models.json').is_file():
        parser.error('Factory must contain config/models.json')
    desktop = Desktop(args.factory)
    def stop(_signum, _frame):
        raise KeyboardInterrupt
    signal.signal(signal.SIGTERM, stop)
    try:
        server = make_server(desktop, port=args.port)
        print(f'Siesta desktop: http://127.0.0.1:{server.server_port}', flush=True)
        print('Keep this terminal open. Ctrl+C stops the server and its active run.', flush=True)
        try:
            server.serve_forever()
        except KeyboardInterrupt:
            pass
        finally:
            server.server_close()
    finally:
        desktop.close()


if __name__ == '__main__':
    main()
