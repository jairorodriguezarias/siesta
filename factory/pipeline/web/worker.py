"""Run the existing CLI with graceful desktop shutdown, including Pi children."""
import signal

from ..__main__ import main as run


class DesktopShutdown(BaseException):
    """Unwind subprocess cleanup without starting failure-learning model calls."""


def main():
    def stop(_signum, _frame):
        raise DesktopShutdown()

    signal.signal(signal.SIGTERM, stop)
    try:
        run()
    except DesktopShutdown:
        print('Desktop closed; execution interrupted.', flush=True)
        raise SystemExit(130)


if __name__ == '__main__':
    main()
