# ============================================================
# ENVIROPULSE TDOA PATTERN DETECTOR
# ============================================================
#
# ENERGY STATE MACHINE + EVENT MATCHER
#
# FEATURES
#
# 1. Pattern-based onset detection
#
#       ----++++
#       ++++----
#
# 2. Dynamic noise-floor estimation
#
# 3. Adaptive energy threshold
#
# 4. Quiet-duration offset validation
#
# 5. Limited onset backtracking
#
# 6. Multi-channel event matching
#
# 7. False detection rejection
#
# 8. Relative delta averaging
#
# ============================================================

import numpy as np
import matplotlib.pyplot as plt

from scipy.io import wavfile

# ============================================================
# USER SETTINGS
# ============================================================

WAV_FILES = [

    "01-260527_0815.wav",
    "02-260527_0815.wav",
    "03-260527_0815.wav",
    "04-260527_0815.wav",
    "05-260527_0815.wav"

]

# ============================================================
# ONSET SETTINGS
# ============================================================

RUN_LENGTH = 3

MAX_BACKTRACK = 7

# ============================================================
# DYNAMIC NOISE FLOOR SETTINGS
# ============================================================

NOISE_SAMPLE_COUNT = 200000

OFFSET_MULTIPLIER = 4.0

# ============================================================
# OFFSET SETTINGS
# ============================================================

MIN_QUIET_SAMPLES = 15000

# ============================================================
# EVENT MATCHER SETTINGS
# ============================================================

# ------------------------------------------------------------
# Maximum allowed timing difference between channels
# for the SAME physical event
# ------------------------------------------------------------

MATCH_TOLERANCE = 2000

# ------------------------------------------------------------
# Maximum allowed delta mismatch
# between sequential events
# ------------------------------------------------------------

DELTA_TOLERANCE = 25

# ============================================================
# DISPLAY SETTINGS
# ============================================================

PRE_SAMPLES = 50
POST_SAMPLES = 100

# ============================================================
# STORAGE
# ============================================================

all_detections = []

all_offsets = []

sample_rate = None

# ============================================================
# HELPER FUNCTIONS
# ============================================================

def detect_events(signal):

    """
    Run onset/offset state machine.
    """

    detections = []

    offsets = []

    # ========================================================
    # DYNAMIC THRESHOLD
    # ========================================================

    baseline_region = signal[:NOISE_SAMPLE_COUNT]

    noise_floor = np.mean(np.abs(baseline_region))

    offset_threshold = noise_floor * OFFSET_MULTIPLIER

    # ========================================================
    # SIGN STREAM
    # ========================================================

    signs = np.sign(signal)

    # ========================================================
    # DETECTOR STATE
    # ========================================================

    armed = True

    quiet_counter = 0

    i = 0

    # ========================================================
    # MAIN LOOP
    # ========================================================

    while i < len(signal) - RUN_LENGTH * 2:

        # ====================================================
        # WAITING FOR ONSET
        # ====================================================

        if armed:

            first_block = signs[i:i + RUN_LENGTH]

            second_block = signs[
                i + RUN_LENGTH:
                i + RUN_LENGTH * 2
            ]

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

            # =================================================
            # ONSET DETECTED
            # =================================================

            if valid_pattern:

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

                detections.append(candidate)

                armed = False

                quiet_counter = 0

        # ====================================================
        # WAITING FOR OFFSET
        # ====================================================

        else:

            current_energy = abs(signal[i])

            if current_energy < offset_threshold:

                quiet_counter += 1

            else:

                quiet_counter = 0

            # =================================================
            # OFFSET DETECTED
            # =================================================

            if quiet_counter >= MIN_QUIET_SAMPLES:

                offsets.append(i)

                armed = True

                quiet_counter = 0

        i += 1

    return detections, offsets


# ============================================================
# EVENT MATCHER
# ============================================================

def match_events(all_detections):

    """
    Match physical events across channels.
    """

    reference_channel = all_detections[0]

    matched_events = []

    # ========================================================
    # MATCH EACH REFERENCE EVENT
    # ========================================================

    for ref_event in reference_channel:

        event_row = [ref_event]

        valid_match = True

        # ====================================================
        # SEARCH OTHER CHANNELS
        # ====================================================

        for ch in range(1, len(all_detections)):

            channel_events = all_detections[ch]

            nearest = None

            nearest_error = 1e12

            for event in channel_events:

                error = abs(event - ref_event)

                if error < MATCH_TOLERANCE:

                    if error < nearest_error:

                        nearest = event

                        nearest_error = error

            if nearest is None:

                valid_match = False

                break

            event_row.append(nearest)

        # ====================================================
        # STORE MATCH
        # ====================================================

        if valid_match:

            matched_events.append(event_row)

    return matched_events


