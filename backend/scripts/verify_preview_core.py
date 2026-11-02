"""Run only the four accepted synthetic core modules with process I/O denied."""
import json
import os
from pathlib import Path
import sys
import unittest

sys.dont_write_bytecode = True
BACKEND = Path(__file__).resolve().parents[1]
sys.path[:0] = [str(BACKEND), str(BACKEND / 'tests')]

def deny_io(event, args):
    if event == 'open':
        _, mode, flags = args
        if ((isinstance(mode, str) and any(c in mode for c in 'wax+')) or
                (isinstance(flags, int) and flags & (os.O_WRONLY | os.O_RDWR | os.O_CREAT | os.O_TRUNC | os.O_APPEND))):
            raise PermissionError('pure core: file write denied')
    if event.startswith(('socket.', 'sqlite3.', 'subprocess.')) or event in (
        'os.system', 'os.exec', 'os.posix_spawn', 'os.remove', 'os.rmdir', 'os.mkdir',
        'os.rename', 'os.link', 'os.symlink', 'os.chmod', 'os.utime', 'os.truncate'):
        raise PermissionError('pure core: forbidden I/O: ' + event)

sys.addaudithook(deny_io)
modules = ('test_audit_delivery_contract', 'test_audit_delivery_fragments',
           'test_audit_delivery_restrictions', 'test_audit_delivery_quantity')
suite = unittest.TestLoader().loadTestsFromNames(modules)

class CountResult(unittest.TextTestResult):
    subtests = 0
    def addSubTest(self, test, subtest, err):
        self.subtests += 1
        return super().addSubTest(test, subtest, err)

if __name__ == '__main__':
    expected_methods = suite.countTestCases()
    result = unittest.TextTestRunner(verbosity=2, resultclass=CountResult).run(suite)
    counts = dict(methods=expected_methods, executed=result.testsRun, subtests=result.subtests,
                  failures=len(result.failures), errors=len(result.errors), skipped=len(result.skipped))
    print('CORE_COUNTS ' + json.dumps(counts))
    sys.exit(0 if result.wasSuccessful() and expected_methods == result.testsRun == 242 and result.subtests == 585 and not result.failures and not result.errors and not result.skipped else 1)
