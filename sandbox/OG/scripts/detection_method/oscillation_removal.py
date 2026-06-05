import numpy as np
import matplotlib.pyplot as plt
from scipy.io import wavfile

# ============================================================
# FILES
# ============================================================

wav_files = [
    "01-260522_1224.wav",
    "02-260522_1224.wav",
    "03-260522_1224.wav",
    "04-260522_1224.wav",
    "05-260522_1224.wav"
]

# ============================================================
# ZOOM SETTINGS
# ============================================================

ZOOM_START = 500000
ZOOM_END   = 0

# ============================================================
# DETECTOR SETTINGS
# ============================================================

MIN_ALTERNATING_RUN = 3


# ============================================================
# PROCESS
# ============================================================

fig, axes = plt.subplots(5, 1, figsize=(14, 12))

for ch, wav_path in enumerate(wav_files):

    sample_rate, data = wavfile.read(wav_path)

    if data.ndim > 1:
        data = data[:, 0]

    x = data.astype(np.float64)

    # --------------------------------------------------------
    # ZOOM REGION
    # --------------------------------------------------------

    x_zoom = x[ZOOM_START:ZOOM_END]

    signs = np.sign(x_zoom)

    cleaned = x_zoom.copy()

    i = 0

    while i < len(signs) - 1:

        run_start = i
        run_length = 1

        # ----------------------------------------------------
        # LOOK FOR PERFECT ALTERNATION
        # ----------------------------------------------------

        while i < len(signs) - 1:

            current = signs[i]
            next_sign = signs[i + 1]

            # Ignore zeros
            if current == 0 or next_sign == 0:
                break

            # Perfect flip?
            if next_sign == -current:
                run_length += 1
                i += 1
            else:
                break

        # ----------------------------------------------------
        # REMOVE RUN
        # ----------------------------------------------------

        if run_length >= MIN_ALTERNATING_RUN:

            cleaned[run_start:run_start + run_length] = 0

        i += 1

    # --------------------------------------------------------
    # PLOT
    # --------------------------------------------------------

    ax = axes[ch]

    ax.plot(
        np.arange(ZOOM_START, ZOOM_END),
        x_zoom,
        color='white',
        linewidth=1,
        label='Original'
    )

    ax.plot(
        np.arange(ZOOM_START, ZOOM_END),
        cleaned,
        color='blue',
        linewidth=2,
        label='Alternating Removed'
    )

    ax.set_title(f'Channel {ch + 1}')
    ax.set_ylabel('Amplitude')
    ax.grid(True)

    if ch == 0:
        ax.legend()

axes[-1].set_xlabel('Sample')

plt.tight_layout()
plt.show()