# ============================================================
# DELTA VALIDATION
# ============================================================

def validate_event_structure(matched_events):

    """
    Reject structurally inconsistent events.
    """

    validated = []

    validated.append(matched_events[0])

    # ========================================================
    # REFERENCE DELTA STRUCTURE
    # ========================================================

    reference_deltas = []

    for i in range(1, len(matched_events)):

        previous = matched_events[i - 1][0]

        current = matched_events[i][0]

        reference_deltas.append(current - previous)

    # ========================================================
    # VALIDATE
    # ========================================================

    for i in range(1, len(matched_events)):

        current_row = matched_events[i]

        previous_row = matched_events[i - 1]

        valid = True

        for ch in range(len(current_row)):

            current_delta = (

                current_row[ch]
                -
                previous_row[ch]

            )

            reference_delta = reference_deltas[i - 1]

            delta_error = abs(

                current_delta
                -
                reference_delta

            )

            if delta_error > DELTA_TOLERANCE:

                valid = False

                break

        if valid:

            validated.append(current_row)

    return validated


# ============================================================
# RELATIVE DELTA ANALYSIS
# ============================================================

def analyze_relative_deltas(events):

    """
    Compare relative event spacing across channels.
    """

    print("\n")
    print("=" * 70)
    print("RELATIVE DELTA ANALYSIS")
    print("=" * 70)

    for i in range(1, len(events)):

        print("\n")
        print(f"EVENT {i} -> EVENT {i+1}")

        deltas = []

        for ch in range(len(events[i])):

            delta = (

                events[i][ch]
                -
                events[i - 1][ch]

            )

            deltas.append(delta)

            print(
                f"CH{ch+1}: {delta}"
            )

        spread = max(deltas) - min(deltas)

        print(f"\nSpread: {spread} samples")

        spread_time = spread / sample_rate

        print(
            f"Spread Time: "
            f"{spread_time * 1e6:.3f} microseconds"
        )


# ============================================================
# CONSENSUS AVERAGING
# ============================================================

def compute_consensus(events):

    """
    Compute average onset position.
    """

    print("\n")
    print("=" * 70)
    print("CONSENSUS EVENTS")
    print("=" * 70)

    consensus = []

    for i, row in enumerate(events):

        avg = np.mean(row)

        consensus.append(avg)

        print("\n")
        print(f"EVENT {i+1}")

        for ch, onset in enumerate(row):

            residual = onset - avg

            print(

                f"CH{ch+1}: "
                f"{onset} "
                f"(Residual {residual:+.2f})"

            )

        print(f"Consensus: {avg:.2f}")

    return consensus

# ============================================================
# FINAL TDOA ANALYSIS
# ============================================================

def compute_final_tdoa(events):

    """
    Compute final physical TDOA values.

    IMPORTANT:
    This preserves real propagation delays.
    It does NOT remove stable geometry.
    """

    events = np.array(events, dtype=np.float64)

    print("\n")
    print("=" * 70)
    print("FINAL TDOA ANALYSIS")
    print("=" * 70)

    # ========================================================
    # STEP 1:
    # COMPUTE RAW TDOA MATRIX
    # ========================================================

    # --------------------------------------------------------
    # Relative to Channel 1
    # --------------------------------------------------------

    tdoa_matrix = events - events[:, [0]]

    # ========================================================
    # STEP 2:
    # PRINT RAW TDOA MATRIX
    # ========================================================

    print("\n")
    print("=" * 70)
    print("RAW TDOA MATRIX")
    print("=" * 70)

    for i, row in enumerate(tdoa_matrix):

        print("\n")
        print(f"EVENT {i + 1}")

        for ch, value in enumerate(row):

            print(
                f"CH1 -> CH{ch + 1}: "
                f"{value:+.3f} samples"
            )

    # ========================================================
    # STEP 3:
    # COMPUTE MEAN TDOA
    # ========================================================

    mean_tdoa = np.mean(tdoa_matrix, axis=0)

    # ========================================================
    # STEP 4:
    # COMPUTE STANDARD DEVIATION
    # ========================================================

    std_tdoa = np.std(tdoa_matrix, axis=0)

    # ========================================================
    # STEP 5:
    # COMPUTE SAMPLE SPREAD
    # ========================================================

    spread_tdoa = np.max(
        tdoa_matrix,
        axis=0
    ) - np.min(
        tdoa_matrix,
        axis=0
    )

    # ========================================================
    # STEP 6:
    # PRINT FINAL RESULTS
    # ========================================================

    print("\n")
    print("=" * 70)
    print("FINAL AVERAGED TDOA")
    print("=" * 70)

    for ch in range(len(mean_tdoa)):

        samples = mean_tdoa[ch]

        time_seconds = samples / sample_rate

        time_microseconds = time_seconds * 1e6

        distance_error = abs(time_seconds * 343)

        print("\n")
        print(f"CH1 -> CH{ch + 1}")

        print(
            f"Mean Samples : "
            f"{samples:+.3f}"
        )

        print(
            f"Std Samples  : "
            f"{std_tdoa[ch]:.3f}"
        )

        print(
            f"Spread       : "
            f"{spread_tdoa[ch]:.3f} samples"
        )

        print(
            f"Mean Time    : "
            f"{time_microseconds:.3f} us"
        )

        print(
            f"Equivalent Distance : "
            f"{distance_error:.6f} m"
        )

    return (
        tdoa_matrix,
        mean_tdoa,
        std_tdoa,
        spread_tdoa
    )
