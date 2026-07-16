from __future__ import annotations

from pathlib import Path
from typing import Any

import numpy as np
import soundfile as sf

from .common import load_json, read_ndjson


class SessionAudioReader:
    def __init__(self, session_directory: Path) -> None:
        self.session_directory = session_directory.resolve()
        self.session = load_json(self.session_directory / "session.json")
        self.sample_rate = int(self.session["config"]["audio"]["sample_rate_hz"])
        self.channels = int(self.session["config"]["audio"]["channels"])
        self.chunks = sorted(
            read_ndjson(self.session_directory / "audio_chunks.ndjson"),
            key=lambda item: item["start_sample"],
        )
        if not self.chunks:
            raise ValueError(f"No audio chunks found in {self.session_directory}")
        self.first_sample = int(self.chunks[0]["start_sample"])
        self.end_sample_exclusive = int(self.chunks[-1]["end_sample_exclusive"])

    def read_samples(self, start_sample: int, end_sample_exclusive: int) -> np.ndarray:
        if end_sample_exclusive <= start_sample:
            raise ValueError("end_sample_exclusive must be greater than start_sample.")
        frame_count = end_sample_exclusive - start_sample
        output = np.zeros((frame_count, self.channels), dtype=np.float64)
        covered = np.zeros(frame_count, dtype=bool)

        for chunk in self.chunks:
            chunk_start = int(chunk["start_sample"])
            chunk_end = int(chunk["end_sample_exclusive"])
            overlap_start = max(start_sample, chunk_start)
            overlap_end = min(end_sample_exclusive, chunk_end)
            if overlap_end <= overlap_start:
                continue

            path = self.session_directory / chunk["path"]
            file_offset = overlap_start - chunk_start
            destination_offset = overlap_start - start_sample
            count = overlap_end - overlap_start
            with sf.SoundFile(str(path), mode="r") as handle:
                handle.seek(file_offset)
                data = handle.read(count, dtype="float64", always_2d=True)
            actual = len(data)
            output[destination_offset:destination_offset + actual] = data
            covered[destination_offset:destination_offset + actual] = True

        if not np.all(covered):
            missing = int((~covered).sum())
            raise ValueError(f"Requested range includes {missing} unavailable samples.")
        return output
