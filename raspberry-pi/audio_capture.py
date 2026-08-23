"""
Audio capture for the Raspberry Pi.

Rewritten from the original project's AudioRecorder with the three things a
real shop deployment needs:

  * the input device is configurable, by index or by name substring, because
    nobody knows which microphone will be plugged in
  * a cheap RMS voice-activity gate, so the Pi does not upload eight hours of
    silence a day over a shop WiFi connection
  * it fails with an explanation instead of a traceback when there is no
    microphone, so the client can carry on in demo mode

sounddevice and soundfile are imported lazily. That keeps `pi_client.py
--help`, `--list-devices` and demo mode working on a machine with no
PortAudio installed at all.
"""

from __future__ import annotations

import wave
from pathlib import Path
from typing import Optional

import config


class AudioUnavailable(RuntimeError):
    """No usable microphone, or the audio stack is not installed."""


def _sounddevice():
    try:
        import sounddevice as sd
    except (ImportError, OSError) as exc:
        # OSError here means PortAudio itself is missing, which is a different
        # problem from the Python package being absent, and needs a different
        # fix (apt install libportaudio2).
        raise AudioUnavailable(
            "sounddevice is unavailable. On a Pi:\n"
            "    sudo apt install -y libportaudio2\n"
            "    pip install -r requirements-pi.txt\n"
            f"Underlying error: {type(exc).__name__}: {exc}"
        ) from exc
    return sd


def list_devices() -> str:
    """Human-readable input device list, for `--list-devices`."""
    try:
        sd = _sounddevice()
    except AudioUnavailable as exc:
        return str(exc)

    lines = ["Input devices visible to sounddevice:", ""]
    try:
        for index, device in enumerate(sd.query_devices()):
            if device.get("max_input_channels", 0) < 1:
                continue
            default = ""
            try:
                if index == sd.default.device[0]:
                    default = "  <- system default"
            except (TypeError, IndexError):
                pass
            lines.append(
                f"  [{index}] {device['name']}  "
                f"({device['max_input_channels']} ch, "
                f"{int(device.get('default_samplerate', 0))} Hz){default}"
            )
    except Exception as exc:  # noqa: BLE001
        return f"Could not query audio devices: {type(exc).__name__}: {exc}"

    if len(lines) == 2:
        lines.append("  (none found - is the microphone plugged in?)")
    lines += ["", "Set AUDIO_DEVICE to an index or part of a device name.", "Also try: arecord -l"]
    return "\n".join(lines)


def resolve_device(spec: str) -> Optional[int]:
    """
    Turn AUDIO_DEVICE into a device index.

    Accepts an index ("1"), a name substring ("USB"), or empty for the system
    default. Matching by name matters more than it sounds: USB device indices
    shuffle between reboots, but the name does not.
    """
    spec = (spec or "").strip()
    if not spec:
        return None

    sd = _sounddevice()

    if spec.isdigit():
        index = int(spec)
        devices = sd.query_devices()
        if index >= len(devices) or devices[index].get("max_input_channels", 0) < 1:
            raise AudioUnavailable(
                f"Device index {index} is not a usable input.\n\n{list_devices()}"
            )
        return index

    needle = spec.lower()
    for index, device in enumerate(sd.query_devices()):
        if device.get("max_input_channels", 0) < 1:
            continue
        if needle in device["name"].lower():
            return index

    raise AudioUnavailable(
        f"No input device matching '{spec}'.\n\n{list_devices()}"
    )


def rms(samples) -> float:
    """Root-mean-square level of a float32 buffer, 0.0 to about 1.0."""
    import numpy as np

    if samples.size == 0:
        return 0.0
    return float(np.sqrt(np.mean(np.square(samples, dtype="float64"))))


