# Muse EEG to TouchDesigner

BlueMuse streams Muse headset EEG over Lab Streaming Layer (LSL). `eeg_to_osc.py` converts recent AF7 signal variation into an OSC level for TouchDesigner.

## One-click launcher

On Windows, double-click `Launch Muse.cmd` (or the desktop shortcut). The control panel starts BlueMuse, the EEG bridge, and the saved TouchDesigner project. It shows headset connection and signal level. If the bridge exits unexpectedly, it retries. **Stop all** or closing the control panel stops the bridge, sends a zero OSC level, requests BlueMuse shutdown, and asks the Muse TouchDesigner project to close normally so it can prompt you to save unsaved work. An already-open unrelated TouchDesigner project is left alone. If a manual EEG bridge is already running, close that PowerShell bridge with Ctrl+C and click **Start all** in the launcher.

Python with `pylsl` and `python-osc`, BlueMuse, and TouchDesigner must be installed on the computer. Use `py -m pip install pylsl python-osc` once if needed.

## Manual run

1. Open BlueMuse, connect the headset, and enable its EEG stream. In PowerShell, run `Start-Process 'bluemuse://start?startall'` to tell BlueMuse to start streaming when it discovers a Muse during this app session.
2. Install Python dependencies once: `py -m pip install pylsl python-osc`
3. In PowerShell, run `py .\eeg_to_osc.py` from this folder. Leave the terminal open.
4. In TouchDesigner, use an OSC In CHOP on UDP port `9000`. `/eeg/level` drives the sine wave amplitude. `/eeg/connected` is `1` while samples arrive and `0` after a disconnect.

The bridge sends a neutral level of `0` if EEG samples stop for three seconds. It keeps discovering the stream and resumes output when BlueMuse starts sending samples again. If you restart BlueMuse, run `Start-Process 'bluemuse://start?startall'` again. If the headset reconnects but no samples return, check BlueMuse's device connection and streaming state.

The level is a visual control signal, **not** alpha, beta, or other brainwave bands. High variation can reflect poor electrode contact or movement. In an initial live check, the EEG channels frequently reached their limits; adjust the headset for good contact before interpreting the display.

## TouchDesigner patch

`MuseTouchDesigner.toe` is the GitHub copy of the saved TouchDesigner patch. On this computer, the launcher opens whichever is newer: `Desktop/NewProject.toe` or `MuseTouchDesigner.toe`. This keeps later saves in the active Desktop project from being replaced by the older backup. If the Muse TouchDesigner project is already open, the launcher uses that window.
