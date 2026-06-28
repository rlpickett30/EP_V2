#!/usr/bin/env python3
"""
dev_5s_spectrogram_test.py

EnviroPulse V2

Purpose:
    Record one controlled short USB microphone sample and generate local
    spectrogram images for visual tuning before runtime integration.

Does:
    - Records one WAV from a selected microphone device.
    - Saves several matplotlib spectrogram image styles for comparison.
    - Avoids EventBus, BirdNET, scheduler, PPS, GUI, and server paths.
"""

from __future__ import annotations

import argparse
import wave
from datetime import datetime
from pathlib import Path

import numpy as np
import sounddevice as sd


def utc_safe_timestamp() -> str:
    return datetime.utcnow().isoformat(timespec="seconds").replace(":", "-")


def write_wav(path: Path, audio: np.ndarray, sample_rate: int, channels: int) -> None:
    audio = np.asarray(audio)

    if audio.dtype != np.int16:
        audio = audio.astype(np.float32)
        peak = float(np.max(np.abs(audio))) if audio.size else 0.0

        if peak > 0:
            audio = audio / peak

        audio = np.clip(audio, -1.0, 1.0)
        audio = (audio * 32767).astype(np.int16)

    path.parent.mkdir(parents=True, exist_ok=True)

    with wave.open(str(path), "wb") as wav_file:
        wav_file.setnchannels(channels)
        wav_file.setsampwidth(2)
        wav_file.setframerate(sample_rate)
        wav_file.writeframes(audio.tobytes())


def make_custom_ep_cmap():
    from matplotlib.colors import LinearSegmentedColormap

    colors = [
        "#000000",
        "#090018",
        "#24004e",
        "#5c008c",
        "#aa18b0",
        "#ee5cb0",
        "#ffaa5a",
        "#fff2d2",
    ]

    return LinearSegmentedColormap.from_list(
        "ep_purple_pink_yellow",
        colors,
        N=256,
    )


def generate_spectrogram(
    audio: np.ndarray,
    sample_rate: int,
    output_path: Path,
    cmap,
    title: str,
    max_frequency_hz: int = 6000,
    nfft: int = 2048,
    noverlap: int = 1536,
    dpi: int = 150,
) -> None:
    import matplotlib

    matplotlib.use("Agg")

    import matplotlib.pyplot as plt

    samples = np.asarray(audio)

    if samples.ndim > 1:
        samples = samples[:, 0]

    samples = samples.astype(np.float32)

    if samples.size == 0:
        raise ValueError("Cannot generate spectrogram from empty audio.")

    samples = samples - float(np.mean(samples))
    peak = float(np.max(np.abs(samples)))

    if peak > 0:
        samples = samples / peak

    fig, ax = plt.subplots(figsize=(8.0, 4.0), dpi=dpi)
    fig.patch.set_facecolor("white")
    ax.set_facecolor("black")

    ax.specgram(
        samples,
        NFFT=nfft,
        Fs=sample_rate,
        noverlap=noverlap,
        cmap=cmap,
    )

    ax.set_title(title)
    ax.set_xlabel("Time (s)")
    ax.set_ylabel("Frequency (kHz)")
    ax.set_ylim(0, max_frequency_hz)

    ticks = ax.get_yticks()
    ax.set_yticks(ticks)
    ax.set_yticklabels([f"{tick / 1000.0:g}" for tick in ticks])

    ax.grid(False)
    fig.tight_layout()
    fig.savefig(str(output_path))
    plt.close(fig)


def main() -> int:
    parser = argparse.ArgumentParser(
        description="Record one controlled USB microphone sample and generate spectrograms."
    )

    parser.add_argument("--device", type=int, default=2)
    parser.add_argument("--duration", type=float, default=5.0)
    parser.add_argument("--sample-rate", type=int, default=48000)
    parser.add_argument("--channels", type=int, default=1)
    parser.add_argument("--out", default="dev_spectrogram_tests")

    args = parser.parse_args()

    output_root = Path(args.out)
    timestamp = utc_safe_timestamp()
    wav_path = output_root / f"dev_{args.duration:g}s_{timestamp}_device_{args.device}.wav"

    print()
    print("EnviroPulse controlled spectrogram test")
    print("---------------------------------------")
    print(f"Device:      {args.device}")
    print(f"Duration:    {args.duration:.3f} seconds")
    print(f"Sample rate: {args.sample_rate}")
    print(f"Channels:    {args.channels}")
    print(f"Output:      {output_root}")
    print()
    print("Recording now...")

    frame_count = int(args.duration * args.sample_rate)

    audio = sd.rec(
        frame_count,
        samplerate=args.sample_rate,
        channels=args.channels,
        dtype="int16",
        device=args.device,
    )

    sd.wait()

    print("Recording complete.")

    write_wav(
        path=wav_path,
        audio=audio,
        sample_rate=args.sample_rate,
        channels=args.channels,
    )

    print(f"WAV written: {wav_path}")

    styles = {
        "magma": "magma",
        "inferno": "inferno",
        "plasma": "plasma",
        "ep_purple_pink_yellow": make_custom_ep_cmap(),
    }

    for style_name, cmap in styles.items():
        png_path = output_root / f"dev_{args.duration:g}s_{timestamp}_{style_name}.png"

        generate_spectrogram(
            audio=audio,
            sample_rate=args.sample_rate,
            output_path=png_path,
            cmap=cmap,
            title=f"EnviroPulse Spectrogram Test - {style_name}",
        )

        print(f"Spectrogram written: {png_path}")

    print()
    print("Done.")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
