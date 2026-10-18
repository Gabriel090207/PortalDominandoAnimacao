"""Bounded test-only runner/pytest recorder. No production SDK initialization.

Run from Backend with explicitly guarded emulator environment. Saves only the
whitelisted synthetic diagnostic attached by the concurrent test, never stdout,
raw exception messages, locals, cookies, hashes or complete documents.
"""
import argparse
import re
import json
import os
from pathlib import Path
import subprocess
import sys
import tempfile
import time

NODE='tests/emulator/test_admin_activation_integration.py::test_concurrent_activation_one_transition_one_audit'


def pytest_runtest_logreport(report):
    if report.when!='call' or report.nodeid.split('::')[-1]!=NODE.split('::')[-1]:return
    diagnostic=next((value for key,value in report.user_properties if key=='activation_diagnostic'),None)
    target=os.environ.get('ADMIN_ACTIVATION_DIAGNOSTIC_PATH')
    if target:
        Path(target).write_text(json.dumps({'outcome':report.outcome,'duration':round(report.duration,3),
            'diagnostic':diagnostic},ensure_ascii=True),encoding='utf-8')


def main():
    parser=argparse.ArgumentParser(description='Bounded local demo activation test only.')
    parser.add_argument('--output-name',default='activation_stress_results.jsonl')
    parser.add_argument('--max-seconds',type=int,default=540)
    args=parser.parse_args()
    if not re.fullmatch(r'[A-Za-z0-9_-]+\.jsonl',args.output_name) or not 1<=args.max_seconds<=540:
        parser.error('A simple JSONL filename and a budget of 1..540 seconds are required.')
    from emulator_support import configured_emulator
    configured_emulator()  # exact loopback + fixed demo BEFORE starting tests
    backend=Path(__file__).resolve().parents[1]
    output=backend/'tests'/args.output_name
    if output.exists():raise SystemExit('Diagnostic output exists; preserve it before a new run.')
    started=time.monotonic()
    with tempfile.TemporaryDirectory(prefix='admin62-') as temp:
        for number in range(1,100):  # reserve one concurrent execution for regression
            remaining=args.max_seconds-(time.monotonic()-started)
            if remaining<=0:break
            target=Path(temp)/'current.json'
            if target.exists():target.unlink()
            env=dict(os.environ,ADMIN_ACTIVATION_DIAGNOSTIC_PATH=str(target))
            env['PYTHONPATH']=str(backend/'tests')+os.pathsep+str(backend)
            before=time.monotonic()
            try:
                completed=subprocess.run([sys.executable,'-m','pytest','-p','activation_stress_probe',
                    '--run-firestore-emulator','-q',NODE],cwd=backend,env=env,capture_output=True,
                    timeout=remaining,check=False)
                captured=json.loads(target.read_text()) if target.exists() else {'outcome':'UNKNOWN','diagnostic':None}
                row={'run':number,'exit_code':completed.returncode,'wall_seconds':round(time.monotonic()-before,3),**captured}
            except subprocess.TimeoutExpired:
                row={'run':number,'outcome':'BUDGET_EXHAUSTED','wall_seconds':round(time.monotonic()-before,3),'diagnostic':None}
            with output.open('a',encoding='utf-8') as stream:
                stream.write(json.dumps(row,ensure_ascii=True)+'\n')
            print(json.dumps(row,ensure_ascii=True),flush=True)
            if row['outcome']=='BUDGET_EXHAUSTED':break
    print(json.dumps({'total_seconds':round(time.monotonic()-started,3),'output':str(output)}),flush=True)


if __name__=='__main__':main()
