import numpy as np
from scipy.optimize import minimize
import matplotlib.pyplot as plt
from mpl_toolkits.mplot3d import Axes3D

# ============================================================
# AUDIO SETTINGS
# ============================================================

SAMPLE_RATE = 96000       # Hz
SPEED_OF_SOUND = 339    # m/s

# ============================================================
# MICROPHONE POSITIONS (meters)
# Replace with your real coordinates
# ============================================================

mic_positions = np.array([
    [0.0, 0.0, 0.0],    # Mic 0 (reference)
    [-8.5352, 0.0, 0.2],    # Mic 1
    [-8.5352, -4.8768, 0.4],    # Mic 2
    [0.0, -4.8768, 0.6],    # Mic 3
    [-4.2726, -2.4384 , .9906]     # Mic 4 (raised in Z)
])

# ============================================================
# SAMPLE OFFSETS
#
# Relative to Mic 0
#
# Example:
# sample_offsets[0] = sample index difference
# between Mic1 and Mic0
# ============================================================

sample_offsets = np.array([

    485,     # Mic1 - Mic0

    45,     # Mic2 - Mic0

    -690.5,     # Mic3 - Mic0

    -834       # Mic4 - Mic0

])

# ============================================================
# CONVERT SAMPLES -> TIME
# ============================================================

tdoa = sample_offsets / SAMPLE_RATE

# ============================================================
# CONVERT TIME -> DISTANCE DIFFERENCE
# ============================================================

delta_d = SPEED_OF_SOUND * tdoa

# ============================================================
# ERROR FUNCTION
# ============================================================

def error_function(source_pos):

    ref_distance = np.linalg.norm(
        source_pos - mic_positions[0]
    )

    error = 0.0

    for i in range(1, len(mic_positions)):

        current_distance = np.linalg.norm(
            source_pos - mic_positions[i]
        )

        predicted_delta = (
            current_distance - ref_distance
        )

        measured_delta = delta_d[i - 1]

        error += (
            predicted_delta - measured_delta
        ) ** 2

    return error

# ============================================================
# INITIAL GUESS
# ============================================================

initial_guess = np.array([

    2.0,
    1.5,
    1.0

])

# ============================================================
# SOLVE
# ============================================================

result = minimize(
    error_function,
    initial_guess
)

estimated_source = result.x

# ============================================================
# PRINT RESULTS
# ============================================================

print("\n===================================")
print("3D TDOA ESTIMATED SOURCE LOCATION")
print("===================================")

print(f"X = {estimated_source[0]:.3f} m")
print(f"Y = {estimated_source[1]:.3f} m")
print(f"Z = {estimated_source[2]:.3f} m")

print("\nOptimization Success:", result.success)
print("Residual Error:", result.fun)

# ============================================================
# 3D PLOT
# ============================================================

fig = plt.figure(figsize=(10, 8))

ax = fig.add_subplot(
    111,
    projection='3d'
)

# ------------------------------------------------------------
# Plot microphones
# ------------------------------------------------------------

ax.scatter(

    mic_positions[:, 0],
    mic_positions[:, 1],
    mic_positions[:, 2],

    s=120,
    marker='o',
    label='Microphones'

)

# ------------------------------------------------------------
# Label microphones
# ------------------------------------------------------------

for i, mic in enumerate(mic_positions):

    ax.text(

        mic[0],
        mic[1],
        mic[2],

        f"Mic {i}",

        fontsize=10

    )

# ------------------------------------------------------------
# Plot estimated source
# ------------------------------------------------------------

ax.scatter(

    estimated_source[0],
    estimated_source[1],
    estimated_source[2],

    s=200,
    marker='*',
    label='Estimated Source'

)

# ------------------------------------------------------------
# Axis Labels
# ------------------------------------------------------------

ax.set_xlabel("X Position (m)")
ax.set_ylabel("Y Position (m)")
ax.set_zlabel("Z Position (m)")

ax.set_title("3D TDOA Localization")

ax.legend()

plt.show()
