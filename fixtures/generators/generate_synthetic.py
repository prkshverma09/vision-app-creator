"""Reproduce tiny deterministic synthetic MP4 fixtures (seed 20260918)."""
import argparse
import hashlib
import json
import subprocess
from pathlib import Path

SEED = 20260918
FPS = 10
FRAMES = 50
WIDTH = 320
HEIGHT = 240
CASES = (
    "empty_scene",
    "moving_dot",
    "red_green_light",
    "red_light_violation",
    "green_light_crossing",
)
CAR_CASES = {"red_light_violation", "green_light_crossing"}


def sha(path: Path) -> str:
    return hashlib.sha256(path.read_bytes()).hexdigest()


def annotation(name: str) -> dict:
    frames = []
    for i in range(FRAMES):
        t = i * 100
        boxes = []
        if name == "moving_dot" or name in CAR_CASES:
            x = 20 + 5 * i if name == "moving_dot" else 40 + 4 * i
            w = 12 if name == "moving_dot" else 24
            boxes = [{
                "track_id": "track-1",
                "class": "dot" if name == "moving_dot" else "car",
                "box_px": [x, 110 if name == "moving_dot" else 150,
                           x + w, 122 if name == "moving_dot" else 164],
            }]
        signal = "unknown"
        if name in {"red_green_light", "red_light_violation"}:
            signal = "green" if t < 2000 else "red"
        elif name == "green_light_crossing":
            signal = "green"
        frames.append({"frame": i, "source_time_ms": t, "boxes": boxes, "signal_state": signal})
    return {
        "fixture_id": name,
        "seed": SEED,
        "video": {"width": WIDTH, "height": HEIGHT, "fps": FPS,
                  "frames": FRAMES, "duration_ms": 5000},
        "frames": frames,
        "expected_events": ([{"type": "red_phase_crossing", "track_id": "track-1",
                              "crossing_bracket_ms": [2900, 3100]}]
                            if name == "red_light_violation" else []),
        "no_event": name != "red_light_violation",
    }


def render_frame(name: str, frame: dict) -> bytes:
    pixels = bytearray(WIDTH * HEIGHT * 3)

    def rectangle(box: tuple | list, color: tuple[int, int, int]) -> None:
        x1, y1, x2, y2 = box
        row = bytes(color) * (x2 - x1)
        for y in range(y1, y2):
            start = (y * WIDTH + x1) * 3
            pixels[start:start + len(row)] = row

    if name in CAR_CASES:
        rectangle((0, 140, WIDTH, 174), (64, 64, 64))
        rectangle((160, 0, 162, HEIGHT), (255, 255, 0))
    if frame["signal_state"] != "unknown":
        signal_box = (285, 20, 305, 40) if name in CAR_CASES else (145, 20, 175, 50)
        color = (0, 128, 0) if frame["signal_state"] == "green" else (255, 0, 0)
        rectangle(signal_box, color)
    for obj in frame["boxes"]:
        x1, y1, x2, y2 = obj["box_px"]
        if obj["class"] == "dot":
            rectangle(obj["box_px"], (255, 255, 255))
        else:
            rectangle((x1, y1, x2, y2 - 4), (245, 245, 245))
            rectangle((x1 + 5, y1 + 2, x1 + 16, y1 + 6), (35, 90, 140))
            for wheel_x in (x1 + 3, x2 - 8):
                rectangle((wheel_x, y2 - 6, wheel_x + 5, y2), (12, 12, 12))
                rectangle((wheel_x + 1, y2 - 4, wheel_x + 4, y2 - 2), (180, 180, 180))
    return bytes(pixels)


def generate(root: Path) -> None:
    video = root / "video"
    annotations = root / "annotations"
    video.mkdir(parents=True, exist_ok=True)
    annotations.mkdir(parents=True, exist_ok=True)
    manifest = {
        "generator": "generate_synthetic.py",
        "seed": SEED,
        "ffmpeg_options": "rawvideo rgb24 input; libx264 preset=ultrafast crf=23 "
                          "pix_fmt=yuv420p threads=1 metadata stripped",
        "fixtures": {},
    }
    for name in CASES:
        data = annotation(name)
        target = video / f"{name}.mp4"
        cmd = [
            "ffmpeg", "-hide_banner", "-loglevel", "error", "-y",
            "-f", "rawvideo", "-pixel_format", "rgb24", "-video_size", f"{WIDTH}x{HEIGHT}",
            "-framerate", str(FPS), "-i", "pipe:0", "-frames:v", str(FRAMES),
            "-an", "-c:v", "libx264", "-preset", "ultrafast", "-crf", "23",
            "-pix_fmt", "yuv420p", "-threads", "1", "-map_metadata", "-1", str(target),
        ]
        subprocess.run(cmd, input=b"".join(render_frame(name, f) for f in data["frames"]),
                       check=True)
        ann = annotations / f"{name}.json"
        ann.write_text(json.dumps(data, sort_keys=True, indent=2) + "\n")
        manifest["fixtures"][name] = {"video_sha256": sha(target), "annotation_sha256": sha(ann)}
    (root / "manifest.json").write_text(json.dumps(manifest, sort_keys=True, indent=2) + "\n")


if __name__ == "__main__":
    p = argparse.ArgumentParser()
    p.add_argument("--output", type=Path, default=Path(__file__).resolve().parents[1] / "synthetic")
    generate(p.parse_args().output)
