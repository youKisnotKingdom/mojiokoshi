#!/usr/bin/env python3
"""Generate a noisy PCM16 wav copy at a target SNR."""

from __future__ import annotations

import argparse
import wave
from pathlib import Path

import numpy as np


def read_wav(path: Path) -> tuple[np.ndarray, wave._wave_params]:
    with wave.open(str(path), "rb") as wav_file:
        params = wav_file.getparams()
        if params.sampwidth != 2:
            raise ValueError(f"Only PCM16 wav is supported: {path}")
        frames = wav_file.readframes(params.nframes)
    audio = np.frombuffer(frames, dtype=np.int16).astype(np.float32)
    if params.nchannels > 1:
        audio = audio.reshape(-1, params.nchannels)
    return audio, params


def write_wav(path: Path, audio: np.ndarray, params: wave._wave_params) -> None:
    clipped = np.clip(audio, -32768, 32767).astype(np.int16)
    with wave.open(str(path), "wb") as wav_file:
        wav_file.setparams(params)
        wav_file.writeframes(clipped.tobytes())


def add_noise(audio: np.ndarray, snr_db: float, seed: int) -> np.ndarray:
    rng = np.random.default_rng(seed)
    noise = rng.normal(0.0, 1.0, size=audio.shape).astype(np.float32)
    signal_rms = float(np.sqrt(np.mean(np.square(audio), dtype=np.float64)))
    if signal_rms == 0.0:
        return audio.copy()
    target_noise_rms = signal_rms / (10 ** (snr_db / 20.0))
    noise_rms = float(np.sqrt(np.mean(np.square(noise), dtype=np.float64)))
    scaled_noise = noise * (target_noise_rms / max(noise_rms, 1e-12))
    return audio + scaled_noise


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("input", type=Path)
    parser.add_argument("output", type=Path)
    parser.add_argument("--snr-db", type=float, required=True)
    parser.add_argument("--seed", type=int, default=42)
    return parser.parse_args()


def main() -> None:
    args = parse_args()
    audio, params = read_wav(args.input)
    noisy = add_noise(audio, snr_db=args.snr_db, seed=args.seed)
    args.output.parent.mkdir(parents=True, exist_ok=True)
    write_wav(args.output, noisy, params)
    print(f"wrote noisy wav to {args.output} (snr_db={args.snr_db})")


if __name__ == "__main__":
    main()
