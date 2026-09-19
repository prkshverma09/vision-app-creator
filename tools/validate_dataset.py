#!/usr/bin/env python3
"""Validate operator-supplied real and held-out dataset manifests.

Exit codes: 0 ready, 1 invalid, 2 blocked (valid framework but missing inventory/assets).
"""

from __future__ import annotations

import argparse
import hashlib
import json
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any

ROOT = Path(__file__).resolve().parents[1]
SHA256_LENGTH = 64
VIDEO_TARGET = 30
PROMPT_TARGET = 20
DISPOSITIONS = {"positive", "negative", "unknown"}
SPLITS = {"development", "heldout"}
FIXTURE_TYPES = {"real", "staged", "synthetic"}


@dataclass
class ValidationReport:
    errors: list[str] = field(default_factory=list)
    blockers: list[str] = field(default_factory=list)
    video_cases: int = 0
    prompt_cases: int = 0

    @property
    def status(self) -> str:
        if self.errors:
            return "invalid"
        if self.blockers:
            return "blocked"
        return "ready"

    @property
    def exit_code(self) -> int:
        return {"ready": 0, "invalid": 1, "blocked": 2}[self.status]


def _load(path: Path, report: ValidationReport) -> dict[str, Any] | None:
    if not path.is_file():
        report.blockers.append(f"manifest not supplied: {path}")
        return None
    try:
        value = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError) as exc:
        report.errors.append(f"cannot read JSON manifest {path}: {exc}")
        return None
    if not isinstance(value, dict):
        report.errors.append(f"manifest must be a JSON object: {path}")
        return None
    if value.get("schema_version") != 1 or not isinstance(value.get("cases"), list):
        report.errors.append(f"{path}: schema_version must be 1 and cases must be an array")
        return None
    return value


def _sha256(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as stream:
        for chunk in iter(lambda: stream.read(1024 * 1024), b""):
            digest.update(chunk)
    return digest.hexdigest()


def _rights(case: dict[str, Any], manifest: Path, licenses: Path, report: ValidationReport) -> None:
    reference = case.get("rights_record")
    case_id = case.get("id", "<unknown>")
    if not isinstance(reference, str) or not reference:
        report.errors.append(f"{case_id}: missing rights_record")
        return
    path = (licenses / reference).resolve()
    try:
        path.relative_to(licenses.resolve())
    except ValueError:
        report.errors.append(f"{case_id}: rights_record escapes licenses directory")
        return
    if not path.is_file():
        report.errors.append(f"{case_id}: rights record not found: {reference}")
        return
    try:
        record = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError) as exc:
        report.errors.append(f"{case_id}: invalid rights record: {exc}")
        return
    required = (
        "id",
        "approved_by",
        "approved_at",
        "permitted_uses",
        "redistribution",
        "source_ids",
    )
    missing = [name for name in required if name not in record]
    if missing:
        report.errors.append(f"{case_id}: rights record missing fields: {', '.join(missing)}")
    if case.get("source_id") not in record.get("source_ids", []):
        report.errors.append(f"{case_id}: rights record does not cover source_id")


def _intervals(case: dict[str, Any], report: ValidationReport) -> None:
    case_id = case.get("id", "<unknown>")
    intervals = case.get("truth_intervals")
    if not isinstance(intervals, list) or not intervals:
        report.errors.append(f"{case_id}: truth_intervals must be a non-empty array")
        return
    for index, interval in enumerate(intervals):
        valid = isinstance(interval, dict)
        valid = (
            valid and type(interval.get("start_ms")) is int and type(interval.get("end_ms")) is int
        )
        valid = valid and interval["start_ms"] >= 0 and interval["start_ms"] <= interval["end_ms"]
        valid = valid and interval.get("disposition") in DISPOSITIONS
        valid = (
            valid
            and type(interval.get("uncertainty_ms")) is int
            and interval["uncertainty_ms"] >= 0
        )
        if not valid:
            report.errors.append(
                f"{case_id}: truth_intervals[{index}] requires non-negative integer "
                "start_ms<=end_ms and uncertainty_ms, plus positive/negative/unknown disposition"
            )


def _source(case: dict[str, Any], manifest: Path, report: ValidationReport) -> None:
    case_id = case.get("id", "<unknown>")
    expected = case.get("source_sha256")
    if not isinstance(expected, str) or len(expected) != SHA256_LENGTH:
        report.errors.append(f"{case_id}: source_sha256 must be a 64-character SHA-256")
        return
    try:
        int(expected, 16)
    except ValueError:
        report.errors.append(f"{case_id}: source_sha256 is not hexadecimal")
        return
    source_path = case.get("source_path")
    if not isinstance(source_path, str) or not source_path:
        report.errors.append(f"{case_id}: source_path is required")
        return
    path = (manifest.parent / source_path).resolve()
    if not path.is_file():
        report.blockers.append(f"{case_id}: authorized source unavailable for hash check: {path}")
    elif _sha256(path) != expected.lower():
        report.errors.append(f"{case_id}: source hash mismatch")


