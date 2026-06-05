# ============================================================
# detect_t_alpha_multi_wav.py
# ============================================================
#
# Loads multiple synchronized mono WAV files
# Detects t_alpha automatically for each microphone
# Plots onset regions
#
# Designed for:
# REAPER synchronized mono exports
# EnviroPulse TDOA experiments
#
# ============================================================

import numpy as np
import matplotlib.pyplot as plt

from scipy.io import wavfile
from scipy.signal import butter, filtfilt

# ============================================================
# USER SETTINGS
# ============================================================

WAV_FILES = [

    "01-260521_1352.wav",
    "02-260521_1352.wav",
    "03-260521_1352.wav",
    "04-260521_1352.wav",
    "05-260521_1352.wav"

]

NOISE_WINDOW = 0.25
THRESHOLD_MULTIPLIER =100

LOWCUT = 500
HIGHCUT = 8000

ZOOM_BEFORE = 0.01
ZOOM_AFTER = 0.03

SEARCH_START = 2.8
# ============================================================
# BANDPASS FILTER
# ============================================================

def bandpass_filter(data, lowcut, highcut, fs, order=4):

    nyquist = 0.5 * fs

    low = lowcut / nyquist
    high = highcut / nyquist

    b, a = butter(order, [low, high], btype='band')

    return filtfilt(b, a, data)

# ============================================================
# LOAD FILES
# ============================================================

audio_data = []

sample_rates = []
lengths = []

print("\n====================================")
print("LOADING WAV FILES")
print("====================================")

for file in WAV_FILES:

    sample_rate, audio = wavfile.read(file)

    print(f"\nLoaded: {file}")
    print(f"Sample Rate : {sample_rate}")
    print(f"Shape       : {audio.shape}")

    # ----------------------------------------
    # FORCE MONO
    # ----------------------------------------

    if len(audio.shape) > 1:

        audio = audio[:, 0]

    audio = audio.astype(np.float64)

    max_val = np.max(np.abs(audio))

    if max_val > 0:
        audio = audio / max_val

    audio_data.append(audio)

    sample_rates.append(sample_rate)
    lengths.append(len(audio))

# ============================================================
# VERIFY CONSISTENCY
# ============================================================

if len(set(sample_rates)) != 1:

    raise ValueError(
        "ERROR: Sample rates do not match."
    )

if len(set(lengths)) != 1:

    raise ValueError(
        "ERROR: WAV lengths do not match."
    )

sample_rate = sample_rates[0]

channels = len(audio_data)

samples = lengths[0]

print("\n====================================")
print("DATA VERIFIED")
print("====================================")

print(f"Channels     : {channels}")
print(f"Samples      : {samples}")
print(f"Sample Rate  : {sample_rate}")

# ============================================================
# STACK INTO ARRAY
# ============================================================

audio = np.stack(audio_data, axis=1)

time_axis = np.arange(samples) / sample_rate

# ============================================================
# DETECT t_alpha
# ============================================================

t_alpha_samples = []
t_alpha_times = []

fig, axes = plt.subplots(
    channels,
    1,
    figsize=(14, 3 * channels)
)

if channels == 1:
    axes = [axes]

