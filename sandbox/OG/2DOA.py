import numpy as np
from scipy.optimize import least_squares
import matplotlib.pyplot as plt

# =====================================================
# SETTINGS
# =====================================================

SAMPLE_RATE = 96000

# Your measured speed of sound from today's experiment
SPEED_OF_SOUND = 343.3  # m/s

# =====================================================
# MICROPHONE POSITIONS
# Units: meters
#
# Example square:
# Mic 1 ----- Mic 2
#   |           |
# Mic 4 ----- Mic 3
# =====================================================

side_length = 10

mic_positions = np.array([
    [0.0, 0.0],                 # Mic 1
    [side_length, 0.0],         # Mic 2
    [side_length, side_length], # Mic 3
    [0.0, side_length]          # Mic 4
])

# =====================================================
# ARRIVAL TIMES
# Use Mic 1 as the reference.
#
# If sound was made near Mic 1:
# Mic 1 should arrive first.
#
# Replace these with your measured sample offsets.
# =====================================================

arrival_samples = np.array([
    0,       # Mic 1 reference
    0,    # Mic 2 delay relative to Mic 1
    1736,    # Mic 3 delay relative to Mic 1, placeholder
    1736     # Mic 4 delay relative to Mic 1, placeholder
])

arrival_times = arrival_samples / SAMPLE_RATE

# Convert arrival times into distance differences
distance_differences = SPEED_OF_SOUND * arrival_times

# =====================================================
# TDOA RESIDUAL FUNCTION
# =====================================================

def residuals(source_xy):
    source_xy = np.array(source_xy)

    distances = np.linalg.norm(mic_positions - source_xy, axis=1)

    reference_distance = distances[0]

    predicted_differences = distances - reference_distance

    return predicted_differences - distance_differences


# =====================================================
# SOLVE
# =====================================================

initial_guess = np.array([
    side_length / 2,
    side_length / 2
])

result = least_squares(
    residuals,
    initial_guess
)

estimated_source = result.x

print("\nEstimated source location:")
print(f"x = {estimated_source[0]:.4f} m")
print(f"y = {estimated_source[1]:.4f} m")

print("\nIn feet:")
print(f"x = {estimated_source[0] * 3.28084:.2f} ft")
print(f"y = {estimated_source[1] * 3.28084:.2f} ft")

print("\nResiduals in meters:")
print(result.fun)

# =====================================================
# PLOT
# =====================================================

plt.figure(figsize=(8, 8))

plt.scatter(
    mic_positions[:, 0],
    mic_positions[:, 1],
    s=120,
    label="Microphones"
)

for i, pos in enumerate(mic_positions):
    plt.text(
        pos[0] + 0.2,
        pos[1] + 0.2,
        f"Mic {i + 1}"
    )

plt.scatter(
    estimated_source[0],
    estimated_source[1],
    s=160,
    marker="x",
    label="Estimated Sound Source"
)

plt.xlabel("x position (m)")
plt.ylabel("y position (m)")
plt.title("2D TDOA Source Estimate")

plt.axis("equal")
plt.grid(True)
plt.legend()
plt.show()