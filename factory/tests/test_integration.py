"""End-to-end pipeline runs against a fake `pi` on PATH — no live models.

The stub logs every call to $FAKE_PI_LOG, keys off the role's model name,
--skill flags and prompt markers; FAKE_PI_SCENARIO drives the escalation
ladder, proxy flow and failure paths. SIESTA_FACTORY redirects projects/,
kb/ and skills/ into a temp copy so runs never touch the real factory, and
each test gets a unique project name so the copied global KB can't collide.
"""
import json
import os
import shutil
import subprocess
import sys
import tempfile
import unittest
from pathlib import Path
from uuid import uuid4

from pipeline import phases

FACTORY = Path(__file__).resolve().parent.parent
GIT_ENV = {"GIT_AUTHOR_NAME": "Siesta Test", "GIT_AUTHOR_EMAIL": "test@example.invalid",
           "GIT_COMMITTER_NAME": "Siesta Test", "GIT_COMMITTER_EMAIL": "test@example.invalid"}
STUB = r"""#!/bin/bash
# fake-pi — canned model responses for the pipeline integration tests.
piped_prompt=$(cat)
if [ -n "$piped_prompt" ]; then set -- "$@" "$piped_prompt"; fi
printf '%s\n' "$*" >> "${FAKE_PI_LOG:-/dev/null}"

model="" prev=""
for a in "$@"; do [ "$prev" = "--model" ] && model="$a"; prev="$a"; done

implement() {
  printf 'def greeting():\n    return "hello"\n' > todo.py
  printf 'from todo import greeting\n\ndef test_greeting():\n    assert greeting() == "hello"\n' > test_todo.py
  if [ "$FAKE_PI_SCENARIO" = "verify_mutates" ]; then
    printf '\ndef test_final_cleanup():\n    from pathlib import Path\n    if Path("verify_output.txt").exists():\n        Path("todo.py").write_text("def greeting(): return 999\\n")\n' >> test_todo.py
  fi
  if [ "$FAKE_PI_SCENARIO" = "verify_mutates_during_audit" ]; then
    cat >> test_todo.py <<'TEST'

def test_final_cleanup():
    from pathlib import Path
    import subprocess
    import sys
    if Path('verify_output.txt').exists():
        child = '''
from pathlib import Path
import time
deadline = time.monotonic() + 5
while not Path('.siesta/audit_started').exists():
    if time.monotonic() >= deadline:
        raise SystemExit('Audit did not start')
    time.sleep(0.01)
Path('todo.py').write_text('def greeting(): return 999\\n')
Path('.siesta/audit_mutation_done').touch()
'''
        subprocess.Popen([sys.executable, '-c', child],
                         stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL)
TEST
  fi
  if [ "$FAKE_PI_SCENARIO" = "final_commit_fails" ]; then
    printf '#!/bin/sh\ncase "$(cat "$1")" in\n  "Project verified:"*) exit 1 ;;\nesac\n' > .git/hooks/commit-msg
    chmod +x .git/hooks/commit-msg
  fi
  python3 -m pytest -q >&2
}

case "$model" in
  planner-model|planning-agent-model)
    case "$*" in
      *"You are a software architect."*)
        # No file writes: the model prints the document, the pipeline saves it.
        case "$FAKE_PI_SCENARIO" in
          never_spec) echo "sorry, cannot write a spec right now" ;;
          *) printf '# Spec\n\nA tiny todo CLI in Python with root-tested behavior.\nStores tasks in memory, runs offline.\n\n## Acceptance criteria\n- R1: Return a hello greeting.\n' ;;
        esac ;;
      *"You are a project planner."*)
        case "$FAKE_PI_SCENARIO" in
          repair_fails_forever_3) printf '# Issues\n\n## Issue #1: Add hello\nR1: Return a hello greeting.\nWrite hello.\nTest strategy: Assert the exact greeting.\nDependencies: none.\n\n## Issue #2: Add bye\nWrite bye.\nTest strategy: Assert the bye output.\nDependencies: #1.\n\n## Issue #3: Add more\nWrite more.\nTest strategy: Assert the additional output.\nDependencies: #2.\n' ;;
          *) printf '# Issues\n\n## Issue #1: Add hello\nR1: Return a hello greeting.\nWrite hello.\nTest strategy: Assert the exact greeting.\nDependencies: none.\n\n## Issue #2: Add bye\nWrite bye.\nTest strategy: Assert the bye output.\nDependencies: #1.\n' ;;
        esac ;;
      *"Close out the interview now"*)
        # #45: autonomous close-out after the human left mid-interview
        echo "INTENT_FINALIZED: a tiny todo cli with sensible defaults" ;;
      *"interview-me"*)
        # #55: the interview is a python-mediated dialog — each call is one
        # model turn. Subprocess tests have no human, so the dialog ends at
        # EOF after this turn and the close-out finalizes with defaults.
        printf 'Q: What kind of user interface do you want?\nGUESS: terminal CLI — simplest to verify.\n' ;;
    esac ;;
  consultant-model)
    case "$*" in
      *"Agent identity: intent-critic"*)
        case "$FAKE_PI_SCENARIO" in
          intent_review_blocked)
            echo '{"version":1,"verdict":"blocked","candidate":"A todo CLI.","changes":[],"unresolved":[{"id":"U1","question":"Should tasks sync to a hosted service?","reason":"The request does not choose a sync policy.","options":["local only","hosted sync"]}]}' ;;
          *) echo '{"version":1,"verdict":"pass","changes":[],"unresolved":[]}' ;;
        esac ;;
      *"Pipeline phase: issue_review"*)
        echo '{"version":1,"verdict":"pass","summary":"The active issue satisfies its requirements.","findings":[]}' ;;
      *"Independent design review by"*)
        case "$FAKE_PI_SCENARIO" in
          design_rejected) echo '{"verdict":"failed","findings":["Specify the greeting output"]}' ;;
          *) echo '{"verdict":"passed","findings":[]}' ;;
        esac ;;
      *"Independent requirement evidence audit"*)
        if [ "$FAKE_PI_SCENARIO" = "verify_mutates_during_audit" ]; then
          touch .siesta/audit_started
          python3 - <<'WAIT'
from pathlib import Path
import time
deadline = time.monotonic() + 5
while not Path('.siesta/audit_mutation_done').exists():
    if time.monotonic() >= deadline:
        raise SystemExit('Test child did not change source during the audit')
    time.sleep(0.01)
WAIT
        fi
        case "$FAKE_PI_SCENARIO" in
          evidence_missing) echo '{"requirements":[],"drift":[]}' ;;
          *) echo '{"requirements":[{"id":"R1","status":"supported","tests":["test_todo.py::test_greeting"],"sources":["todo.py"],"reason":"The greeting assertion checks hello."}],"drift":[]}' ;;
        esac ;;
      *"Agent identity: integration-reviewer"*)
        case "$FAKE_PI_SCENARIO" in
          review_degenerate) echo '{"name": "bash", "arguments": {"command": "ls -la"}}' ;;
          *) echo '{"version":1,"verdict":"pass","summary":"Requirements and integration are sound.","findings":[]}' ;;
        esac ;;
      *"Agent identity: quality-reviewer"*)
        echo '{"version":1,"verdict":"pass","summary":"No concrete code quality defects.","findings":[]}' ;;
      *"You are the factory-learner"*)
        # #46: learning routes to the consultant — GLM owns the strict format
        echo "PROJECT_LEARNING:
  Project: stub
  Actions:
    LEARNING: stub learning — detail" ;;
      *"Evaluate if this review meets"*)
        case "$FAKE_PI_SCENARIO" in
          review_needs_revision) echo "NEEDS_REVISION: the CLI lacks input validation" ;;
          *) echo "APPROVED: meets the definition of done" ;;
        esac ;;
      *"A worker requests approval"*)
        case "$FAKE_PI_SCENARIO" in
          proxy_rejected) echo "REJECTED: over-engineered, use the standard library" ;;
          proxy_no_marker) echo "I am honestly not sure whether the human would approve this." ;;
          *) echo "APPROVED: aligned with the intent recorded in the KB" ;;
        esac ;;
      *"DEEP DIAGNOSIS"*)
        case "$FAKE_PI_SCENARIO" in
          diagnosis_skips) echo "DIAGNOSIS: wrong environment
RECOMMENDATION: skip
SKIP: log blocker and continue" ;;
          *) echo "DIAGNOSIS: wrong approach
RECOMMENDATION: restructure
DETAILED_PLAN: start over with a simpler plan" ;;
        esac ;;
      *) echo "RESOLUTION: split the work and use the standard library
APPROACH: take the simplest path" ;;
    esac ;;
  worker-model)
    case "$*" in
      *"QA engineer"*)
        case "$FAKE_PI_SCENARIO" in
          verify_fails) echo "VERIFY_FAILED: the entry point crashes on launch" ;;
          verify_fenced)
            printf 'def test_failed_verification():\n    assert False, "verification must catch this"\n' > test_verify_failure.py
            printf 'The config docs say:\n```\nVERIFY_PASSED: quoted example\n```\nbut honestly I could not check it.\n' ;;
          verify_degenerate) echo '{"name": "bash", "arguments": {"command": "ls -la"}}' ;;
          *) echo "VERIFY_PASSED: static verification complete" ;;
        esac ;;
      *"egression suite is RED"*)
        case "$FAKE_PI_SCENARIO" in
          repair_regression)
            printf 'def test_broken():\n    assert True, "repaired"\n' > tests/test_broken.py
            echo "REPAIR_DONE: fixed the failing tests" ;;
          *) echo "REPAIR_DONE: tried to fix the tests but they stay broken" ;;
        esac ;;
      *"Fix review issues"*)
        case "$FAKE_PI_SCENARIO" in
          review_needs_revision)
            printf '\n# Applied the proxy requested revision\n' >> todo.py
            echo "ISSUE_OK: applied the requested review revision and tests still pass" ;;
          *) echo "REVIEW_PASSED: no issues found" ;;
        esac ;;
      *)
        case "$FAKE_PI_SCENARIO" in
          consult_once)
            case "$*" in
              *"A senior engineer provided this guidance"*)
                implement
                echo "ISSUE_OK: implemented the greeting module and passing tests after guidance" ;;
              *) echo "CONSULT: I am stuck.
How should I implement this?" ;;
            esac ;;
          always_consult|diagnosis_skips) echo "CONSULT: I am stuck.
How should I implement this?" ;;
          proxy_request) echo "PROXY_REQUEST: requesting approval to proceed.
Justification: the change requires it." ;;
          proxy_hang) echo "PROXY_REQUEST: requesting approval to proceed.
Justification: the change requires it." ;;
          proxy_approved_implements)
            case "$*" in
              *"Approval was granted"*)
                implement
                echo "ISSUE_OK: implemented the issue after the approval" ;;
              *) echo "PROXY_REQUEST: requesting approval to proceed.
Justification: the change requires it." ;;
            esac ;;
          proxy_rejected|proxy_no_marker)
            case "$*" in
              *"Proxy rejected"*|*"Proxy did not approve"*)
                implement
                echo "ISSUE_OK: implemented a simpler approach with tests included" ;;
              *) echo "PROXY_REQUEST: requesting approval to proceed.
Justification: the change requires it." ;;
            esac ;;
          degenerate_once)
            case "$*" in
              *"Your last answer was rejected"*)
                implement
                echo "ISSUE_OK: implemented the module and its tests after the feedback" ;;
              *) echo '{"name": "bash", "arguments": {"command": "ls -la"}}' ;;
            esac ;;
          degenerate_always) echo '{"name": "bash", "arguments": {"command": "ls -la"}}' ;;
          rewrite_spec)
            implement
            printf '# Spec\n## Acceptance criteria\n- R1: Print anything.\n' > spec.md
            echo 'ISSUE_OK: weakened the spec and implemented it' ;;
          *) implement; echo "ISSUE_OK: implemented the change with tests; the suite passes." ;;
        esac ;;
    esac ;;
  *) echo "FAKE_PI: unexpected model '$model'" >&2; exit 3 ;;
esac
"""


