"""Send BlueMuse EEG activity to TouchDesigner as OSC /eeg/level."""

from collections import deque
from statistics import pstdev
from time import monotonic

from pylsl import StreamInlet, resolve_byprop
from pythonosc.udp_client import SimpleUDPClient


def main():
    print("Waiting for BlueMuse EEG stream. Start EEG streaming in BlueMuse.", flush=True)
    streams = resolve_byprop("type", "EEG")
    inlet = StreamInlet(streams[0])
    osc = SimpleUDPClient("127.0.0.1", 9000)
    window = deque(maxlen=128)
    last_send = 0.0
    last_print = 0.0

    print(f"Receiving {streams[0].name()} on {streams[0].channel_count()} channels.", flush=True)
    while True:
        sample, _ = inlet.pull_sample(timeout=1.0)
        if sample is None:
            continue
        window.append(float(sample[1]))  # AF7; cleaner than TP9 in the current stream
        now = monotonic()
        if len(window) >= 32 and now - last_send >= 1 / 30:
            variation = pstdev(window)
            level = variation / (variation + 300.0)
            osc.send_message("/eeg/level", level)
            last_send = now
            if now - last_print >= 1.0:
                print(f"AF7 variation: {variation:.1f} uV | EEG level: {level:.3f}", flush=True)
                last_print = now


if __name__ == "__main__":
    try:
        main()
    except KeyboardInterrupt:
        print("Stopped.")
