import sounddevice as sd
import numpy as np
from scipy.io.wavfile import write
import matplotlib.pyplot as plt
from scipy.signal import spectrogram

# =====================================================
# SETTINGS
# =====================================================

DURATION = 10                  # seconds
SAMPLE_RATE = 96000            # Hz
CHANNELS = 8                   # number of microphones
DEVICE = 1                     # Focusrite MME device
OUTPUT_WAV = "tdoa_4ch.wav"

# =====================================================
# DISPLAY AVAILABLE DEVICES
# =====================================================

print("\n========================================")
print("AVAILABLE AUDIO DEVICES")
print("========================================\n")

print(sd.query_devices())

print("\n========================================")
print("SELECTED DEVICE")
print("========================================\n")

print(sd.query_devices(DEVICE))

# =====================================================
# RECORD AUDIO
# =====================================================

print(f"\nRecording {CHANNELS} channels for {DURATION} seconds...\n")

audio = sd.rec(
    frames=int(DURATION * SAMPLE_RATE),
    samplerate=SAMPLE_RATE,
    channels=CHANNELS,
    device=DEVICE,
    dtype=np.float32,
    blocking=True
)

print("Recording complete.\n")

# =====================================================
# SAVE WAV FILE
# =====================================================

audio_int16 = np.int16(audio * 32767)

write(
    OUTPUT_WAV,
    SAMPLE_RATE,
    audio_int16
)

print(f"WAV saved as: {OUTPUT_WAV}\n")

# =====================================================
# CREATE TIME AXIS
# =====================================================

time_axis = np.linspace(
    0,
    DURATION,
    len(audio)
)

# =====================================================
# CREATE FIGURE
# =====================================================

fig, axes = plt.subplots(
    CHANNELS,
    1,
    figsize=(16, 2.5 * CHANNELS)
)

fig.suptitle(
    "4-Channel TDOA Recording",
    fontsize=22
)

# =====================================================
# PROCESS EACH CHANNEL
# =====================================================

for ch in range(CHANNELS):

    channel_data = audio[:, ch]

    peak = np.max(np.abs(channel_data))
    rms = np.sqrt(np.mean(channel_data**2))

    print(f"\nCHANNEL {ch + 1}")
    print(f"Peak: {peak:.6f}")
    print(f"RMS : {rms:.6f}")

    ax_wave = axes[ch]

    ax_wave.plot(
        time_axis,
        channel_data,
        linewidth=0.8
    )

    ax_wave.set_title(
        f"Channel {ch + 1}"
    )

    ax_wave.set_xlim(0, DURATION)

    ax_wave.grid(True)
    # -------------------------------------------------
    # SPECTROGRAM
    # -------------------------------------------------

    frequencies, times, Sxx = spectrogram(
        channel_data,
        fs=SAMPLE_RATE,
        window='hann',
        nperseg=2048,
        noverlap=1800,
        scaling='density',
        mode='magnitude'
    )

    # Convert to dB
    Sxx_db = 20 * np.log10(Sxx + 1e-10)

    ax_wave = axes[ch]

    mesh = ax_wave.pcolormesh(
        times,
        frequencies,
        Sxx_db,
        shading='gouraud',
        cmap='inferno'
    )

    ax_wave.set_title(
        f"Channel {ch + 1} Spectrogram"
    )

    ax_wave.set_xlabel("Time (s)")
    ax_wave.set_ylabel("Frequency (Hz)")

    ax_wave.set_ylim(0, 10000)

    # -------------------------------------------------
    # COLORBAR
    # -------------------------------------------------

    cbar = fig.colorbar(
        mesh,
        ax=ax_wave
    )

    cbar.set_label("Intensity (dB)")

# =====================================================
# FINALIZE LAYOUT
# =====================================================

plt.tight_layout()

plt.show()