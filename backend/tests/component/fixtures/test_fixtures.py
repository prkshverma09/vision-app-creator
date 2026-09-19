import hashlib
import json
import runpy
import subprocess
import sys
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parents[4]
SYN = ROOT / "fixtures/synthetic"
NAMES = {"empty_scene", "moving_dot", "red_green_light", "red_light_violation",
         "green_light_crossing"}
FRAME_BYTES = 320 * 240 * 3


def digest(path: Path) -> str:
    return hashlib.sha256(path.read_bytes()).hexdigest()


def annotation(name: str) -> dict:
    return json.loads((SYN / f"annotations/{name}.json").read_text())


@pytest.fixture(scope="module")
def decoded() -> dict[str, list[bytes]]:
    result = {}
    for name in sorted(NAMES):
        raw = subprocess.run(
            ["ffmpeg", "-hide_banner", "-loglevel", "error", "-i",
             str(SYN / f"video/{name}.mp4"), "-f", "rawvideo", "-pix_fmt", "rgb24", "pipe:1"],
            capture_output=True, check=True, timeout=30,
        ).stdout
        assert len(raw) == FRAME_BYTES * 50
        result[name] = [raw[i:i + FRAME_BYTES] for i in range(0, len(raw), FRAME_BYTES)]
    return result


def pixel(frame: bytes, x: int, y: int) -> bytes:
    offset = (y * 320 + x) * 3
    return frame[offset:offset + 3]


def test_fixture_inventory_and_size() -> None:
    manifest = json.loads((SYN / "manifest.json").read_text())
    assert set(manifest["fixtures"]) == NAMES
    assert "libx264" in manifest["ffmpeg_options"]
    assert sum(p.stat().st_size for p in (SYN / "video").glob("*.mp4")) < 5_000_000
    assert len({item["video_sha256"] for item in manifest["fixtures"].values()}) == len(NAMES)


def test_manifest_hashes_match() -> None:
    manifest = json.loads((SYN / "manifest.json").read_text())
    for name, item in manifest["fixtures"].items():
        assert digest(SYN / f"video/{name}.mp4") == item["video_sha256"]
        assert digest(SYN / f"annotations/{name}.json") == item["annotation_sha256"]


@pytest.mark.parametrize("name", sorted(NAMES))
def test_annotations_match_video_metadata(name: str) -> None:
    data = annotation(name)
    assert len(data["frames"]) == data["video"]["frames"] == 50
    assert [f["source_time_ms"] for f in data["frames"]] == list(range(0, 5000, 100))
    assert [f["frame"] for f in data["frames"]] == list(range(50))
    assert (len(data["expected_events"]) == 0) == data["no_event"]
    probe = subprocess.run(
        ["ffprobe", "-v", "error", "-show_streams", "-show_frames", "-of", "json",
         str(SYN / f"video/{name}.mp4")], capture_output=True, check=True, timeout=15,
    )
    metadata = json.loads(probe.stdout)
    assert [round(float(f["best_effort_timestamp_time"]) * 1000) for f in metadata["frames"]] == [
        f["source_time_ms"] for f in data["frames"]
    ]
    streams = metadata["streams"]
    assert len(streams) == 1
    stream = streams[0]
    assert stream["codec_name"] == "h264"
    assert stream["pix_fmt"] == "yuv420p"
    assert stream["width"] == data["video"]["width"] == 320
    assert stream["height"] == data["video"]["height"] == 240
    assert stream["avg_frame_rate"] == stream["r_frame_rate"] == "10/1"
    assert data["video"]["fps"] == 10
    assert int(stream["nb_frames"]) == data["video"]["frames"]
    assert float(stream["duration"]) * 1000 == data["video"]["duration_ms"] == 5000


@pytest.mark.parametrize("name", ["moving_dot", "red_light_violation", "green_light_crossing"])
def test_decoded_objects_exist_and_move_in_every_annotated_frame(name: str, decoded) -> None:
    frames = decoded[name]
    for rgb, frame in zip(frames, annotation(name)["frames"], strict=True):
        obj, = frame["boxes"]
        x1, y1, x2, y2 = obj["box_px"]
        body_y = y1 + 7 if obj["class"] == "car" else y1 + 5
        white_x = [x for x in range(320) if min(pixel(rgb, x, body_y)) > 200]
        assert white_x == list(range(x1, x2)), (name, frame["frame"], white_x)
        assert min(pixel(rgb, x1 + 1, y1 + 1)) > 200
        if obj["class"] == "car":
            assert max(pixel(rgb, x1 + 3, y2 - 1)) < 45
            assert max(pixel(rgb, x2 - 8, y2 - 1)) < 45
            assert min(pixel(rgb, x1 + 5, y2 - 3)) > 140
            assert pixel(rgb, x1 + 10, y1 + 3)[2] > pixel(rgb, x1 + 10, y1 + 3)[0]
        else:
            white_y = [y for y in range(240) if min(pixel(rgb, x1 + 5, y)) > 200]
            assert white_y == list(range(y1, y2))
    assert frames[0] != frames[30]
    start = 20 if name == "moving_dot" else 40
    end = 170 if name == "moving_dot" else 160
    y = 115 if name == "moving_dot" else 157
    assert min(pixel(frames[0], start + 2, y)) > 200
    assert min(pixel(frames[30], start + 2, y)) < 100
    assert min(pixel(frames[30], end + 2, y)) > 200


