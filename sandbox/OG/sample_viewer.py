import numpy as np
import matplotlib.pyplot as plt
from scipy.io import wavfile

# =====================================================
# LOAD WAV
# =====================================================

sample_rate, data = wavfile.read("01-260521_1437.wav")

# Select channel
channel = data[:]

# =====================================================
# SAMPLE WINDOW
# =====================================================

start = 374750
end   = 374910

window = channel[start:end]

# =====================================================
# DELTA BETWEEN SAMPLES
# =====================================================

delta = np.diff(window)

print("\nSample-to-Sample Change")
print("--------------------------")

for i, value in enumerate(delta):
    sample_num = start + i + 1
    print(f"{sample_num:<10} {value}")

# =====================================================
# PRINT SAMPLES
# =====================================================

print("\nSample     Amplitude")
print("----------------------")

for i, value in enumerate(window):
    sample_num = start + i
    print(f"{sample_num:<10} {value}")

# =====================================================
# PLOT
# =====================================================

x = np.arange(start, end)

plt.figure(figsize=(12,5))
plt.plot(x, window, marker='o')

plt.xlabel("Sample Number")
plt.ylabel("Amplitude")
plt.title("Sample-Level Onset Inspection")

plt.grid(True)

plt.show()
