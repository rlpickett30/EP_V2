import numpy as np
import matplotlib.pyplot as plt

from scipy.io.wavfile import read
from scipy.signal import spectrogram
from scipy.ndimage import uniform_filter1d

# -----------------------------------
# SETTINGS
# -----------------------------------

INPUT_WAV = "recording.wav"

SMOOTHING_WINDOW = 1000
THRESHOLD_MULTIPLIER = 3
MIN_TIME_BETWEEN_EVENTS = 0.3   # seconds

# -----------------------------------
# LOAD AUDIO
# -----------------------------------

sample_rate, audio = read(INPUT_WAV)

# Convert int16 -> float
audio = audio.astype(np.float32) / 32768.0

# Mono safety
if len(audio.shape) > 1:
    audio = audio[:, 0]

# -----------------------------------
# TIME AXIS
# -----------------------------------

time_axis = np.linspace(
    0,
    len(audio) / sample_rate,
    len(audio)
)

# -----------------------------------
# ENVELOPE
# -----------------------------------

envelope = np.abs(audio)

# Smooth envelope
smoothed = uniform_filter1d(
    envelope,
    size=SMOOTHING_WINDOW
)

# -----------------------------------
# NOISE FLOOR
# -----------------------------------

noise_floor = np.median(smoothed)

threshold = noise_floor * THRESHOLD_MULTIPLIER

print(f"Noise floor: {noise_floor:.6f}")
print(f"Threshold:   {threshold:.6f}")

# -----------------------------------
# DETECT EVENTS
# -----------------------------------

event_indices = []

last_event_time = -999

for i in range(1, len(smoothed)):

    crossed = (
        smoothed[i - 1] < threshold
        and
        smoothed[i] >= threshold
    )

    if crossed:

        current_time = i / sample_rate

        if (
            current_time - last_event_time
            >= MIN_TIME_BETWEEN_EVENTS
        ):

            event_indices.append(i)
            last_event_time = current_time

# -----------------------------------
# PRINT DETECTIONS
# -----------------------------------

print("\nDetected t_alpha values:\n")

for idx, sample_index in enumerate(event_indices):

    t_alpha = sample_index / sample_rate

    print(f"Event {idx+1}: {t_alpha:.6f} seconds")

# -----------------------------------
# SPECTROGRAM
# -----------------------------------

frequencies, times, Sxx = spectrogram(
    audio,
    fs=sample_rate,
    window='hann',
    nperseg=2048,
    noverlap=1800,
    scaling='density',
    mode='magnitude'
)

Sxx_db = 20 * np.log10(Sxx + 1e-10)

# -----------------------------------
# PLOTTING
# -----------------------------------

fig, (ax1, ax2) = plt.subplots(
    2,
    1,
    figsize=(14, 10)
)

# -----------------------------------
# WAVEFORM
# -----------------------------------

ax1.plot(
    time_axis,
    audio,
    linewidth=1
)

# Plot detections
for sample_index in event_indices:

    t_alpha = sample_index / sample_rate

    ax1.axvline(
        t_alpha,
        color='red',
        linestyle='--',
        alpha=0.8
    )

ax1.set_title("Waveform with t_alpha Detection")
ax1.set_xlabel("Time (s)")
ax1.set_ylabel("Amplitude")

# -----------------------------------
# SPECTROGRAM
# -----------------------------------

spec = ax2.pcolormesh(
    times,
    frequencies,
    Sxx_db,
    shading='gouraud',
    cmap='inferno'
)

# Plot detections
for sample_index in event_indices:

    t_alpha = sample_index / sample_rate

    ax2.axvline(
        t_alpha,
        color='cyan',
        linestyle='--',
        alpha=0.8
    )

ax2.set_title("Spectrogram with t_alpha Detection")
ax2.set_xlabel("Time (s)")
ax2.set_ylabel("Frequency (Hz)")

ax2.set_ylim(0, 10000)

cbar = fig.colorbar(spec, ax=ax2)
cbar.set_label("Intensity (dB)")

plt.tight_layout()
plt.show()