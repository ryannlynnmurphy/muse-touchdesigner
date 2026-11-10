"""Exercise loss and recovery with a simulated LSL stream."""

import importlib.util
import unittest
from pathlib import Path
from unittest.mock import patch


SCRIPT = Path(__file__).resolve().parents[1] / "eeg_to_osc.py"
spec = importlib.util.spec_from_file_location("eeg_to_osc", SCRIPT)
bridge = importlib.util.module_from_spec(spec)
spec.loader.exec_module(bridge)


class FakeStream:
    def channel_count(self):
        return 5

    def name(self):
        return "Simulated Muse EEG"


class FakeOsc:
    def __init__(self):
        self.messages = []

    def send_message(self, address, value):
        self.messages.append((address, value))


class FakeInlet:
    created = 0
    clock = None

    def __init__(self, stream, recover):
        self.index = FakeInlet.created
        FakeInlet.created += 1
        self.pulls = 0
        self.closed = False

    def pull_sample(self, timeout):
        self.pulls += 1
        FakeInlet.clock[0] += 0.04 if self.pulls <= 40 else 0.6
        if self.pulls <= 40:
            return [0.0, (-300.0 if self.pulls % 2 else 300.0), 0.0, 0.0, 0.0], FakeInlet.clock[0]
        if self.index == 1:
            raise KeyboardInterrupt
        return None, None

    def close_stream(self):
        self.closed = True


class ReconnectTest(unittest.TestCase):
    def test_disconnect_clears_level_and_reconnects(self):
        clock = [0.0]
        osc = FakeOsc()
        FakeInlet.created = 0
        FakeInlet.clock = clock

        def advance(seconds):
            clock[0] += seconds

        with patch.object(bridge, "SimpleUDPClient", return_value=osc), \
             patch.object(bridge, "resolve_byprop", return_value=[FakeStream()]), \
             patch.object(bridge, "StreamInlet", FakeInlet), \
             patch.object(bridge, "monotonic", side_effect=lambda: clock[0]), \
             patch.object(bridge, "sleep", side_effect=advance):
            with self.assertRaises(KeyboardInterrupt):
                bridge.main()

        states = [value for address, value in osc.messages if address == "/eeg/connected"]
        levels = [value for address, value in osc.messages if address == "/eeg/level"]
        self.assertEqual(states, [0, 1, 0, 1, 0])
        self.assertGreater(sum(level > 0 for level in levels), 1)
        self.assertEqual(levels[-1], 0.0)
        self.assertEqual(FakeInlet.created, 2)


if __name__ == "__main__":
    unittest.main()
