"""Run solver scenarios in a fresh process: earlier solves must not poison later ones."""
import json
import subprocess
import sys


def test_proof_scenarios_work_when_the_lp_initializes_scipy_first():
    result = subprocess.run([sys.executable, "-c", """
import json
from concurrent.futures import ThreadPoolExecutor
from scp.scenarios import BY_ID, EngineClient
def run(sid):
    report = BY_ID[sid].execute(EngineClient())
    return {'id': sid, 'ok': report.ok, 'failed': report.failed,
            'errors': [s.error for s in report.steps if s.error]}
with ThreadPoolExecutor(1) as worker:
    reports = list(worker.map(run, ['s3-bikes', 's5-paints', 's9-generated']))
print(json.dumps(reports))
"""], capture_output=True, text=True, timeout=180, check=True)
    reports = json.loads(result.stdout.splitlines()[-1])
    assert all(r["ok"] for r in reports), reports