def _case(
    case: Any, expected_split: str, manifest: Path, licenses: Path, report: ValidationReport
) -> None:
    if not isinstance(case, dict):
        report.errors.append(f"{manifest}: each case must be an object")
        return
    case_id = case.get("id", "<unknown>")
    required = (
        "id",
        "kind",
        "fixture_type",
        "split",
        "source_id",
        "camera_group",
        "provenance",
        "label_review",
    )
    missing = [name for name in required if case.get(name) in (None, "")]
    if missing:
        report.errors.append(f"{case_id}: missing metadata fields: {', '.join(missing)}")
    if case.get("split") not in SPLITS or case.get("split") != expected_split:
        report.errors.append(f"{case_id}: split must be {expected_split}")
    fixture_type = case.get("fixture_type")
    if fixture_type not in FIXTURE_TYPES:
        report.errors.append(f"{case_id}: invalid fixture_type")
    elif fixture_type == "synthetic":
        report.errors.append(
            f"{case_id}: synthetic cases belong in fixtures/synthetic, not real datasets"
        )
    _rights(case, manifest, licenses, report)
    kind = case.get("kind")
    if kind == "video":
        report.video_cases += 1
        _source(case, manifest, report)
        _intervals(case, report)
        evidence = case.get("evidence")
        if not isinstance(evidence, dict) or not all(
            evidence.get(marker) is True
            for marker in ("governing_signal_visible", "stop_line_visible", "approach_lane_visible")
        ):
            report.errors.append(
                f"{case_id}: video evidence must mark governing signal, stop line, "
                "and approach lane visible"
            )
    elif kind == "prompt":
        report.prompt_cases += 1
        if not isinstance(case.get("prompt"), str) or not case["prompt"].strip():
            report.errors.append(f"{case_id}: prompt text is required")
        if case.get("expected_outcome") not in {"supported", "unsupported", "clarification"}:
            report.errors.append(f"{case_id}: invalid expected_outcome")
    else:
        report.errors.append(f"{case_id}: kind must be video or prompt")


def validate(real_manifest: Path, heldout_manifest: Path, licenses: Path) -> ValidationReport:
    """Validate both split manifests without accessing a network."""
    report = ValidationReport()
    seen_ids: set[str] = set()
    source_groups: dict[str, set[str]] = {"development": set(), "heldout": set()}
    camera_groups: dict[str, set[str]] = {"development": set(), "heldout": set()}
    disposition_counts = dict.fromkeys(DISPOSITIONS, 0)
    for path, split in ((real_manifest, "development"), (heldout_manifest, "heldout")):
        data = _load(path, report)
        if data is None:
            continue
        if split == "heldout" and data["cases"] and not isinstance(data.get("frozen_at"), str):
            report.errors.append(f"{path}: non-empty held-out manifest requires frozen_at")
        for case in data["cases"]:
            _case(case, split, path, licenses, report)
            if not isinstance(case, dict):
                continue
            case_id = case.get("id")
            if isinstance(case_id, str):
                if case_id in seen_ids:
                    report.errors.append(f"duplicate case id: {case_id}")
                seen_ids.add(case_id)
            if case.get("kind") == "video":
                group = case.get("camera_group")
                source = case.get("source_id")
                if isinstance(source, str):
                    source_groups[split].add(source)
                if isinstance(group, str):
                    camera_groups[split].add(group)
                for interval in case.get("truth_intervals", []):
                    if isinstance(interval, dict) and interval.get("disposition") in DISPOSITIONS:
                        disposition_counts[interval["disposition"]] += 1
    source_overlap = source_groups["development"] & source_groups["heldout"]
    if source_overlap:
        report.errors.append(
            f"development/held-out source overlap: {', '.join(sorted(source_overlap))}"
        )
    camera_overlap = camera_groups["development"] & camera_groups["heldout"]
    if camera_overlap:
        report.errors.append(
            f"development/held-out camera overlap: {', '.join(sorted(camera_overlap))}"
        )
    if report.video_cases < VIDEO_TARGET:
        report.blockers.append(
            f"video inventory shortfall: {report.video_cases}/{VIDEO_TARGET} labeled cases"
        )
    if report.prompt_cases < PROMPT_TARGET:
        report.blockers.append(
            f"prompt inventory shortfall: {report.prompt_cases}/{PROMPT_TARGET} cases"
        )
    missing_dispositions = sorted(name for name, count in disposition_counts.items() if count == 0)
    if missing_dispositions:
        report.blockers.append(
            f"video disposition coverage missing: {', '.join(missing_dispositions)}"
        )
    if not source_groups["heldout"]:
        report.blockers.append("explicit held-out video portion is empty")
    return report


def _parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(
        description="Validate authorized dataset manifests and report release blockers"
    )
    parser.add_argument("--real-manifest", type=Path, default=ROOT / "fixtures/real/manifest.json")
    parser.add_argument(
        "--heldout-manifest", type=Path, default=ROOT / "fixtures/heldout/manifest.json"
    )
    parser.add_argument("--licenses-dir", type=Path, default=ROOT / "fixtures/licenses")
    parser.add_argument("--json", action="store_true", help="emit a machine-readable report")
    return parser


def main() -> int:
    args = _parser().parse_args()
    report = validate(args.real_manifest, args.heldout_manifest, args.licenses_dir)
    payload = {
        "status": report.status,
        "video_cases": report.video_cases,
        "video_target": VIDEO_TARGET,
        "prompt_cases": report.prompt_cases,
        "prompt_target": PROMPT_TARGET,
        "errors": report.errors,
        "blockers": report.blockers,
    }
    if args.json:
        print(json.dumps(payload, indent=2))
    else:
        print(f"dataset status: {report.status.upper()}")
        print(
            f"inventory: video {report.video_cases}/{VIDEO_TARGET}; "
            f"prompt {report.prompt_cases}/{PROMPT_TARGET}"
        )
        for error in report.errors:
            print(f"ERROR: {error}")
        for blocker in report.blockers:
            print(f"BLOCKED: {blocker}")
    return report.exit_code


if __name__ == "__main__":
    raise SystemExit(main())
