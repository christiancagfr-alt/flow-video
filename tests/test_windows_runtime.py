import ctypes
import os
from pathlib import Path
import sys
import tempfile
import unittest
from app.services import quiet_process as process

class QuietProcessTests(unittest.TestCase):
    def test_captured_protocol_and_stdin(self):
        result = process.run([sys.executable, '-c', 'import sys; print(sys.stdin.read()); print("diagnostic", file=sys.stderr)'],
                             input='payload', capture_output=True, text=True, check=True)
        self.assertEqual(result.stdout.strip(), 'payload')
        self.assertEqual(result.stderr.strip(), 'diagnostic')

    @unittest.skipUnless(os.name == 'nt', 'Windows console check')
    def test_children_have_no_console(self):
        code = 'import ctypes; print(ctypes.windll.kernel32.GetConsoleWindow())'
        for launch in ('run', 'popen'):
            if launch == 'run':
                output = process.run([sys.executable, '-c', code], capture_output=True, text=True, check=True).stdout
            else:
                with process.Popen([sys.executable, '-c', code], stdout=process.PIPE, text=True) as child:
                    output, _ = child.communicate(timeout=10)
            self.assertEqual(output.strip(), '0')

    @unittest.skipUnless(os.name == 'nt', 'Windows Qt console check')
    def test_qt_children_have_no_console(self):
        from PySide6.QtCore import QCoreApplication, QProcess
        app = QCoreApplication.instance() or QCoreApplication([])
        child = QProcess()
        child.start(sys.executable, ['-c', 'import ctypes; print(ctypes.windll.kernel32.GetConsoleWindow())'])
        self.assertTrue(child.waitForFinished(10000))
        self.assertEqual(child.exitCode(), 0)
        self.assertEqual(bytes(child.readAllStandardOutput()).strip(), b'0')

    def test_failure_retains_captured_error(self):
        with self.assertRaises(process.CalledProcessError) as error:
            process.run([sys.executable, '-c', 'import sys; print("failed", file=sys.stderr); sys.exit(7)'], capture_output=True, text=True, check=True)
        self.assertEqual(error.exception.returncode, 7)
        self.assertIn('failed', error.exception.stderr)

    def test_timeout_stops_child(self):
        with self.assertRaises(process.TimeoutExpired):
            process.run([sys.executable, '-c', 'import time; time.sleep(30)'], timeout=0.2, capture_output=True)

    def test_unrequested_output_is_discarded(self):
        result = process.run([sys.executable, '-c', 'print("should not appear")'], check=True)
        self.assertIsNone(result.stdout)

if __name__ == '__main__':
    unittest.main()
