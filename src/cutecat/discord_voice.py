from __future__ import annotations

import tempfile
from pathlib import Path


async def transcribe(cfg: dict, attachment) -> str:
    dcfg = cfg.get("discord") or {}
    mode = (dcfg.get("stt") or "").lower()
    if mode not in ("local", "api"):
        return ("(a voice message was sent, but voice transcription is off — set "
                "discord.stt to \"local\" or \"api\" in config to enable it)")
    try:
        audio = await attachment.read()
    except Exception as exc:  # noqa: BLE001
        return f"(could not read the voice message: {exc})"

    import asyncio

    try:
        if mode == "local":
            size = (dcfg.get("stt_local_model") or "base").strip()
            text = await asyncio.to_thread(
                _transcribe_local, audio, attachment.filename, size)
        else:
            text = await asyncio.to_thread(_transcribe_api, cfg, audio, attachment.filename)
    except Exception as exc:  # noqa: BLE001
        return f"(could not transcribe the voice message: {exc})"
    return text.strip() or "(the voice message was empty or silent)"


def to_wav(audio: bytes) -> bytes | None:
    import io

    try:
        import av
    except ImportError:
        return None

    try:
        with av.open(io.BytesIO(audio)) as src:
            if not src.streams.audio:
                return None
            buf = io.BytesIO()
            with av.open(buf, mode="w", format="wav") as dst:
                # 16k mono is what speech models want anyway, and it keeps the
                # base64 payload small
                out = dst.add_stream("pcm_s16le", rate=16000, layout="mono")
                resampler = av.AudioResampler(
                    format="s16", layout="mono", rate=16000)
                for frame in src.decode(audio=0):
                    for chunk in resampler.resample(frame):
                        chunk.pts = None
                        for packet in out.encode(chunk):
                            dst.mux(packet)
                for packet in out.encode(None):
                    dst.mux(packet)
        return buf.getvalue() or None
    except Exception:  # noqa: BLE001 — a bad recording is not worth a crash
        return None


_MODELS: dict[str, object] = {}


def _local_model(size: str):
    if size not in _MODELS:
        try:
            from faster_whisper import WhisperModel
        except Exception as exc:  # noqa: BLE001 — a native .so may fail to load too
            raise RuntimeError(
                f"local voice transcription is unavailable "
                f"({type(exc).__name__}: {exc}). "
                "From a pip install, run: pip install 'cutecat[voice]'. "
                "In the standalone binary the library is bundled, so this "
                "usually means a system library is missing (e.g. 'apt install "
                "libgomp1')."
            ) from exc
        _MODELS[size] = WhisperModel(size, device="cpu", compute_type="int8")
    return _MODELS[size]


def _transcribe_local(audio: bytes, filename: str, size: str = "base") -> str:
    model = _local_model(size)
    with tempfile.NamedTemporaryFile(suffix=Path(filename).suffix or ".ogg",
                                     delete=False) as fh:
        fh.write(audio)
        path = fh.name
    try:
        segments, _info = model.transcribe(path)
        return " ".join(seg.text for seg in segments)
    finally:
        try:
            Path(path).unlink()
        except OSError:
            pass


def _transcribe_api(cfg: dict, audio: bytes, filename: str) -> str:
    import requests

    dcfg = cfg.get("discord") or {}
    base = dcfg.get("stt_url") or "https://api.openai.com/v1"
    model = dcfg.get("stt_model") or "whisper-1"
    key = (
        dcfg.get("stt_key")
        or (cfg.get("api_keys") or {}).get("openai")
        or (cfg.get("api_keys") or {}).get("groq")
    )
    if not key:
        raise RuntimeError(
            "api transcription needs a key — connect OpenAI, or set discord.stt_key")
    resp = requests.post(
        f"{base}/audio/transcriptions",
        headers={"Authorization": f"Bearer {key}"},
        files={"file": (filename or "voice.ogg", audio)},
        data={"model": model},
        timeout=120,
    )
    if resp.status_code >= 400:
        raise RuntimeError(f"transcription API returned HTTP {resp.status_code}")
    return resp.json().get("text", "")
