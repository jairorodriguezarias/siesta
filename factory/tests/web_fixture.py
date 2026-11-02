"""Disposable real HTTP/process fixture for browser checks; never calls a model."""
from pathlib import Path
import shutil
import sys
import tempfile
import time

from pipeline.__main__ import slug
from pipeline.web.runner import Desktop
from pipeline.web.server import make_server


def child(idea):
    from pipeline.phases import _read_answer
    from pipeline.pi import FACTORY, phase
    project = FACTORY / 'projects' / slug(idea)
    project.mkdir(parents=True, exist_ok=True)
    checkpoint = project / '.pipeline-checkpoint'
    if checkpoint.exists() and checkpoint.read_text() == 'complete':
        print('Completed project resumed without another interview.')
        return
    (project / '.pipeline-idea').write_text(idea)
    phase(0, 'Interview')
    time.sleep(1)
    print('What should the timer count?')
    answer = _read_answer()
    print(f'Answer received: {answer}')
    phase(3, 'Build')
    time.sleep(3)
    (project / '.siesta').mkdir()
    (project / 'spec.md').write_text('# Timer\nR1: Count seconds.\n<img src=x onerror=alert(1)>')
    (project / 'issues.md').write_text('## Issue #1: Build the timer\n')
    (project / '.siesta/requirements.md').write_text('R1 → tests/test_timer.py::test_seconds → timer.py')
    (project / 'verify_verdict.txt').write_text('VERIFY_PASSED')
    (project / '.pipeline-checkpoint').write_text('complete')
    phase(6, 'Complete')
    print('Controlled fixture finished. No model was called.')


class FixtureDesktop(Desktop):
    def start(self, idea, *, auto=False, command=None, model_selection=None,
              review_policy=None):
        return super().start(idea, auto=auto,
                             command=[sys.executable, '-u', __file__, '--child', idea],
                             model_selection=model_selection,
                             review_policy=review_policy)


def serve():
    with tempfile.TemporaryDirectory(prefix='siesta-browser-fixture-') as directory:
        factory = Path(directory)
        (factory / 'config').mkdir()
        shutil.copyfile(Path(__file__).resolve().parents[1] / 'config/models.json',
                        factory / 'config/models.json')
        desktop = FixtureDesktop(factory)
        server = make_server(desktop, port=0)
        print(f'http://127.0.0.1:{server.server_port}', flush=True)
        try:
            server.serve_forever()
        except KeyboardInterrupt:
            pass
        finally:
            server.server_close()
            desktop.close()


if __name__ == '__main__':
    if len(sys.argv) > 1 and sys.argv[1] == '--child':
        child(sys.argv[2])
    else:
        serve()
