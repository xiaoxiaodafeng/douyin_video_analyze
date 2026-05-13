import argparse
import json
from pathlib import Path

import cv2
import numpy as np
from rapidocr_onnxruntime import RapidOCR


FACE_CASCADE = cv2.CascadeClassifier(cv2.data.haarcascades + "haarcascade_frontalface_default.xml")
OCR_ENGINE = RapidOCR()


def _dominant_tone(avg_bgr: np.ndarray) -> str:
    b, g, r = [float(x) for x in avg_bgr]
    if max(b, g, r) - min(b, g, r) < 12:
        return "low-sat gray"
    if r >= g and r >= b:
        return "warm red-orange"
    if g >= r and g >= b:
        return "natural green"
    return "cool blue-gray"


def summarize_frame(image: np.ndarray) -> dict:
    gray = cv2.cvtColor(image, cv2.COLOR_BGR2GRAY)
    hsv = cv2.cvtColor(image, cv2.COLOR_BGR2HSV)
    brightness = float(np.mean(gray))
    saturation = float(np.mean(hsv[:, :, 1]))
    edge = cv2.Canny(gray, 80, 160)
    edge_density = float(np.mean(edge > 0))
    h, w = gray.shape

    center_crop = gray[int(h * 0.2): int(h * 0.8), int(w * 0.2): int(w * 0.8)]
    center_edge = cv2.Canny(center_crop, 80, 160)
    center_edge_density = float(np.mean(center_edge > 0)) if center_crop.size else edge_density

    bottom_crop = gray[int(h * 0.76):, :]
    bottom_edge = cv2.Canny(bottom_crop, 80, 160) if bottom_crop.size else edge
    subtitle_band_density = float(np.mean(bottom_edge > 0)) if bottom_crop.size else 0.0

    faces = FACE_CASCADE.detectMultiScale(gray, scaleFactor=1.08, minNeighbors=4, minSize=(36, 36))
    face_count = int(len(faces))

    small = cv2.resize(image, (64, 64))
    avg_bgr = np.mean(small.reshape(-1, 3), axis=0)
    return {
        "brightness": round(brightness, 2),
        "saturation": round(saturation, 2),
        "edge_density": round(edge_density, 4),
        "center_edge_density": round(center_edge_density, 4),
        "subtitle_band_density": round(subtitle_band_density, 4),
        "face_count": face_count,
        "avg_bgr": [round(float(x), 2) for x in avg_bgr],
        "dominant_tone": _dominant_tone(avg_bgr),
    }


def run_ocr(image_path: Path) -> list[dict]:
    result, _ = OCR_ENGINE(str(image_path))
    rows = []
    for item in result or []:
        if not item or len(item) < 3:
            continue
        text = str(item[1] or "").strip()
        score = float(item[2] or 0)
        if not text:
            continue
        rows.append({"text": text, "score": round(score, 4)})
    return rows


def frame_observation(metrics: dict) -> str:
    light_text = "bright" if metrics["brightness"] >= 145 else "dark" if metrics["brightness"] <= 95 else "balanced light"
    color_text = "high saturation" if metrics["saturation"] >= 110 else "low saturation" if metrics["saturation"] <= 60 else "medium saturation"
    subject_text = "subject centered" if metrics["center_edge_density"] >= metrics["edge_density"] * 1.12 else "subject spread out"
    subtitle_text = "subtitle band likely" if metrics["subtitle_band_density"] >= 0.018 else "subtitle band weak"
    face_text = f"{metrics['face_count']} face(s) detected" if metrics["face_count"] > 0 else "no obvious face"
    return f"{light_text}, {color_text}, {subject_text}, {subtitle_text}, {face_text}, tone {metrics['dominant_tone']}."


def compute_scene_change_score(images: list[np.ndarray]) -> float:
    if len(images) < 2:
        return 0.0
    diffs = []
    prev = None
    for image in images:
        hsv = cv2.cvtColor(cv2.resize(image, (96, 96)), cv2.COLOR_BGR2HSV)
        hist = cv2.calcHist([hsv], [0, 1], None, [24, 24], [0, 180, 0, 256])
        hist = cv2.normalize(hist, hist).flatten()
        if prev is not None:
            diff = 1.0 - float(cv2.compareHist(prev, hist, cv2.HISTCMP_CORREL))
            diffs.append(max(0.0, diff))
        prev = hist
    return round(float(np.mean(diffs)) if diffs else 0.0, 4)


