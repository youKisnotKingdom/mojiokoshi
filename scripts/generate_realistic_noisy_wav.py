#!/usr/bin/env python3
"""Generate babble / reverb corrupted wav files for ASR robustness checks."""

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


def rms(x: np.ndarray) -> float:
    return float(np.sqrt(np.mean(np.square(x), dtype=np.float64)))


def fit_length(audio: np.ndarray, target_len: int, offset: int = 0) -> np.ndarray:
    if audio.ndim != 1:
        raise ValueError("Only mono wav is supported.")
    out = np.zeros(target_len, dtype=np.float32)
    if len(audio) == 0:
        return out
    start = max(0, offset)
    if start >= target_len:
        return out
    remaining = target_len - start
    if len(audio) >= remaining:
        out[start:] = audio[:remaining]
        return out
    tiled = np.resize(audio, remaining)
    out[start:] = tiled
    return out


def add_babble(clean: np.ndarray, babble_sources: list[np.ndarray], snr_db: float) -> np.ndarray:
    if not babble_sources:
        return clean.copy()
    total = np.zeros_like(clean, dtype=np.float32)
    step = max(1, len(clean) // (len(babble_sources) * 3))
    for idx, source in enumerate(babble_sources):
        total += fit_length(source, len(clean), offset=idx * step)
    total_rms = rms(total)
    if total_rms == 0.0:
        return clean.copy()
    target_noise_rms = rms(clean) / (10 ** (snr_db / 20.0))
    return clean + total * (target_noise_rms / max(total_rms, 1e-12))


def apply_rir(clean: np.ndarray, rir: np.ndarray) -> np.ndarray:
    if rir.ndim != 1:
        raise ValueError("Only mono RIR wav is supported.")
    rir = rir.astype(np.float32)
    peak = np.max(np.abs(rir))
    if peak > 0:
        rir = rir / peak
    convolved = np.convolve(clean, rir, mode="full")[: len(clean)]
    clean_rms = rms(clean)
    conv_rms = rms(convolved)
    if clean_rms == 0.0 or conv_rms == 0.0:
        return convolved
    return convolved * (clean_rms / conv_rms)


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("clean", type=Path)
    parser.add_argument("output", type=Path)
    parser.add_argument("--babble", type=Path, nargs="*", default=[])
    parser.add_argument("--babble-snr-db", type=float, default=10.0)
    parser.add_argument("--rir", type=Path, default=None)
    return parser.parse_args()


def main() -> None:
    args = parse_args()
    clean, params = read_wav(args.clean)
    if clean.ndim != 1:
        raise ValueError("Only mono wav is supported.")
    audio = clean.copy()
    if args.rir is not None:
        rir, _ = read_wav(args.rir)
        if rir.ndim > 1:
            rir = rir[:, 0]
        audio = apply_rir(audio, rir)
    if args.babble:
        babble_sources = []
        for babble_path in args.babble:
            babble_audio, _ = read_wav(babble_path)
            if babble_audio.ndim > 1:
                babble_audio = babble_audio[:, 0]
            babble_sources.append(babble_audio)
        audio = add_babble(audio, babble_sources, snr_db=args.babble_snr_db)
    args.output.parent.mkdir(parents=True, exist_ok=True)
    write_wav(args.output, audio, params)
    print(f"wrote realistic noisy wav to {args.output}")


if __name__ == "__main__":
    main()