@pytest.mark.parametrize("name", ["moving_dot", "red_light_violation", "green_light_crossing"])
def test_rendered_object_bounds_exactly_match_annotations(name: str) -> None:
    render = runpy.run_path(str(ROOT / "fixtures/generators/generate_synthetic.py"))["render_frame"]
    for frame in annotation(name)["frames"]:
        rgb = render(name, frame)
        background = render(name, {**frame, "boxes": []})
        obj, = frame["boxes"]
        x1, y1, x2, y2 = obj["box_px"]
        for y in range(240):
            start = y * 320 * 3
            if not y1 <= y < y2:
                assert rgb[start:start + 960] == background[start:start + 960]
            else:
                assert rgb[start:start + x1 * 3] == background[start:start + x1 * 3]
                assert rgb[start + x2 * 3:start + 960] == background[start + x2 * 3:start + 960]
        changed = [(x, y) for y in range(y1, y2) for x in range(x1, x2)
                   if pixel(rgb, x, y) != pixel(background, x, y)]
        assert [min(x for x, _ in changed), min(y for _, y in changed),
                max(x for x, _ in changed) + 1, max(y for _, y in changed) + 1] == obj["box_px"]


@pytest.mark.parametrize("name", ["red_green_light", "red_light_violation", "green_light_crossing"])
def test_decoded_signal_matches_annotation_every_frame(name: str, decoded) -> None:
    x = 160 if name == "red_green_light" else 295
    for rgb, frame in zip(decoded[name], annotation(name)["frames"], strict=True):
        red, green, blue = pixel(rgb, x, 30)
        expected = (
            "green" if name == "green_light_crossing" or frame["source_time_ms"] < 2000 else "red"
        )
        assert frame["signal_state"] == expected
        if expected == "green":
            assert green > 100 and red < 30 and blue < 30
        else:
            assert red > 200 and green < 30 and blue < 30


def test_green_crossing_is_same_car_motion_but_no_red_event(decoded) -> None:
    positive = annotation("red_light_violation")
    negative = annotation("green_light_crossing")
    assert [f["boxes"] for f in negative["frames"]] == [f["boxes"] for f in positive["frames"]]
    assert negative["no_event"] and negative["expected_events"] == []
    assert all(f["signal_state"] == "green" for f in negative["frames"])
    assert decoded["green_light_crossing"][30] != decoded["red_light_violation"][30]
    assert digest(SYN / "video/green_light_crossing.mp4") != digest(
        SYN / "video/red_light_violation.mp4"
    )


def test_red_event_bracket_uses_bottom_left_anchor_and_one_percent_line_band() -> None:
    data = annotation("red_light_violation")
    before = [f for f in data["frames"] if f["boxes"][0]["box_px"][0] < 160 - 320 * 0.01]
    after = [f for f in data["frames"] if f["boxes"][0]["box_px"][0] > 160 + 320 * 0.01]
    bracket = [before[-1]["source_time_ms"], after[0]["source_time_ms"]]
    assert bracket == data["expected_events"][0]["crossing_bracket_ms"] == [2900, 3100]
    assert all(f["signal_state"] == "red" for f in data["frames"]
               if bracket[0] <= f["source_time_ms"] <= bracket[1])


def test_empty_scene_has_no_visible_objects_or_events(decoded) -> None:
    data = annotation("empty_scene")
    assert data["no_event"] and data["expected_events"] == []
    assert all(f["boxes"] == [] and f["signal_state"] == "unknown" for f in data["frames"])
    assert all(max(frame) < 5 for frame in decoded["empty_scene"])
    assert digest(SYN / "video/empty_scene.mp4") != digest(SYN / "video/moving_dot.mp4")


def test_regeneration_is_deterministic(tmp_path: Path) -> None:
    out = tmp_path / "synthetic"
    subprocess.run([sys.executable, str(ROOT / "fixtures/generators/generate_synthetic.py"),
                    "--output", str(out)], check=True)
    expected = json.loads((SYN / "manifest.json").read_text())
    actual = json.loads((out / "manifest.json").read_text())
    assert actual == expected
