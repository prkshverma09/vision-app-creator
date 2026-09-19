import hashlib
import json
from pathlib import Path

import pytest

from tools.validate_dataset import validate


def dump(path: Path, value: object) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(value), encoding="utf-8")


def rights(directory: Path, source_ids: list[str]) -> None:
    dump(
        directory / "approved.json",
        {
            "id": "rights-1",
            "approved_by": "operator@example.invalid",
            "approved_at": "2026-01-01T00:00:00Z",
            "permitted_uses": ["development", "evaluation"],
            "redistribution": "prohibited",
            "source_ids": source_ids,
        },
    )


def video_case(
    case_id: str, split: str, source: Path, source_id: str = "source-1"
) -> dict[str, object]:
    return {
        "id": case_id,
        "kind": "video",
        "fixture_type": "real",
        "split": split,
        "source_id": source_id,
        "camera_group": "camera-1",
        "provenance": "operator-supplied test placeholder",
        "rights_record": "approved.json",
        "source_path": source.name,
        "source_sha256": hashlib.sha256(source.read_bytes()).hexdigest(),
        "evidence": {
            "governing_signal_visible": True,
            "stop_line_visible": True,
            "approach_lane_visible": True,
        },
        "truth_intervals": [
            {"start_ms": 0, "end_ms": 100, "uncertainty_ms": 0, "disposition": "positive"}
        ],
        "label_review": {"reviewer": "human", "reviewed_at": "2026-01-01T00:00:00Z"},
    }


def test_empty_manifests_are_blocked_not_ready(tmp_path: Path) -> None:
    real = tmp_path / "real.json"
    heldout = tmp_path / "heldout.json"
    dump(real, {"schema_version": 1, "cases": []})
    dump(heldout, {"schema_version": 1, "cases": []})

    report = validate(real, heldout, tmp_path / "licenses")

    assert report.status == "blocked"
    assert report.exit_code == 2
    assert not report.errors
    assert "0/30" in " ".join(report.blockers)
    assert "0/20" in " ".join(report.blockers)


def test_missing_rights_record_is_rejected(tmp_path: Path) -> None:
    source = tmp_path / "placeholder.bin"
    source.write_bytes(b"not real footage")
    case = video_case("development-1", "development", source)
    case.pop("rights_record")
    real = tmp_path / "real.json"
    heldout = tmp_path / "heldout.json"
    dump(real, {"schema_version": 1, "cases": [case]})
    dump(heldout, {"schema_version": 1, "cases": []})

    report = validate(real, heldout, tmp_path / "licenses")

    assert report.status == "invalid"
    assert any("missing rights_record" in error for error in report.errors)


def test_development_heldout_source_overlap_is_rejected(tmp_path: Path) -> None:
    source = tmp_path / "placeholder.bin"
    source.write_bytes(b"synthetic placeholder bytes")
    rights(tmp_path / "licenses", ["shared-source"])
    development = video_case("development-1", "development", source, "shared-source")
    heldout_case = video_case("heldout-1", "heldout", source, "shared-source")
    real = tmp_path / "real.json"
    heldout = tmp_path / "heldout.json"
    dump(real, {"schema_version": 1, "cases": [development]})
    dump(heldout, {"schema_version": 1, "cases": [heldout_case]})

    report = validate(real, heldout, tmp_path / "licenses")

    assert report.status == "invalid"
    assert any("source overlap" in error for error in report.errors)


def test_missing_authorized_media_remains_blocked(tmp_path: Path) -> None:
    placeholder = tmp_path / "absent.mp4"
    existing = tmp_path / "seed.bin"
    existing.write_bytes(b"hash seed only")
    rights(tmp_path / "licenses", ["source-1"])
    case = video_case("development-1", "development", existing)
    case["source_path"] = placeholder.name
    real = tmp_path / "real.json"
    heldout = tmp_path / "heldout.json"
    dump(real, {"schema_version": 1, "cases": [case]})
    dump(heldout, {"schema_version": 1, "cases": []})

    report = validate(real, heldout, tmp_path / "licenses")

    assert report.status == "blocked"
    assert any("authorized source unavailable" in blocker for blocker in report.blockers)


@pytest.mark.parametrize(
    ("mutation", "message"),
    [
        ("hash", "source hash mismatch"),
        ("evidence", "video evidence"),
        ("interval", "truth_intervals[0]"),
    ],
)
def test_invalid_hash_evidence_and_truth_are_rejected(
    tmp_path: Path, mutation: str, message: str
) -> None:
    source = tmp_path / "placeholder.bin"
    source.write_bytes(b"generated placeholder")
    rights(tmp_path / "licenses", ["source-1"])
    case = video_case("development-1", "development", source)
    if mutation == "hash":
        case["source_sha256"] = "0" * 64
    elif mutation == "evidence":
        case["evidence"] = {
            "governing_signal_visible": False,
            "stop_line_visible": True,
            "approach_lane_visible": True,
        }
    else:
        case["truth_intervals"] = [
            {"start_ms": 200, "end_ms": 100, "uncertainty_ms": -1, "disposition": "positive"}
        ]
    real = tmp_path / "real.json"
    heldout = tmp_path / "heldout.json"
    dump(real, {"schema_version": 1, "cases": [case]})
    dump(heldout, {"schema_version": 1, "cases": []})

    report = validate(real, heldout, tmp_path / "licenses")

    assert report.status == "invalid"
    assert any(message in error for error in report.errors)


def test_synthetic_placeholder_cannot_count_as_real(tmp_path: Path) -> None:
    source = tmp_path / "placeholder.bin"
    source.write_bytes(b"generated")
    rights(tmp_path / "licenses", ["source-1"])
    case = video_case("synthetic-1", "development", source)
    case["fixture_type"] = "synthetic"
    real = tmp_path / "real.json"
    heldout = tmp_path / "heldout.json"
    dump(real, {"schema_version": 1, "cases": [case]})
    dump(heldout, {"schema_version": 1, "cases": []})

    report = validate(real, heldout, tmp_path / "licenses")

    assert report.status == "invalid"
    assert any("fixtures/synthetic" in error for error in report.errors)