class PipelineRun(unittest.TestCase):
    """Full `python3 -m pipeline` runs in a temp factory with the stub."""

    def setUp(self):
        self.tmp = Path(tempfile.mkdtemp(prefix="siesta-int-"))
        self.idea = f"build a tiny todo cli {uuid4().hex[:6]}"
        self.name = self.idea.replace(" ", "-")
        for name in ("agents", "config", "skills"):
            shutil.copytree(FACTORY / name, self.tmp / "factory" / name)
        shutil.copytree(FACTORY.parent / ".agents", self.tmp / ".agents")
        kb_dir = self.tmp / "factory/kb"
        kb_dir.mkdir()
        for name in ("schema.json", "global-seed.json"):
            shutil.copy2(FACTORY / "kb" / name, kb_dir / name)
        models = json.loads((self.tmp / "factory/config/models.json").read_text())
        for role in ("planner", "worker", "consultant"):
            models[role]["model"] = f"{role}-model"
        (self.tmp / "factory/config/models.json").write_text(json.dumps(models))

    def tearDown(self):
        shutil.rmtree(self.tmp, ignore_errors=True)

    def siesta(self, *args, scenario="ok", stub=True, timeout=90):
        bin_path = self.tmp / "bin"
        if stub:
            bin_path.mkdir(exist_ok=True)
            fake_pi = bin_path / "pi"
            fake_pi.write_text(STUB)
            fake_pi.chmod(0o755)
        env = os.environ | GIT_ENV | {
            "SIESTA_FACTORY": str(self.tmp / "factory"),
            "PYTHONPATH": str(FACTORY),
            "PATH": f"{bin_path}:{os.environ['PATH']}",
            "FAKE_PI_SCENARIO": scenario,
            "FAKE_PI_LOG": str(self.tmp / "pi_calls.log"),
        }
        return subprocess.run([sys.executable, "-m", "pipeline", *args],
                              capture_output=True, text=True, env=env,
                              cwd=self.tmp, stdin=subprocess.DEVNULL,
                              timeout=timeout)

    def test_cli_saves_and_uses_phase_agent_model_selection(self):
        selection_path = self.tmp / "model-selection.json"
        selection_path.write_text(json.dumps({
            "phases": {"planning": {"model": "planning-phase-model",
                                     "provider": "ollama"}},
            "agents": {"planning": {"planner": {
                "model": "planning-agent-model", "provider": "ollama"}}},
        }))
        result = self.siesta("--auto", "--model-selection", str(selection_path), self.idea)
        self.assertEqual(result.returncode, 0, result.stderr)
        calls = (self.tmp / "pi_calls.log").read_text()
        self.assertIn("--model planning-agent-model", calls)
        self.assertNotIn("--model planning-phase-model", calls)
        saved = json.loads((self.proj() / ".siesta/model-selection.json").read_text())
        self.assertEqual(saved["agents"]["planning"]["planner"]["model"],
                         "planning-agent-model")
        self.assertEqual(saved["role_defaults"]["planner"]["model"], "planner-model")

    def proj(self) -> Path:
        return self.tmp / "factory/projects" / self.name

    def kb(self, path=None) -> dict:
        path = path or f"factory/projects/{self.name}/kb/graph.json"
        return json.loads((self.tmp / path).read_text())

    def types(self, graph=None, type_="blocker"):
        graph = graph or self.kb()
        return [n["summary"] for n in graph["nodes"] if n["type"] == type_]

    def log_count(self, needle):
        log = self.tmp / "pi_calls.log"
        if not log.exists():
            return 0
        return sum(1 for line in log.read_text().splitlines() if needle in line)

    def global_learnings(self, summary: str) -> list:
        nodes = self.kb("factory/kb/global-graph.json")["nodes"]
        return [n for n in nodes if n["type"] == "learning"
                and n["summary"] == summary]

    # ─── happy path ──────────────────────────────────────────────────────

    def test_design_rejection_stops_before_worker_execution(self):
        result = self.siesta('--auto', self.idea, scenario='design_rejected')
        self.assertNotEqual(result.returncode, 0)
        self.assertFalse((self.proj() / 'todo.py').exists())
        self.assertIn('FAIL', (self.proj() / '.siesta/design-review.md').read_text())

    def test_resume_before_planning_preserves_uncommitted_product(self):
        first = self.siesta('--auto', self.idea, scenario='never_spec')
        self.assertNotEqual(first.returncode, 0)
        local = self.proj() / 'local-notes.txt'
        local.write_text('Uncommitted human work')
        resumed = self.siesta('--auto', '--resume', self.idea)
        self.assertNotEqual(resumed.returncode, 0)
        self.assertIn('Uncommitted product changes preserved', resumed.stderr)
        self.assertEqual(local.read_text(), 'Uncommitted human work')
        self.assertFalse((self.proj() / 'spec.md').exists())

    def test_passing_tests_without_requirement_evidence_cannot_complete(self):
        result = self.siesta('--auto', self.idea, scenario='evidence_missing')
        self.assertNotEqual(result.returncode, 0)
        self.assertEqual((self.proj() / 'verify_verdict.txt').read_text().strip(), 'VERIFY_FAILED')
        self.assertFalse(json.loads((self.proj() / '.siesta/requirements.json').read_text())['passed'])

    def test_worker_cannot_weaken_the_reviewed_specification(self):
        result = self.siesta('--auto', self.idea, scenario='rewrite_spec')
        self.assertNotEqual(result.returncode, 0)
        self.assertIn('Return a hello greeting', (self.proj() / 'spec.md').read_text())
        self.assertNotIn('Issue #1 completed', self.decisions())

    def test_active_legacy_verification_requires_new_requirement_evidence(self):
        first = self.siesta('--auto', self.idea)
        self.assertEqual(first.returncode, 0, first.stderr)
        (self.proj() / '.pipeline-checkpoint').write_text('phase-5\n')
        (self.proj() / '.git/siesta-state.json').unlink()
        (self.proj() / '.siesta/requirements.json').unlink()
        result = self.siesta('--auto', '--resume', self.idea, scenario='evidence_missing')
        self.assertNotEqual(result.returncode, 0)
        self.assertEqual((self.proj() / 'verify_verdict.txt').read_text().strip(), 'VERIFY_FAILED')

    def test_verification_cannot_change_the_reviewed_product(self):
        result = self.siesta('--auto', self.idea, scenario='verify_mutates')
        self.assertNotEqual(result.returncode, 0)
        self.assertEqual((self.proj() / 'verify_verdict.txt').read_text().strip(), 'VERIFY_FAILED')
        self.assertNotIn('Project complete:', '\n'.join(self.decisions()))

    def test_source_changed_by_test_child_during_evidence_audit_cannot_complete(self):
        result = self.siesta('--auto', self.idea, scenario='verify_mutates_during_audit')
        self.assertTrue((self.proj() / '.siesta/audit_mutation_done').exists(), result.stderr)
        self.assertIn('return 999', (self.proj() / 'todo.py').read_text())
        self.assertNotEqual(result.returncode, 0)
        self.assertEqual((self.proj() / 'verify_verdict.txt').read_text().strip(), 'VERIFY_FAILED')
        state = json.loads((self.proj() / '.git/siesta-state.json').read_text())
        self.assertNotIn('verified_product', state)
        self.assertNotIn('Project complete:', '\n'.join(self.decisions()))

    def test_failed_completion_commit_can_resume_without_false_claims(self):
        result = self.siesta('--auto', self.idea, scenario='final_commit_fails')
        self.assertNotEqual(result.returncode, 0)
        self.assertNotIn('Project complete:', '\n'.join(self.decisions()))
        (self.proj() / '.git/hooks/commit-msg').unlink()
        resumed = self.siesta('--auto', '--resume', self.idea)
        self.assertEqual(resumed.returncode, 0, resumed.stderr)
        self.assertEqual((self.proj() / '.pipeline-checkpoint').read_text().strip(), 'complete')

    def test_auto_happy_path_completes_every_phase(self):
        result = self.siesta("--auto", self.idea)
        self.assertEqual(result.returncode, 0, result.stderr[-3000:])
        proj = self.proj()
        self.assertTrue((proj / "spec.md").exists())
        # The pipeline saved the spec from the model's text output — the stub
        # planner never writes files, so these documents prove pipeline-side writing.
        self.assertIn("A tiny todo CLI in Python",
                      (proj / "spec.md").read_text())
        self.assertTrue((proj / "issues.md").exists())
        # narration ("# Issues") trimmed: the doc starts at the first issue
        self.assertTrue((proj / "issues.md").read_text().lstrip()
                        .startswith("## Issue #1"))
        self.assertTrue((proj / "issue_1_output.txt").exists())
        self.assertTrue((proj / "issue_2_output.txt").exists())
        self.assertTrue((proj / "learning_issue_1.txt").exists(),
                        "per-issue learning hook should run after each issue")
        proxy_outputs = sorted((proj / ".siesta").glob("proxy-*.txt"))
        self.assertTrue(proxy_outputs)
        self.assertIn("APPROVED", proxy_outputs[-1].read_text())
        verify = (proj / "verify_output.txt").read_text()
        self.assertIn("VERIFY_PASSED", verify)
        self.assertIn("RUNTIME_CHECK: SKIPPED", verify)  # no runnable entry point
        self.assertEqual((proj / ".pipeline-checkpoint").read_text().strip(),
                         "complete")
        # Two issue calls plus verification; final review uses consultants.
        self.assertEqual(self.log_count("--model worker-model"), 3)
        log = (self.tmp / "pi_calls.log").read_text().splitlines()
        learner_calls = [l for l in log if "factory-learner/" in l]
        self.assertEqual(len(learner_calls), 3)
        self.assertTrue(all("--model consultant-model" in l for l in learner_calls))

    def test_happy_path_kb_and_git(self):
        result = self.siesta("--auto", self.idea)
        self.assertEqual(result.returncode, 0, result.stderr[-3000:])
        expected = {"intent": 1, "spec": 1, "issue": 2, "proxy_decision": 1}
        for type_, count in expected.items():
            self.assertEqual(len(self.types(self.kb(), type_)), count,
                             f"expected {count} {type_} nodes")
        # 2 per-issue decisions + the phase-6 "project complete" decision
        self.assertEqual(len(self.types(self.kb(), "decision")), 3)
        self.assertEqual(self.types(self.kb(), "blocker"), [])
        self.assertGreaterEqual(len(self.global_learnings(
            f"Pipeline failure: {self.name}")), 0)  # pollution-free base
        # the learner stub logged a learning to the global KB
        self.assertIn("stub learning", [n["summary"] for n in
                        self.kb("factory/kb/global-graph.json")["nodes"]])
        log = subprocess.run(["git", "-C", str(self.proj()), "log",
                              "--oneline"], capture_output=True,
                             text=True).stdout
        for msg in ("Intent captured", "Spec generated", "Plan generated",
                    "Issue #1: implemented", "Issue #2: implemented",
                    "Project verified"):
            self.assertIn(msg, log)

    # ─── escalation ladder ───────────────────────────────────────────────

    def test_intent_critic_blocks_specification_for_a_new_user_decision(self):
        result = self.siesta("--auto", self.idea, scenario="intent_review_blocked")
        self.assertEqual(result.returncode, 1, result.stderr[-3000:])
        self.assertFalse((self.proj() / "spec.md").exists())
        self.assertIn("Intent review needs user decision", self.types(self.kb(), "blocker"))
        audit = json.loads((self.proj() / ".siesta/intent-review.json").read_text())
        self.assertEqual(audit["status"], "blocked")

    def test_consult_blocks_issue_after_failed_resolution(self):
        result = self.siesta("--auto", self.idea, scenario="always_consult")
        self.assertEqual(result.returncode, 1, result.stderr[-3000:])
        self.assert_incomplete("phase-2")
        proj = self.proj()
        # The ladder runs to fail 3: two GLM resolutions, then deep diagnosis.
        self.assertTrue((proj / "consult_1_output.txt").exists())
        self.assertTrue((proj / "issue_1_retry_output.txt").exists())
        self.assertTrue((proj / "diagnosis_1_output.txt").exists())
        # The diagnosis had no SKIP marker → fed back to the worker → the
        # worker is still stuck → the issue is blocked after diagnosis.
        blockers = self.types(self.kb(), "blocker")
        self.assertIn("Issue #1 blocked after diagnosis", blockers)
        self.assertIn("Issue #2 blocked after diagnosis", blockers)
        # Per issue: initial + 2 resolution retries + 1 diagnosis-feedback
        # retry = 4 worker calls; learn hooks skipped when blocked.
        # Verification adds one worker call; final review uses specialists.
        self.assertEqual(self.log_count("--model worker-model"), 9)
        # Per issue: 2 resolutions + 1 diagnosis = 3 consultant calls,
        # plus the review proxy → 7; the per-issue learn hooks never ran
        # (blocked) and project learning adds 1 → 8.
        self.assertEqual(self.log_count("--model consultant-model"), 14)
        self.assertIn("2 blocked", result.stdout)
        self.assertFalse((proj / "learning_issue_1.txt").exists())

    def test_deep_diagnosis_can_skip_issue(self):
        result = self.siesta("--auto", self.idea, scenario="diagnosis_skips")
        self.assertEqual(result.returncode, 1, result.stderr[-3000:])
        self.assert_incomplete("phase-2")
        proj = self.proj()
        self.assertTrue((proj / "diagnosis_1_output.txt").exists())
        blockers = self.types(self.kb(), "blocker")
        self.assertIn("Issue #1 skipped after diagnosis", blockers)
        self.assertIn("Issue #2 skipped after diagnosis", blockers)
        self.assertFalse((proj / "stop.md").exists())  # SKIP, not CRITICAL
        # Each issue uses three workers; verification adds one. Specialists
        # and the proxy use the consultant route.
        self.assertEqual(self.log_count("--model worker-model"), 7)
        self.assertEqual(self.log_count("--model consultant-model"), 14)
        self.assertIn("2 blocked", result.stdout)

    def test_single_consultation_recovers_issue(self):
        result = self.siesta("--auto", self.idea, scenario="consult_once")
        self.assertEqual(result.returncode, 0, result.stderr[-3000:])
        proj = self.proj()
        self.assertTrue((proj / "consult_1_output.txt").exists())
        # GLM's guidance recovered the worker on the first fed-back retry:
        # no blocker, no diagnosis, issue decisions recorded.
        self.assertEqual(self.types(self.kb(), "blocker"), [])
        self.assertFalse((proj / "diagnosis_1_output.txt").exists())
        self.assertEqual(len(self.types(self.kb(), "decision")), 3)
        self.assertIn("0 blocked", result.stdout)
        # Two issue retries plus verification; final review uses consultants.
        self.assertEqual(self.log_count("--model worker-model"), 5)
        # Issue guidance, one per-issue reviewer, final specialists and proxy,
        # and learnings.
        self.assertEqual(self.log_count("--model consultant-model"), 15)
        # recovered issues DO get the per-issue learning hook
        self.assertTrue((proj / "learning_issue_1.txt").exists())

    def test_preexisting_stop_md_halts_cleanly(self):
        proj = self.proj()
        proj.mkdir(parents=True)
        (proj / "stop.md").write_text("manual halt for test")
        result = self.siesta("--auto", self.idea)
        self.assertEqual(result.returncode, 0, result.stderr[-3000:])
        self.assertFalse((proj / '.pipeline-checkpoint').exists())
        self.assertFalse((proj / 'kb/graph.json').exists())
        self.assertEqual(self.log_count('--model'), 0)

    def test_persistent_proxy_requests_stay_blocked(self):
        for scenario in ("proxy_request", "proxy_hang"):
            with self.subTest(scenario=scenario):
                result = self.siesta("--auto", self.idea, scenario=scenario)
                self.assertEqual(result.returncode, 1, result.stderr[-3000:])
                self.assert_incomplete("phase-2")
                self.assertIn("APPROVED", (self.proj() / "proxy_1_output.txt").read_text())
                self.assertNotIn("Issue #1 completed", self.decisions())
                self.assertNotIn("Issue #2 completed", self.decisions())
                self.assertFalse((self.proj() / "todo.py").exists())
                self.assertIn("2 blocked", result.stdout)

    def test_proxy_approval_still_implements_the_issue(self):
        # #58: APPROVED used to mean "continue" with no worker re-invocation
        # — the issue was marked completed on a bare PROXY_REQUEST and
        # nothing was ever implemented. The worker MUST run again with
        # the approval fed back.
        result = self.siesta("--auto", self.idea,
                             scenario="proxy_approved_implements")
        self.assertEqual(result.returncode, 0, result.stderr[-3000:])
        self.assertEqual(self.types(self.kb(), "blocker"), [])
        self.assertIn("Issue #1 completed", self.decisions())
        # the completion node records the IMPLEMENTATION, not the request
        first = next(n for n in self.kb()["nodes"]
                     if n["summary"] == "Issue #1 completed")
        self.assertIn("implemented the issue", first["detail"])
        # each issue: PROXY attempt + post-approval implementation = 2
        self.assertGreaterEqual(self.log_count("--model worker-model"), 4)

    # ─── degenerate-output guard (#2) ────────────────────────────────────

    def decisions(self):
        return self.types(self.kb(), "decision")

    def assert_incomplete(self, checkpoint):
        self.assertEqual((self.proj() / ".pipeline-checkpoint").read_text().strip(),
                         checkpoint)
        self.assertFalse(any(summary.startswith("Project complete:")
                             for summary in self.decisions()))

    def test_degenerate_worker_output_blocked_not_faked(self):
        result = self.siesta("--auto", self.idea, scenario="degenerate_always")
        self.assertEqual(result.returncode, 1, result.stderr[-3000:])
        self.assert_incomplete("phase-2")
        blockers = self.types(self.kb(), "blocker")
        self.assertIn("Issue #1 degenerate output", blockers)
        self.assertIn("Issue #2 degenerate output", blockers)
        # the #2 regression: garbage output must NOT become a completion
        self.assertNotIn("Issue #1 completed", self.decisions())
        self.assertFalse((self.proj() / "learning_issue_1.txt").exists())
        self.assertIn("2 blocked", result.stdout)
        # per issue: initial + 1 degenerate feedback retry = 2 worker calls,
        # no learn hooks when blocked → 4, plus verification; review uses consultants.
        self.assertEqual(self.log_count("--model worker-model"), 5)

    def test_blocked_issue_leaves_no_tree_residue(self):
        # #49: a blocked issue's uncommitted work is discarded — the tree
        # must match the last commit (untracked run evidence excepted)
        result = self.siesta("--auto", self.idea, scenario="degenerate_always")
        self.assertEqual(result.returncode, 1, result.stderr[-3000:])
        self.assert_incomplete("phase-2")
        status = subprocess.run(["git", "-C", str(self.proj()),
                                 "status", "--porcelain"],
                                capture_output=True, text=True).stdout
        dirty = [ln for ln in status.splitlines()
                 if ln and not ln.startswith("??") and not ln[3:].startswith("kb/")]
        # Failure learning may append KB evidence after the product commit.
        self.assertEqual(dirty, [],
                         "blocked issues must not leave committed-file "
                         "residue (the pomodoro-#3 shape)")

    def test_degenerate_once_recovers_with_feedback(self):
        result = self.siesta("--auto", self.idea, scenario="degenerate_once")
        self.assertEqual(result.returncode, 0, result.stderr[-3000:])
        self.assertEqual(self.types(self.kb(), "blocker"), [])
        self.assertIn("Issue #1 completed", self.decisions())
        self.assertIn("0 blocked", result.stdout)
        self.assertTrue((self.proj() / "learning_issue_1.txt").exists())

    # ─── regression gating (#15) ─────────────────────────────────────────

    def test_failing_regression_gates_the_next_issue(self):
        self.siesta_hybrid_repair_project()
        proj = self.proj()
        result = self.siesta("--auto", self.idea)
        self.assertEqual(result.returncode, 1, result.stderr[-3000:])
        self.assert_incomplete("phase-2")
        blockers = self.types(self.kb(), "blocker")
        self.assertIn("Regression failure before issue #2", blockers)
        # #15: the issue after a red suite is skipped, not built
        self.assertIn("1 blocked", result.stdout)
        self.assertFalse((proj / "issue_2_output.txt").exists())
        self.assertNotIn("Issue #2 completed", self.decisions())

    # ─── regression repair ladder (#44) ─────────────────────────────────

    def test_red_suite_gets_one_worker_repair_then_continues(self):
        # #44: a red suite is repaired by the worker when it can be —
        # the repair pass runs BEFORE the issue, and the issue still executes
        self.siesta_hybrid_repair_project()
        result = self.siesta("--auto", self.idea, scenario="repair_regression")
        self.assertEqual(result.returncode, 0, result.stderr[-3000:])
        proj = self.proj()
        self.assertTrue((proj / "regression_repair_2.txt").exists())
        self.assertIn("Regression repaired", result.stderr)
        # the gated issue still executed (not skipped)
        self.assertIn("Issue #2 completed", self.decisions())
        self.assertIn("0 blocked", result.stdout)
        self.assertEqual(self.types(self.kb(), "blocker"), [])
        # repair call carried the debugging skill and the red suite output
        repair_calls = [l for l in (self.tmp / "pi_calls.log").read_text()
                        .splitlines() if "egression suite is RED" in l]
        self.assertEqual(len(repair_calls), 1)

    def test_unrepairable_suite_skips_issue_with_honest_blocker(self):
        # This repair response writes no files and leaves the suite red.
        self.siesta_hybrid_repair_project()
        result = self.siesta("--auto", self.idea, scenario="repair_fails_forever")
        self.assertEqual(result.returncode, 1, result.stderr[-3000:])
        self.assert_incomplete("phase-2")
        proj = self.proj()
        self.assertTrue((proj / "regression_repair_2.txt").exists())
        blockers = self.types(self.kb(), "blocker")
        self.assertIn("Regression failure before issue #2", blockers)
        # honest blocker: names the repair artifacts, not just the log
        blocker = next(b for b in self.kb()["nodes"]
                       if b["summary"] == "Regression failure before issue #2")
        self.assertIn("repair attempt", blocker["detail"])
        self.assertIn("1 blocked", result.stdout)
        self.assertNotIn("Issue #2 completed", self.decisions())

    def test_two_unrepairable_suites_halt_phase3(self):
        # circuit breaker: two consecutive unrepairable red suites stop the
        # pipeline honestly instead of skipping every remaining issue
        self.siesta_hybrid_repair_project(issue_count=3)
        result = self.siesta("--auto", self.idea,
                             scenario="repair_fails_forever_3")
        self.assertEqual(result.returncode, 1, result.stderr[-3000:])
        self.assertIn("halting phase 3", result.stderr)
        blockers = self.types(self.kb(), "blocker")
        self.assertIn("Phase 3 halted: unrepairable suite", blockers)
        # global KB also learns the failure (the failure trap)
        self.assertEqual(len(self.global_learnings(
            f"Pipeline failure: {self.name}")), 1)

    def siesta_hybrid_repair_project(self, issue_count=2):
        """Committed red base with issue #1 done and later work pending."""
        from pipeline.kb import Graph
        result = self.siesta("--auto", self.idea)
        self.assertEqual(result.returncode, 0, result.stderr[-3000:])
        proj = self.proj()
        graph_path = proj / "kb/graph.json"
        graph = json.loads(graph_path.read_text())
        removed = {n["id"] for n in graph["nodes"]
                   if n["summary"] == "Issue #2 completed"
                   or n["summary"].startswith("Project complete:")}
        graph["nodes"] = [n for n in graph["nodes"] if n["id"] not in removed]
        graph["edges"] = [e for e in graph["edges"]
                          if e["from"] not in removed and e["to"] not in removed]
        graph_path.write_text(json.dumps(graph))
        if issue_count == 3:
            with (proj / "issues.md").open("a") as stream:
                stream.write("\n## Issue #3: Add more\nWrite more.\n"
                             "Test strategy: Assert the additional output.\n"
                             "Dependencies: #2.\n")
            Graph(graph_path).node("issue", "Issue #3: Add more", "Write more")
        (proj / "pyproject.toml").write_text("[project]\nname = 'stub'\n")
        tests = proj / "tests"
        tests.mkdir()
        (tests / "test_broken.py").write_text(
            "def test_broken():\n    assert False, 'previous issue broke me'\n")
        (proj / ".pipeline-checkpoint").write_text("phase-2\n")
        (proj / "issue_2_output.txt").unlink()
        subprocess.run(["git", "add", "-A"], cwd=proj, check=True, capture_output=True)
        subprocess.run(["git", "commit", "-qm", "Fixture: preserve broken committed base"],
                       cwd=proj, check=True, capture_output=True, env=os.environ | GIT_ENV)
        (self.tmp / "pi_calls.log").write_text("")

    # ─── explicit-approval gates (#3) ─────────────────────────────────────

    def test_unapproved_proxy_feedback_retries_issue(self):
        # #3: hesitation is not approval — the worker gets feedback and retries
        result = self.siesta("--auto", self.idea, scenario="proxy_no_marker")
        self.assertEqual(result.returncode, 0, result.stderr[-3000:])
        self.assertEqual(self.types(self.kb(), "blocker"), [])
        self.assertIn("Issue #1 completed", self.decisions())
        self.assertNotIn("did not approve", result.stderr)  # recovered quietly
        # per issue: PROXY attempt + 1 feedback retry = 2 worker calls; then
        # review + verify = 2 (learn hooks are consultant calls since #46)
        self.assertEqual(self.log_count("--model worker-model"), 5)
        # 2 issue-level proxies + 2 per-issue reviews + final review proxy
        # and specialists + 2 per-issue learnings + project learning.
        self.assertEqual(self.log_count("--model consultant-model"), 15)

    def test_proxy_rejection_retries_with_different_approach(self):
        result = self.siesta("--auto", self.idea, scenario="proxy_rejected")
        self.assertEqual(result.returncode, 0, result.stderr[-3000:])
        self.assertIn("REJECTED", (self.proj() / "proxy_1_output.txt").read_text())
        self.assertEqual(self.types(self.kb(), "blocker"), [])
        self.assertIn("Issue #1 completed", self.decisions())
        self.assertEqual(self.log_count("--model consultant-model"), 15)

    # ─── review revision now applies fixes (#16/#18) ─────────────────────

    def test_review_revision_applies_fixes_with_tools(self):
        result = self.siesta("--auto", self.idea, scenario="review_needs_revision")
        self.assertEqual(result.returncode, 1, result.stderr[-3000:])
        self.assert_incomplete("phase-3")
        self.assertIn("Review not approved", self.types(self.kb(), "blocker"))
        # #16: the fix pass runs WITH write tools and its changes are committed
        fix_calls = [line for line in (self.tmp / "pi_calls.log").read_text()
                     .splitlines() if "Fix review issues" in line]
        self.assertEqual(len(fix_calls), 2)
        self.assertNotIn("--no-tools", fix_calls[0])
        log = subprocess.run(["git", "-C", str(self.proj()), "log", "--oneline"],
                             capture_output=True, text=True).stdout
        self.assertIn("Review fixes", log)
        proxy_outputs = sorted((self.proj() / ".siesta").glob("proxy-*.txt"))
        self.assertTrue(proxy_outputs)
        self.assertIn("NEEDS_REVISION", proxy_outputs[-1].read_text())

    def test_degenerate_review_never_reaches_the_proxy(self):
        # #41: tool-JSON review output is not a verdict — the proxy must
        # never judge on it. The #16 fix pass runs instead, with tools.
        result = self.siesta("--auto", self.idea, scenario="review_degenerate")
        self.assertEqual(result.returncode, 1, result.stderr[-3000:])
        self.assert_incomplete("phase-3")
        self.assertIn("Review not approved", self.types(self.kb(), "blocker"))
        # the proxy was never consulted for review approval
        self.assertFalse(list((self.proj() / ".siesta").glob("proxy-*.txt")))
        log = (self.tmp / "pi_calls.log").read_text().splitlines()
        self.assertEqual(len([l for l in log
                               if "Evaluate if this review meets" in l]), 0)
        # Invalid structured reports exhaust the review retry before the proxy or a repair.
        review_calls = [l for l in log if "Fix review issues" in l]
        self.assertEqual(len(review_calls), 0)
        call_records = [json.loads(line) for line in
                        (self.proj() / ".siesta/calls.jsonl").read_text().splitlines()]
        self.assertEqual(sum(record["agent"] == "integration-reviewer"
                             for record in call_records), 4)
        self.assertEqual(sum(record["agent"] == "quality-reviewer"
                             for record in call_records), 0)
        self.assertFalse((self.proj() / "review_fixes_output.txt").exists())
        self.assertFalse((self.proj() / "verify_verdict.txt").exists())

    def test_fenced_verify_marker_is_not_a_verdict(self):
        # round-7 hardening: a VERIFY_PASSED quoted inside a code fence is
        # an example, not a verdict — the marker gate matches fence-free.
        result = self.siesta("--auto", self.idea, scenario="verify_fenced")
        self.assertEqual(result.returncode, 1, result.stderr[-3000:])
        self.assert_incomplete("phase-4")
        self.assertEqual((self.proj() / "verify_verdict.txt").read_text().strip(),
                         "VERIFY_FAILED")
        self.assertTrue(any("Project NOT verified" in b
                            for b in self.types(self.kb(), "blocker")))

    # ─── verify verdict tells the truth (#6) ─────────────────────────────

    def test_failed_verify_is_recorded_as_unverified(self):
        result = self.siesta("--auto", self.idea, scenario="verify_fails")
        self.assertEqual(result.returncode, 1, result.stderr[-3000:])
        self.assert_incomplete("phase-4")
        self.assertTrue(any("Project NOT verified" in b
                            for b in self.types(self.kb(), "blocker")))
        self.assertEqual((self.proj() / "verify_verdict.txt").read_text().strip(),
                         "VERIFY_FAILED")
        log = subprocess.run(["git", "-C", str(self.proj()), "log", "--oneline"],
                             capture_output=True, text=True).stdout
        self.assertIn("UNVERIFIED", log)
        self.assertNotIn("Project verified", log)
        # Completed issues survive, but failed verification stays resumable.
        self.assertIn("Issue #1 completed", self.decisions())
        (self.tmp / "pi_calls.log").write_text("")
        recovered = self.siesta("--auto", self.idea)
        self.assertEqual(recovered.returncode, 0, recovered.stderr[-3000:])
        self.assertEqual(self.log_count("skills/issue-executor/"), 0)
        self.assertIn("QA engineer", (self.tmp / "pi_calls.log").read_text())
        self.assertEqual((self.proj() / "verify_verdict.txt").read_text().strip(),
                         "VERIFY_PASSED")

    # ─── resume ──────────────────────────────────────────────────────────

    def test_legacy_complete_checkpoint_retries_failed_verification(self):
        first = self.siesta("--auto", self.idea, scenario="verify_fails")
        self.assertEqual(first.returncode, 1, first.stderr[-3000:])
        # Older runs closed the checkpoint even when verification failed.
        (self.proj() / ".pipeline-checkpoint").write_text("complete\n")
        (self.tmp / "pi_calls.log").write_text("")
        result = self.siesta("--auto", self.idea)
        self.assertEqual(result.returncode, 0, result.stderr[-3000:])
        self.assertEqual(self.log_count("skills/issue-executor/"), 0)
        self.assertEqual(self.log_count("QA engineer"), 1)
        self.assertEqual((self.proj() / "verify_verdict.txt").read_text().strip(),
                         "VERIFY_PASSED")
        self.assertEqual((self.proj() / ".pipeline-checkpoint").read_text().strip(),
                         "complete")

    def test_resume_skips_completed_issues(self):
        # #9: a resume must not re-run issues whose completion node is on disk
        self.siesta("--auto", self.idea)
        (self.proj() / ".pipeline-checkpoint").write_text("phase-2\n")
        (self.tmp / "pi_calls.log").write_text("")
        result = self.siesta("--auto", self.idea, scenario="always_consult")
        self.assertEqual(result.returncode, 0, result.stderr[-3000:])
        # no issue-executor skill calls: both completed issues were skipped
        # (the path form only — the learner prompts also list the name)
        self.assertEqual(self.log_count("skills/issue-executor/"), 0)
        # The same-version specialist approval is reused; design and project
        # learning remain in this resumed call sequence.
        self.assertEqual(self.log_count("consultant-model"), 2)
        self.assertIn("0 blocked", result.stdout)
        self.assertEqual((self.proj() / ".pipeline-checkpoint").read_text().strip(),
                         "complete")

    def test_resume_reports_blocked_issues_from_kb(self):
        # Reconstruct pending issues from KB, retry them and outrank stale blockers.
        first = self.siesta("--auto", self.idea, scenario="always_consult")
        self.assertEqual(first.returncode, 1, first.stderr[-3000:])
        self.assertIn("2 blocked", first.stdout)
        self.assert_incomplete("phase-2")
        (self.tmp / "pi_calls.log").write_text("")
        second = self.siesta("--auto", self.idea)
        self.assertEqual(second.returncode, 0, second.stderr[-3000:])
        self.assertIn("0 blocked", second.stdout)
        self.assertNotIn("Blocked issues: #1, #2", second.stderr)
        self.assertIn("Issue #1 completed", self.decisions())
        self.assertIn("Issue #2 completed", self.decisions())
        self.assertEqual(self.log_count("skills/issue-executor/"), 2)
        self.assertIn("return \"hello\"", (self.proj() / "todo.py").read_text())

    def test_resume_says_resuming_not_creating(self):
        # #51: the slug maps the same idea to the same dir every time, so a
        # relaunch is silently a resume — the operator can't tell fresh
        # from resume while the log still says "Creating project".
        self.siesta("--auto", self.idea)
        result = self.siesta("--auto", self.idea)
        self.assertEqual(result.returncode, 0, result.stderr[-3000:])
        self.assertNotIn("Creating project", result.stderr)
        self.assertIn("Resuming project", result.stderr)
        # a genuinely fresh idea still says "Creating"
        fresh = self.siesta("--auto", self.idea + " and a tail")
        self.assertIn("Creating project", fresh.stderr)

    def test_different_idea_with_same_slug_dies_loudly(self):
        # #56: two DIFFERENT ideas sharing a >40-char prefix slug-map to
        # the same dir — the newer idea used to silently resume the older
        # project (tempconv/guessgame collision, live 2026-09-10).
        from pipeline.__main__ import slug
        prefix = "build a tiny todo cli with a very long shared prefix"
        idea_a = f"{prefix} alpha variant"
        idea_b = f"{prefix} beta variant"
        self.assertEqual(slug(idea_a), slug(idea_b))
        self.siesta("--auto", idea_a)
        collide = self.siesta("--auto", idea_b)
        self.assertNotEqual(collide.returncode, 0)
        self.assertIn("DIFFERENT idea", collide.stderr)
        # the original idea still resumes cleanly (no worker calls)
        (self.tmp / "pi_calls.log").write_text("")
        again = self.siesta("--auto", idea_a)
        self.assertEqual(again.returncode, 0, again.stderr[-3000:])
        self.assertEqual(self.log_count("--model worker-model"), 0)

    def test_relaunch_of_completed_project_does_not_duplicate(self):
        # #57: checkpoint complete → phases 6-7 re-ran on every relaunch:
        # a duplicate "Project verified" commit and duplicate project-level
        # learnings landed in the project git history and the global KB.
        first = self.siesta("--auto", self.idea)
        self.assertEqual(first.returncode, 0, first.stderr[-3000:])
        proj = self.proj()
        one = subprocess.run(["git", "-C", str(proj), "log", "--oneline"],
                             capture_output=True, text=True).stdout
        self.assertEqual(one.count("Project verified"), 1)
        gkb_nodes = len(self.kb("factory/kb/global-graph.json")["nodes"])
        (self.tmp / "pi_calls.log").write_text("")
        second = self.siesta("--auto", self.idea)
        self.assertEqual(second.returncode, 0, second.stderr[-3000:])
        two = subprocess.run(["git", "-C", str(proj), "log", "--oneline"],
                             capture_output=True, text=True).stdout
        self.assertEqual(two.count("Project verified"), 1)
        self.assertEqual(
            len(self.kb("factory/kb/global-graph.json")["nodes"]), gkb_nodes)
        self.assertIn("already complete", second.stderr)

    def test_generated_project_has_hygiene_gitignore(self):
        # #7: `git add -A` must not commit .DS_Store/__pycache__/checkpoint
        self.siesta("--auto", self.idea)
        proj = self.proj()
        self.assertIn("__pycache__/", (proj / ".gitignore").read_text())
        files = subprocess.run(["git", "-C", str(proj), "ls-files"],
                               capture_output=True, text=True).stdout
        self.assertNotIn(".pipeline-checkpoint", files)

    def test_pipeline_artifacts_stay_out_of_project_commits(self):
        # #38: run evidence (outputs, regression logs, pre-issue contexts,
        # learning transcripts) is not product — `git add -A` must not
        # commit it. The files stay on disk for the learner's inputs.
        self.siesta("--auto", self.idea)
        files = subprocess.run(["git", "-C", str(self.proj()), "ls-files"],
                              capture_output=True, text=True).stdout
        for evidence in ("_output.txt", "regression_", "pre_issue_",
                         "learning_issue_", "project_learning"):
            self.assertNotIn(evidence, files, f"committed artifact: {evidence}")
        # the evidence is still on disk — learn.py reads these as inputs
        proj = self.proj()
        self.assertTrue((proj / "issue_1_output.txt").exists())
        self.assertTrue((proj / "pre_issue_1.json").exists())
        # the product itself stays committed
        self.assertIn("spec.md", files)
        self.assertIn("issues.md", files)

    def test_resume_from_phase_2_skips_interview_and_spec(self):
        self.siesta("--auto", self.idea)
        (self.proj() / ".pipeline-checkpoint").write_text("phase-2\n")
        (self.tmp / "pi_calls.log").write_text("")
        result = self.siesta("--auto", self.idea)
        self.assertEqual(result.returncode, 0, result.stderr[-3000:])
        # the regression: phases 0 and 1 must NOT re-run (bash re-interviewed)
        self.assertEqual(self.log_count("interview-me"), 0)
        self.assertEqual(self.log_count("spec-driven-development"), 0)
        # Verification runs; final review remains approved for this exact
        # product and configuration.
        self.assertGreaterEqual(self.log_count("--model worker-model"), 1)
        self.assertEqual((self.proj() / ".pipeline-checkpoint")
                         .read_text().strip(), "complete")

    # ─── failure learning ────────────────────────────────────────────────

    def test_spec_failure_logs_blocker_and_learning(self):
        result = self.siesta("--auto", self.idea, scenario="never_spec")
        self.assertEqual(result.returncode, 1)
        self.assertIn("Spec generation failed", result.stderr)
        self.assertIn("Pipeline failed", self.types(self.kb(), "blocker"))
        found = self.global_learnings(f"Pipeline failure: {self.name}")
        self.assertEqual(len(found), 1)

    def test_missing_pi_binary_still_learns(self):
        result = self.siesta("--auto", self.idea, stub=False)
        self.assertEqual(result.returncode, 1)
        self.assertIn("Pipeline failed", self.types(self.kb(), "blocker"))
        found = self.global_learnings(f"Pipeline failure: {self.name}")
        self.assertEqual(len(found), 1)