def build_visual_style(frames: list[dict], scene_change_score: float) -> str:
    if not frames:
        return "no key frames extracted"
    brightness = float(np.mean([f["metrics"]["brightness"] for f in frames]))
    saturation = float(np.mean([f["metrics"]["saturation"] for f in frames]))
    edge_density = float(np.mean([f["metrics"]["edge_density"] for f in frames]))
    center_edge_density = float(np.mean([f["metrics"]["center_edge_density"] for f in frames]))
    subtitle_band_density = float(np.mean([f["metrics"]["subtitle_band_density"] for f in frames]))
    face_count = float(np.mean([f["metrics"]["face_count"] for f in frames]))
    tones: dict[str, int] = {}
    for f in frames:
        tone = str(f["metrics"].get("dominant_tone") or "unknown")
        tones[tone] = tones.get(tone, 0) + 1

    light_text = "overall bright" if brightness >= 140 else "overall dark" if brightness <= 95 else "balanced exposure"
    color_text = "rich color" if saturation >= 110 else "muted color" if saturation <= 65 else "mid color"
    shot_text = "detail-heavy frames" if edge_density >= 0.12 else "cleaner frames with clearer focus"
    center_text = "subject mostly centered" if center_edge_density >= edge_density * 1.08 else "subject distribution more even"
    subtitle_text = "visible subtitle or copy band" if subtitle_band_density >= 0.018 else "subtitle presence weak"
    face_text = "human subject appears frequently" if face_count >= 0.5 else "human subject appears less often"
    scene_text = "faster scene switching" if scene_change_score >= 0.22 else "steadier scene rhythm"
    main_tone = max(tones.items(), key=lambda kv: kv[1])[0] if tones else "unknown"
    return f"{light_text}, {color_text}, {shot_text}, {center_text}, {subtitle_text}, {face_text}, {scene_text}, dominant tone {main_tone}."


def main() -> None:
    parser = argparse.ArgumentParser(description="Extract key frames and basic visual metrics from a video.")
    parser.add_argument("--video", required=True)
    parser.add_argument("--output", required=True)
    parser.add_argument("--frames-dir", required=True)
    parser.add_argument("--max-frames", type=int, default=6)
    args = parser.parse_args()

    video_path = Path(args.video)
    output_path = Path(args.output)
    frames_dir = Path(args.frames_dir)
    frames_dir.mkdir(parents=True, exist_ok=True)

    if not video_path.exists():
        raise FileNotFoundError(f"video not found: {video_path}")

    cap = cv2.VideoCapture(str(video_path))
    if not cap.isOpened():
        raise RuntimeError(f"unable to open video: {video_path}")

    fps = cap.get(cv2.CAP_PROP_FPS) or 25.0
    frame_count = int(cap.get(cv2.CAP_PROP_FRAME_COUNT) or 0)
    duration = frame_count / fps if fps > 0 else 0
    max_frames = max(1, int(args.max_frames))
    positions = np.linspace(0, max(frame_count - 1, 0), num=max_frames, dtype=int).tolist() if frame_count > 0 else [0]

    results = []
    sampled_images: list[np.ndarray] = []
    for idx, pos in enumerate(positions):
        cap.set(cv2.CAP_PROP_POS_FRAMES, int(pos))
        ok, frame = cap.read()
        if not ok or frame is None:
            continue
        sec = round(float(pos / fps), 2) if fps > 0 else 0.0
        frame_name = f"frame_{idx + 1:02d}_{str(sec).replace('.', '_')}s.jpg"
        frame_path = frames_dir / frame_name
        cv2.imwrite(str(frame_path), frame)
        metrics = summarize_frame(frame)
        ocr_lines = run_ocr(frame_path)
        ocr_preview = " | ".join(row["text"] for row in ocr_lines[:4])
        sampled_images.append(frame.copy())
        results.append(
            {
                "index": idx + 1,
                "timestamp_sec": sec,
                "image_path": str(frame_path),
                "metrics": metrics,
                "ocr_lines": ocr_lines,
                "observation": f"{frame_observation(metrics)}" + (f" OCR text: {ocr_preview}." if ocr_preview else ""),
            }
        )

    cap.release()
    scene_change_score = compute_scene_change_score(sampled_images)

    payload = {
        "ok": True,
        "video_path": str(video_path),
        "frame_count": frame_count,
        "fps": round(float(fps), 3) if fps else 0,
        "duration_seconds": round(float(duration), 2),
        "frames": results,
        "scene_change_score": scene_change_score,
        "visual_style_summary": build_visual_style(results, scene_change_score),
    }
    output_path.parent.mkdir(parents=True, exist_ok=True)
    output_path.write_text(json.dumps(payload, ensure_ascii=False, indent=2), encoding="utf-8")


if __name__ == "__main__":
    main()