def has_speech(samples) -> tuple[bool, float]:
    """
    Is there plausibly a voice in this chunk?

    Deliberately crude: overall level plus the share of 30 ms frames above
    the threshold. Speech is bursty, so a chunk with a few loud frames is
    more interesting than one with a constant hum at the same average level.
    The real decision is Whisper's; this only avoids the upload.
    """
    import numpy as np

    if not config.VAD_ENABLED:
        return True, rms(samples)

    flat = samples.reshape(-1)
    overall = rms(flat)

    frame = max(1, int(config.SAMPLE_RATE * 0.03))
    usable = (flat.size // frame) * frame
    if usable == 0:
        return overall >= config.VAD_RMS_THRESHOLD, overall

    frames = flat[:usable].reshape(-1, frame)
    levels = np.sqrt(np.mean(np.square(frames, dtype="float64"), axis=1))
    voiced_ratio = float(np.mean(levels >= config.VAD_RMS_THRESHOLD))

    return voiced_ratio >= config.VAD_MIN_VOICED_RATIO, overall


class AudioRecorder:
    """Records fixed-length chunks to 16-bit PCM WAV files."""

    def __init__(
        self,
        duration: float = config.RECORDING_DURATION,
        sample_rate: int = config.SAMPLE_RATE,
        channels: int = config.CHANNELS,
        device: Optional[int] = None,
        output_dir: Path = config.TEMP_DIR,
    ) -> None:
        self.duration = duration
        self.sample_rate = sample_rate
        self.channels = channels
        self.device = device
        self.output_dir = Path(output_dir)
        self.output_dir.mkdir(parents=True, exist_ok=True)

    @classmethod
    def from_config(cls) -> "AudioRecorder":
        return cls(device=resolve_device(config.AUDIO_DEVICE))

    def record(self, path: Path) -> tuple[Path, bool, float]:
        """
        Record one chunk.

        Returns (path, speech_detected, rms_level). The file is written even
        when no speech is detected, so the caller decides what to do with it.
        """
        sd = _sounddevice()
        import numpy as np

        frames = int(self.duration * self.sample_rate)
        try:
            buffer = sd.rec(
                frames,
                samplerate=self.sample_rate,
                channels=self.channels,
                dtype="float32",
                device=self.device,
            )
            sd.wait()
        except Exception as exc:  # noqa: BLE001
            raise AudioUnavailable(
                f"Recording failed: {type(exc).__name__}: {exc}\n\n{list_devices()}"
            ) from exc

        speech, level = has_speech(buffer)

        # Write 16-bit PCM through the stdlib rather than soundfile: it is one
        # less binary dependency on the Pi, and this is the only format needed.
        clipped = np.clip(buffer, -1.0, 1.0)
        pcm = (clipped * 32767).astype("<i2")

        path.parent.mkdir(parents=True, exist_ok=True)
        with wave.open(str(path), "wb") as handle:
            handle.setnchannels(self.channels)
            handle.setsampwidth(2)
            handle.setframerate(self.sample_rate)
            handle.writeframes(pcm.tobytes())

        return path, speech, level


def self_test() -> int:
    """`python audio_capture.py` records one chunk and reports on it."""
    print(list_devices())
    print()
    try:
        recorder = AudioRecorder.from_config()
    except AudioUnavailable as exc:
        print(f"[!] {exc}")
        return 1

    target = config.TEMP_DIR / "self_test.wav"
    print(f"[*] Recording {config.RECORDING_DURATION:g}s ... speak now")
    try:
        path, speech, level = recorder.record(target)
    except AudioUnavailable as exc:
        print(f"[!] {exc}")
        return 1

    print(f"[*] Wrote {path} ({path.stat().st_size:,} bytes)")
    print(f"[*] RMS level {level:.4f}, speech detected: {speech}")
    if level < 0.001:
        print("[!] That is essentially silence. Check the mic, or raise the")
        print("    input volume with `alsamixer` (F4 for capture).")
    return 0


if __name__ == "__main__":
    raise SystemExit(self_test())