class RuntimeSmoke(unittest.TestCase):
    def smoke(self, files: dict) -> tuple[str, str]:
        with tempfile.TemporaryDirectory() as d:
            for name, content in files.items():
                p = Path(d, name)
                p.parent.mkdir(parents=True, exist_ok=True)
                p.write_text(content)
            return phases.runtime_smoke(Path(d))

    def test_static_site_is_served_and_probed(self):
        status, detail = self.smoke({"index.html": "<h1>hi</h1>"})
        self.assertEqual(status, "PASSED", detail)
        self.assertIn("127.0.0.1", detail)

    def test_crashing_entry_point_fails(self):
        status, detail = self.smoke({"main.py": "raise SystemExit(3)"})
        self.assertEqual(status, "FAILED", detail)
        self.assertIn("exited", detail)

    def test_no_entry_point_skips(self):
        status, detail = self.smoke({"notes.txt": "nothing runnable"})
        self.assertEqual(status, "SKIPPED", detail)

    def test_package_with_dunder_main_runs(self):
        # #4: `python -m <pkg>` entry points are detected and run
        status, detail = self.smoke({
            "pyproject.toml": "[project]\nname = 'pkg'\n",
            "pkg/__main__.py": "print('hello from the package')",
        })
        self.assertEqual(status, "PASSED", detail)
        self.assertIn("exited cleanly", detail)

    def test_cli_exiting_zero_is_success(self):
        # #19: a working CLI counts as PASSED, not "process exited with code 0"
        status, detail = self.smoke({"main.py": "print('done')"})
        self.assertEqual(status, "PASSED", detail)
        self.assertIn("exited cleanly", detail)