# ============================================================
# PROCESS FILES
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

    if len(signal.shape) > 1:

        signal = signal[:, 0]

    # ========================================================
    # DETECT EVENTS
    # ========================================================

    detections, offsets = detect_events(signal)

    all_detections.append(detections)

    all_offsets.append(offsets)

    # ========================================================
    # PRINT RESULTS
    # ========================================================

    print("\nONSETS")

    for d in detections:

        print(d)

    print("\nOFFSETS")

    for o in offsets:

        print(o)

    # ========================================================
    # FULL SIGNAL PLOT
    # ========================================================

    plt.figure(figsize=(14, 5))

    plt.plot(signal, linewidth=0.7)

    # --------------------------------------------------------
    # ONSETS
    # --------------------------------------------------------

    for d in detections:

        plt.axvline(

            d,

            linestyle='--',
            linewidth=2,
            alpha=0.9

        )

    # --------------------------------------------------------
    # OFFSETS
    # --------------------------------------------------------

    for o in offsets:

        plt.axvline(

            o,

            linestyle=':',
            linewidth=2,
            alpha=0.9

        )

    plt.title(f"Channel {channel + 1}")

    plt.xlabel("Sample")

    plt.ylabel("Amplitude")

    plt.grid(True)

    plt.show(block=False)

# ============================================================
# RAW DETECTION SUMMARY
# ============================================================

print("\n")
print("=" * 70)
print("RAW DETECTIONS")
print("=" * 70)

for ch, detections in enumerate(all_detections):

    print("\n")
    print(f"CHANNEL {ch+1}")

    print(detections)

# ============================================================
# EVENT MATCHING
# ============================================================

matched_events = match_events(all_detections)

# ============================================================
# PRINT MATCHED EVENTS
# ============================================================

print("\n")
print("=" * 70)
print("MATCHED EVENTS")
print("=" * 70)

for i, row in enumerate(matched_events):

    print("\n")
    print(f"EVENT {i+1}")

    for ch, onset in enumerate(row):

        print(

            f"CH{ch+1}: {onset}"

        )

# ============================================================
# VALIDATE STRUCTURE
# ============================================================

validated_events = validate_event_structure(

    matched_events

)

# ============================================================
# VALIDATED EVENTS
# ============================================================

print("\n")
print("=" * 70)
print("VALIDATED EVENTS")
print("=" * 70)

for i, row in enumerate(validated_events):

    print("\n")
    print(f"EVENT {i+1}")

    for ch, onset in enumerate(row):

        print(

            f"CH{ch+1}: {onset}"

        )

# ============================================================
# RELATIVE DELTA ANALYSIS
# ============================================================

analyze_relative_deltas(validated_events)

# ============================================================
# CONSENSUS ANALYSIS
# ============================================================

consensus_events = compute_consensus(

    validated_events

)
# ============================================================
# FINAL TDOA ANALYSIS
# ============================================================

tdoa_matrix, mean_tdoa, std_tdoa, spread_tdoa = compute_final_tdoa(
    validated_events
)
# ============================================================
# FINAL NOTE
# ============================================================

print("\n")
print("=" * 70)
print("PROCESS COMPLETE")
print("=" * 70)