for ch in range(channels):

    signal = audio[:, ch]

    # --------------------------------------------------------
    # RMS CHECK
    # --------------------------------------------------------

    rms = np.sqrt(np.mean(signal**2))

    print(f"\nChannel {ch+1} RMS: {rms:.6f}")

    if rms < 1e-5:

        print(f"Channel {ch+1} skipped")

        continue

    # --------------------------------------------------------
    # FILTER
    # --------------------------------------------------------

    filtered = bandpass_filter(
        signal,
        LOWCUT,
        HIGHCUT,
        sample_rate
    )

    # --------------------------------------------------------
    # ENERGY ENVELOPE
    # --------------------------------------------------------

    energy = np.abs(filtered)

    window_size = 200

    smoothed = np.convolve(
        energy,
        np.ones(window_size) / window_size,
        mode='same'
    )

    # --------------------------------------------------------
    # BASELINE
    # --------------------------------------------------------

    noise_samples = int(NOISE_WINDOW * sample_rate)

    baseline = np.mean(smoothed[:noise_samples])

    sigma = np.std(smoothed[:noise_samples])

    threshold = baseline + THRESHOLD_MULTIPLIER * sigma

    # --------------------------------------------------------
    # FIND ONSET
    # --------------------------------------------------------

    search_start_sample = int(SEARCH_START * sample_rate)

    crossings = np.where(smoothed[search_start_sample:] > threshold)[0]

    if len(crossings) == 0:
        print(f"Channel {ch + 1}: no onset found after {SEARCH_START} seconds")
        continue

    onset_index = search_start_sample + crossings[0]

    onset_time = onset_index / sample_rate

    t_alpha_samples.append(onset_index)

    t_alpha_times.append(onset_time)

    # --------------------------------------------------------
    # PRINT RESULTS
    # --------------------------------------------------------

    print("\n------------------------------------")
    print(f"CHANNEL {ch + 1}")
    print("------------------------------------")

    print(f"t_alpha sample : {onset_index}")

    print(f"t_alpha time   : {onset_time:.8f} s")

    # --------------------------------------------------------
    # ZOOM WINDOW
    # --------------------------------------------------------

    start_idx = max(
        0,
        onset_index - int(ZOOM_BEFORE * sample_rate)
    )

    end_idx = min(
        len(smoothed),
        onset_index + int(ZOOM_AFTER * sample_rate)
    )

    zoom_time = time_axis[start_idx:end_idx]

    zoom_signal = smoothed[start_idx:end_idx]

    # --------------------------------------------------------
    # PLOT
    # --------------------------------------------------------

    ax = axes[ch]

    ax.plot(
        zoom_time,
        zoom_signal
    )

    ax.axhline(
        threshold,
        linestyle='--'
    )

    ax.axvline(
        onset_time,
        linestyle='--'
    )

    ax.set_xlim(
        onset_time - ZOOM_BEFORE,
        onset_time + ZOOM_AFTER
    )

    ax.set_title(f"Channel {ch + 1}")

    ax.set_xlabel("Time (s)")

    ax.set_ylabel("Energy")

# ============================================================
# DELTA TIMES
# ============================================================

print("\n====================================")
print("DELTA TIMES")
print("====================================")

reference = t_alpha_times[0]

for i, t in enumerate(t_alpha_times):

    delta_t = t - reference

    print(
        f"Channel {i + 1}: "
        f"{delta_t:+.8f} s"
    )

# ============================================================
# DELTA SAMPLES
# ============================================================

print("\n====================================")
print("DELTA SAMPLES")
print("====================================")

reference_sample = t_alpha_samples[0]

for i, sample in enumerate(t_alpha_samples):

    delta_samples = sample - reference_sample

    print(
        f"Channel {i + 1}: "
        f"{delta_samples:+d} samples"
    )

# ============================================================
# DISTANCE OFFSETS
# ============================================================

print("\n====================================")
print("DISTANCE OFFSETS")
print("====================================")

speed_of_sound = 343.0

for i, t in enumerate(t_alpha_times):

    delta_t = t - reference

    distance = delta_t * speed_of_sound

    print(
        f"Channel {i + 1}: "
        f"{distance:+.4f} m"
    )
# --------------------------------------------------------
# FULL SIGNAL PLOT
# --------------------------------------------------------

fig_full, ax_full = plt.subplots(figsize=(14, 3))

ax_full.plot(time_axis, smoothed)

ax_full.axhline(
    threshold,
    linestyle='--'
)

ax_full.axvline(
    onset_time,
    linestyle='--'
)

ax_full.set_title(f"FULL VIEW - Channel {ch + 1}")

ax_full.set_xlabel("Time (s)")

ax_full.set_ylabel("Energy")
# ============================================================
# SHOW PLOTS
# ============================================================

plt.tight_layout()

plt.show()