class RootLevelSuiteVerifyFallback(unittest.TestCase):
    """#50: verify's regression fallback must see a root-level suite —
    the pomodoro layout has no tests/ dir and no manifest."""

    def setUp(self):
        self.tmp = Path(tempfile.mkdtemp(prefix="siesta-int-"))
        self.idea = f"build a tiny root-tested cli {uuid4().hex[:6]}"
        self.name = self.idea.replace(" ", "-")
        for name in ("agents", "config", "skills"):
            shutil.copytree(FACTORY / name, self.tmp / "factory" / name)
        shutil.copytree(FACTORY.parent / ".agents", self.tmp / ".agents")
        kb_dir = self.tmp / "factory/kb"
        kb_dir.mkdir()
        for name in ("schema.json", "global-seed.json"):
            shutil.copy2(FACTORY / "kb" / name, kb_dir / name)
        models = json.loads((self.tmp / "factory/config/models.json").read_text())
        for role in ("planner", "worker", "consultant"):
            models[role]["model"] = f"{role}-model"
        (self.tmp / "factory/config/models.json").write_text(json.dumps(models))

    def tearDown(self):
        shutil.rmtree(self.tmp, ignore_errors=True)

    def siesta(self, *args, scenario="ok", timeout=90):
        bin_path = self.tmp / "bin"
        bin_path.mkdir(exist_ok=True)
        fake_pi = bin_path / "pi"
        fake_pi.write_text(STUB)
        fake_pi.chmod(0o755)
        env = os.environ | GIT_ENV | {
            "SIESTA_FACTORY": str(self.tmp / "factory"),
            "PYTHONPATH": str(FACTORY),
            "PATH": f"{bin_path}:{os.environ['PATH']}",
            "FAKE_PI_SCENARIO": scenario,
            "FAKE_PI_LOG": str(self.tmp / "pi_calls.log"),
        }
        return subprocess.run([sys.executable, "-m", "pipeline", *args],
                              capture_output=True, text=True, env=env,
                              cwd=self.tmp, stdin=subprocess.DEVNULL,
                              timeout=timeout)

    def proj(self) -> Path:
        return self.tmp / "factory/projects" / self.name

    def test_root_level_suite_drives_the_verify_fallback(self):
        # pre-seed the pomodoro shape: tests at the root, no tests/ dir,
        # no manifest — then degenerate verify output forces the fallback
        proj = self.proj()
        proj.mkdir(parents=True)
        (proj / "app.py").write_text("def add(a, b):\n    return a + b\n")
        (proj / "test_app.py").write_text(
            "from app import add\n\ndef test_add():\n    assert add(1, 2) == 3\n")
        # the stub's QA engineer answers VERIFY_PASSED unless told otherwise;
        # scenario=verify_fails is the wrong direction, so drive the
        # degenerate path with a QA-verbatim degenerate output instead
        result = self.siesta("--auto", self.idea, scenario="verify_degenerate")
        self.assertEqual(result.returncode, 0, result.stderr[-3000:])
        verdict = (proj / "verify_verdict.txt").read_text().strip()
        # a real passing root suite + no runnable smoke = VERIFY_PASSED
        # (before #50: VERIFY_FAILED — the gate was blind to root tests)
        self.assertEqual(verdict, "VERIFY_PASSED")
        self.assertIn("Running regression suite (.)", result.stderr)


if __name__ == "__main__":
    unittest.main()
