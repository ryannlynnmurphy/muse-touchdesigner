# Muse EEG to TouchDesigner

BlueMuse streams Muse headset EEG over Lab Streaming Layer (LSL). `eeg_to_osc.py` converts recent AF7 signal variation into an OSC level for TouchDesigner.

## Run

1. Open BlueMuse, connect the headset, and enable its EEG stream. In PowerShell, run `Start-Process 'bluemuse://start?startall'` to tell BlueMuse to start streaming when it discovers a Muse during this app session.
2. Install Python dependencies once: `py -m pip install pylsl python-osc`
3. In PowerShell, run `py .\eeg_to_osc.py` from this folder. Leave the terminal open.
4. In TouchDesigner, use an OSC In CHOP on UDP port `9000`. `/eeg/level` drives the sine wave amplitude. `/eeg/connected` is `1` while samples arrive and `0` after a disconnect.

The bridge sends a neutral level of `0` if EEG samples stop for three seconds. It keeps discovering the stream and resumes output when BlueMuse starts sending samples again. If you restart BlueMuse, run `Start-Process 'bluemuse://start?startall'` again. If the headset reconnects but no samples return, check BlueMuse's device connection and streaming state.

The level is a visual control signal, **not** alpha, beta, or other brainwave bands. High variation can reflect poor electrode contact or movement. In an initial live check, the EEG channels frequently reached their limits; adjust the headset for good contact before interpreting the display.

## TouchDesigner patch

The `.toe` project file is the TouchDesigner patch. Open it in TouchDesigner after cloning this repository. Keep `eeg_to_osc.py` running in a separate PowerShell window.
