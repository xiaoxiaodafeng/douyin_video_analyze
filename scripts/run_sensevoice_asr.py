import argparse
import json
import time
from pathlib import Path

import numpy as np
import soundfile as sf
from funasr import AutoModel
from funasr.utils.postprocess_utils import rich_transcription_postprocess


def main() -> None:
    parser = argparse.ArgumentParser(description="Run local SenseVoice ASR on a full-length wav file.")
    parser.add_argument("--audio", required=True)
    parser.add_argument("--model-dir", required=True)
    parser.add_argument("--output", required=True)
    args = parser.parse_args()

    audio_path = Path(args.audio)
    model_dir = Path(args.model_dir)
    output_path = Path(args.output)

    if not audio_path.exists():
        raise FileNotFoundError(f"audio not found: {audio_path}")
    if not model_dir.exists():
        raise FileNotFoundError(f"model dir not found: {model_dir}")

    start_all = time.time()
    audio, sr = sf.read(str(audio_path), dtype="float32")
    if getattr(audio, "ndim", 1) > 1:
        audio = audio.mean(axis=1)
    audio = np.asarray(audio, dtype=np.float32)
    if sr != 16000:
        raise RuntimeError(f"expected 16000Hz wav, got {sr}")

    load_model_start = time.time()
    model = AutoModel(
        model=str(model_dir),
        trust_remote_code=False,
        device="cpu",
        disable_update=True,
    )
    model_load_seconds = time.time() - load_model_start

    generate_start = time.time()
    res = model.generate(
        input=audio,
        cache={},
        language="auto",
        use_itn=True,
        batch_size=1,
    )
    generate_seconds = time.time() - generate_start

    segments = []
    texts = []
    for idx, item in enumerate(res):
        raw = item.get("text", "") if isinstance(item, dict) else str(item)
        try:
            text = rich_transcription_postprocess(raw)
        except Exception:
            text = raw
        text = str(text).strip()
        segments.append({"index": idx, "text": text})
        if text:
            texts.append(text)

    transcript = "\n".join(texts).strip()
    duration_seconds = round(len(audio) / sr, 2)
    total_seconds = round(time.time() - start_all, 2)
    generate_seconds = round(generate_seconds, 2)
    model_load_seconds = round(model_load_seconds, 2)
    rtf = round(generate_seconds / duration_seconds, 4) if duration_seconds else 0.0

    payload = {
        "ok": True,
        "transcript": transcript,
        "segments": segments,
        "duration_seconds": duration_seconds,
        "sample_rate": sr,
        "model_dir": str(model_dir),
        "metrics": {
            "total_seconds": total_seconds,
            "model_load_seconds": model_load_seconds,
            "generate_seconds": generate_seconds,
            "rtf": rtf,
        },
    }
    output_path.parent.mkdir(parents=True, exist_ok=True)
    output_path.write_text(json.dumps(payload, ensure_ascii=False, indent=2), encoding="utf-8")


if __name__ == "__main__":
    main()
