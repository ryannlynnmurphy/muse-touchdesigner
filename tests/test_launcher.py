"""Check launcher ownership and cleanup without touching live apps."""

import importlib.util
import unittest
from pathlib import Path
from unittest.mock import patch


SCRIPT = Path(__file__).resolve().parents[1] / "launcher.pyw"
spec = importlib.util.spec_from_file_location("muse_launcher", SCRIPT)
launcher = importlib.util.module_from_spec(spec)
spec.loader.exec_module(launcher)


class FakeProcess:
    def __init__(self, pid):
        self.pid = pid
        self.stdout = []
        self.terminated = False

    def poll(self):
        return 0 if self.terminated else None

    def terminate(self):
        self.terminated = True

    def wait(self, timeout):
        return 0


class LauncherLifecycleTest(unittest.TestCase):
    def test_signal_status_recovers_after_a_dropout(self):
        app = launcher.Launcher()
        try:
            app._handle_bridge_line("EEG connected.")
            app._handle_bridge_line("AF7 variation: 300.0 uV | level: 0.500")
            self.assertTrue(app.headset_connected)
            self.assertAlmostEqual(app.level, 0.5)
            app._handle_bridge_line("EEG stopped. Waiting for reconnection...")
            self.assertFalse(app.headset_connected)
            self.assertEqual(app.level, 0.0)
            app._handle_bridge_line("EEG connected.")
            self.assertTrue(app.headset_connected)
        finally:
            app.destroy()

    def test_start_and_stop_owns_its_bridge_and_touchdesigner(self):
        td = FakeProcess(1001)
        bridge = FakeProcess(1002)
        app = launcher.Launcher()
        try:
            with patch.object(launcher, "existing_bridge_pids", return_value=[]), \
                 patch.object(launcher, "touchdesigner_windows", return_value=[]), \
                 patch.object(launcher.os, "startfile") as startfile, \
                 patch.object(launcher.subprocess, "Popen", side_effect=[td, bridge]) as popen, \
                 patch.object(launcher, "request_normal_close", return_value=True) as close_td, \
                 patch.object(launcher, "send_osc") as osc:
                app.start_all()
                self.assertTrue(app.want_running)
                self.assertEqual(popen.call_count, 2)
                self.assertEqual(app.touchdesigner_pid, 1001)
                app.stop_all()
                self.assertFalse(app.want_running)
                self.assertTrue(bridge.terminated)
                close_td.assert_called_once_with(1001)
                osc.assert_any_call("/eeg/level", 0)
                osc.assert_any_call("/eeg/connected", 0)
                self.assertEqual(startfile.call_count, 3)
        finally:
            app.destroy()

    def test_manual_bridge_prevents_duplicate_session(self):
        app = launcher.Launcher()
        try:
            with patch.object(launcher, "existing_bridge_pids", return_value=[1234]), \
                 patch.object(launcher.os, "startfile") as startfile, \
                 patch.object(launcher.subprocess, "Popen") as popen:
                app.start_all()
                self.assertFalse(app.want_running)
                popen.assert_not_called()
                startfile.assert_not_called()
        finally:
            app.destroy()


if __name__ == "__main__":
    unittest.main()
