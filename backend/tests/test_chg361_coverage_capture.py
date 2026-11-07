"""Native measurement infrastructure; never claims application acceptance."""
from pathlib import Path
import os
import signal
import subprocess
import sys
import tempfile
import time

import coverage

ROOT=Path(__file__).resolve().parents[1]
sys.path.insert(0,str(ROOT/'scripts'))
from chg361_coverage import configuration


def test_real_parent_child_and_signals_preserve_independent_counters():
    with tempfile.TemporaryDirectory(prefix='chg361-python-capture-') as directory:
        private=Path(directory);output=private/'counters';output.mkdir(mode=0o700)
        config=private/'coverage.ini';config.write_text(configuration(ROOT,output))
        ready=private/'ready'
        child="from app.core.errors import AppError; e=AppError('child','child',status_code=409); assert e.status_code==409"
        driver=private/'actual-process.py'
        driver.write_text('import subprocess,sys,time\nfrom pathlib import Path\nfrom app.core.errors import AppError\n'
            +"assert AppError('parent','parent').status_code==400\n"
            +'subprocess.run([sys.executable,"-c",'+repr(child)+'],check=True)\n'
            +'Path('+repr(str(ready))+').write_text("ready")\n'
            +'while True:time.sleep(0.1)\n')
        # Runtime images deliberately exclude coverage; preserve the separately
        # mounted, pinned tool path for the genuine child interpreter.
        # This child owns an independent tracer. Inheriting the enclosing
        # suite's serialized startup config creates two SIGTERM handlers.
        env=dict({key:value for key,value in os.environ.items() if not key.startswith(('COVERAGE_', 'COV_CORE_'))},
            PYTHONPATH=os.pathsep.join([str(ROOT),*filter(None,os.environ.get('PYTHONPATH','').split(os.pathsep))]),
            COVERAGE_FILE=str(output/'.coverage'))
        log=private/'process.log'
        with log.open('w') as stream:
            process=subprocess.Popen([sys.executable,'-B','-m','coverage','run','--rcfile='+str(config),
                '--context=actual-process-proof','--save-signal=USR2',str(driver)],cwd=ROOT,env=env,
                stdout=stream,stderr=subprocess.STDOUT)
            try:
                deadline=time.monotonic()+15
                while not ready.exists():
                    assert process.poll() is None and time.monotonic()<deadline,log.read_text()[-2000:]
                    time.sleep(.05)
                process.send_signal(signal.SIGUSR2)
                while len(list(output.glob('.coverage.*')))<2:
                    assert process.poll() is None and time.monotonic()<deadline,'save_signal_must_write_parent_and_child'
                    time.sleep(.05)
                process.send_signal(signal.SIGTERM);code=process.wait(timeout=5)
                assert code==-signal.SIGTERM
            finally:
                if process.poll() is None:
                    process.kill();process.wait(timeout=5)
        actual_files=list(output.glob('.coverage.*'));assert len(actual_files)>=2
        expected=str(ROOT/'app/core/errors.py')
        for file in actual_files:
            data=coverage.CoverageData(basename=str(file));data.read()
            assert data.has_arcs()
            assert expected in data.measured_files() and data.lines(expected)
