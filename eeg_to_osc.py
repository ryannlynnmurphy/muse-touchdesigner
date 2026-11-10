"""Bridge BlueMuse EEG over LSL to TouchDesigner OSC.

Sends /eeg/level (0..1) and /eeg/connected (0 or 1) to localhost:9000.
The level reflects recent AF7 signal variation, not EEG frequency bands.
"""

from collections import deque
from statistics import pstdev
from time import monotonic, sleep

from pylsl import StreamInlet, resolve_byprop
from pythonosc.udp_client import SimpleUDPClient


OSC_PORT = 9000
STALE_AFTER_SECONDS = 3.0
RETRY_SECONDS = 1.0
WINDOW_SAMPLES = 128
MIN_SAMPLES = 32
SEND_INTERVAL_SECONDS = 1 / 30


def main():
    osc = SimpleUDPClient("127.0.0.1", OSC_PORT)
    osc.send_message("/eeg/connected", 0)
    osc.send_message("/eeg/level", 0.0)
    print("Waiting for BlueMuse EEG. Press Ctrl+C to stop.", flush=True)

    while True:
        try:
            streams = resolve_byprop("type", "EEG", timeout=2.0)
        except Exception as exc:
            print(f"LSL discovery failed: {exc}. Retrying...", flush=True)
            sleep(RETRY_SECONDS)
            continue

        if not streams:
            sleep(RETRY_SECONDS)
            continue

        inlet = None
        try:
            stream = streams[0]
            if stream.channel_count() < 2:
                print("EEG stream has no AF7 channel. Retrying...", flush=True)
                sleep(RETRY_SECONDS)
                continue

            inlet = StreamInlet(stream, recover=False)
            window = deque(maxlen=WINDOW_SAMPLES)
            last_sample = monotonic()
            last_send = 0.0
            last_print = 0.0
            connected = False
            print(f"Found {stream.name()}; waiting for samples...", flush=True)

            while True:
                sample, _ = inlet.pull_sample(timeout=0.5)
                now = monotonic()
                if sample is None:
                    if now - last_sample >= STALE_AFTER_SECONDS:
                        print("EEG stopped. Waiting for reconnection...", flush=True)
                        break
                    continue

                last_sample = now
                if not connected:
                    osc.send_message("/eeg/connected", 1)
                    connected = True
                    print("EEG connected.", flush=True)

                window.append(float(sample[1]))  # AF7 electrode
                if len(window) >= MIN_SAMPLES and now - last_send >= SEND_INTERVAL_SECONDS:
                    variation = pstdev(window)
                    level = variation / (variation + 300.0)
                    osc.send_message("/eeg/level", level)
                    last_send = now
                    if now - last_print >= 1.0:
                        print(f"AF7 variation: {variation:.1f} uV | level: {level:.3f}", flush=True)
                        last_print = now
        except Exception as exc:
            print(f"EEG stream lost: {exc}. Retrying...", flush=True)
        finally:
            osc.send_message("/eeg/connected", 0)
            osc.send_message("/eeg/level", 0.0)
            if inlet is not None:
                try:
                    inlet.close_stream()
                except Exception:
                    pass
            sleep(RETRY_SECONDS)


if __name__ == "__main__":
    try:
        main()
    except KeyboardInterrupt:
        print("Stopped.", flush=True)
