# ============================================================
# ENVIROPULSE TDOA PATTERN DETECTOR
# ============================================================
#
# Experimental waveform-structure onset detector
#
# Detects patterns like:
#
# ----++++
#
# or
#
# ++++----
#
# Then backtracks to the FIRST sample
# of the detected polarity run.
#
# ============================================================

import numpy as np
import matplotlib.pyplot as plt

from scipy.io import wavfile

# ============================================================
# USER SETTINGS
# ============================================================

WAV_FILES = [

    "01-260526_0830.wav",
    "02-260526_0830.wav",
    "03-260526_0830.wav",
    "04-260526_0830.wav",
    "05-260526_0830.wav"

]

# ------------------------------------------------------------
# Detection sensitivity
# ------------------------------------------------------------

RUN_LENGTH = 3

# ------------------------------------------------------------
# Ignore repeated triggers
# ------------------------------------------------------------

COOLDOWN_SAMPLES = 50000

# ------------------------------------------------------------
# Zoom region around detection
# ------------------------------------------------------------

PRE_SAMPLES =50
POST_SAMPLES = 100


# ------------------------------------------------------------
# Maximum backtrack distance
# ------------------------------------------------------------

MAX_BACKTRACK = 7

# ============================================================
# STORAGE
# ============================================================

all_detections = []

# ============================================================
# PROCESS EACH FILE
# ============================================================

for channel, wav_path in enumerate(WAV_FILES):

    print("\n")
    print("=" * 70)
    print(f"PROCESSING FILE: {wav_path}")
    print("=" * 70)

    # ========================================================
    # LOAD WAV
    # ========================================================

    sample_rate, signal = wavfile.read(wav_path)

    signal = signal.astype(np.float64)

    # --------------------------------------------------------
    # Handle stereo files
    # --------------------------------------------------------

    if len(signal.shape) > 1:

        signal = signal[:, 0]

    # ========================================================
    # SIGN STREAM
    # ========================================================

    signs = np.sign(signal)

    # ========================================================
    # DETECTOR
    # ========================================================

    detections = []

    last_detection = -COOLDOWN_SAMPLES

    i = 0

    while i < len(signs) - RUN_LENGTH * 2:

        # ----------------------------------------------------
        # BUILD TWO SIGN BLOCKS
        # ----------------------------------------------------

        first_block = signs[i:i + RUN_LENGTH]

        second_block = signs[
            i + RUN_LENGTH:
            i + RUN_LENGTH * 2
        ]

        # ----------------------------------------------------
        # DETECT:
        #
        # ----++++
        #
        # OR
        #
        # ++++----
        # ----------------------------------------------------

        neg_to_pos = (

            np.all(first_block == -1)
            and
            np.all(second_block == 1)

        )

        pos_to_neg = (

            np.all(first_block == 1)
            and
            np.all(second_block == -1)

        )

        valid_pattern = neg_to_pos or pos_to_neg

        # ====================================================
        # DETECTION
        # ====================================================

        if valid_pattern:

            # ------------------------------------------------
            # BACKTRACK TO START OF CURRENT RUN
            # ------------------------------------------------

            candidate = i

            target_sign = signs[i]
            
            backtrack_count = 0
            
            while (

                candidate > 0
                and
                signs[candidate - 1] == target_sign
                and
                backtrack_count < MAX_BACKTRACK

            ):

                candidate -= 1
                
                backtrack_count += 1
            # ------------------------------------------------
            # COOLDOWN
            # ------------------------------------------------

            if candidate - last_detection > COOLDOWN_SAMPLES:

                detections.append(candidate)

                last_detection = candidate

                print(f"\nONSET DETECTED: {candidate}")

        i += 1

    # ========================================================
    # STORE FIRST DETECTION
    # ========================================================

    if len(detections) > 0:

        all_detections.append(detections[0])

    else:

        all_detections.append(None)

    # ========================================================
    # FULL SIGNAL PLOT
    # ========================================================

    plt.figure(figsize=(14, 5))

    plt.plot(signal, linewidth=0.7)

    for d in detections:

        plt.axvline(
            d,
            linestyle='--',
            linewidth=2
        )

    plt.title(f"Channel {channel + 1} Detection")

    plt.xlabel("Sample")
    plt.ylabel("Amplitude")

    plt.grid(True)

    plt.show(block=False)

    # ========================================================
    # ZOOM FIRST DETECTION
    # ========================================================

    if len(detections) > 0:

        center = detections[0]

        start = max(
            0,
            center - PRE_SAMPLES
        )

        end = min(
            len(signal),
            center + POST_SAMPLES
        )

        zoom_signal = signal[start:end]

        x = np.arange(start, end)

        # ----------------------------------------------------
        # PRINT SAMPLE VALUES
        # ----------------------------------------------------

        print("\n")
        print("=" * 70)
        print(f"ZOOMED DETECTION: CHANNEL {channel + 1}")
        print("=" * 70)

        print("\nSample\tAmplitude")
        print("-" * 35)

        for sample_num, amplitude in zip(x, zoom_signal):

            print(f"{sample_num}\t{int(amplitude)}")

        # ----------------------------------------------------
        # ZOOM PLOT
        # ----------------------------------------------------

        plt.figure(figsize=(12, 5))

        plt.plot(

            x,
            zoom_signal,

            marker='o',
            linewidth=2

        )

        plt.axvline(

            center,

            linestyle='--',
            linewidth=2

        )

        plt.title(
            f"Zoomed Detection - Channel {channel + 1}"
        )

        plt.xlabel("Sample")
        plt.ylabel("Amplitude")

        plt.grid(True)

        plt.xlim(start, end)

        plt.show()

# ============================================================
# DETECTION SUMMARY
# ============================================================

print("\n")
print("=" * 70)
print("DETECTION SUMMARY")
print("=" * 70)

for ch, detection in enumerate(all_detections):

    print(f"Channel {ch + 1}: {detection}")

# ============================================================
# DELTA CALCULATIONS
# ============================================================

reference = all_detections[0]

print("\n")
print("=" * 70)
print("DELTA RESULTS")
print("=" * 70)

for ch in range(1, len(all_detections)):

    detection = all_detections[ch]

    if detection is not None and reference is not None:

        delta_samples = detection - reference

        delta_time = delta_samples / sample_rate

        print("\n")
        print(f"Channel 1 -> Channel {ch + 1}")

        print(f"Delta Samples : {delta_samples}")

        print(
            f"Delta Time    : "
            f"{delta_time:.9f} seconds"
        )

        print(
            f"Delta Time    : "
            f"{delta_time * 1e6:.3f} microseconds"
        )

# ============================================================
# FINAL NOTE
# ============================================================

print("\n")
print("=" * 70)
print("PROCESS COMPLETE")
print("=" * 70)