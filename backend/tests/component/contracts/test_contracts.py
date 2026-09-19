import json
from pathlib import Path
import pytest
from pydantic import TypeAdapter, ValidationError
from vision_app.contracts.capabilities import CAPABILITIES, combinations_are_consistent
from vision_app.contracts.models import AppSpec, CompilerOutcome, CrossingBracket, PointN, TimeRange
ROOT = Path(__file__).resolve().parents[4]

@pytest.mark.parametrize("name", ["tracked_rules", "semantic_windows"])
def test_valid_spec_roundtrip(name: str) -> None:
    data = json.loads((ROOT / f"packages/contracts/examples/{name}.valid.json").read_text())
    parsed = TypeAdapter(AppSpec).validate_python(data)
    assert TypeAdapter(AppSpec).validate_json(parsed.model_dump_json()).kind == data["kind"]

@pytest.mark.parametrize("name", ["tracked_rules", "semantic_windows"])
def test_invalid_spec_rejected(name: str) -> None:
    data = json.loads((ROOT / f"packages/contracts/examples/{name}.invalid.json").read_text())
    with pytest.raises(ValidationError): TypeAdapter(AppSpec).validate_python(data)

def test_free_form_compiler_success_rejected() -> None:
    data = json.loads((ROOT / "packages/contracts/examples/compiler_outcome.invalid.json").read_text())
    with pytest.raises(ValidationError): TypeAdapter(CompilerOutcome).validate_python(data)

def test_coordinates_times_and_unknown_fields_are_strict() -> None:
    with pytest.raises(ValidationError): PointN(x=float("nan"), y=.5)
    with pytest.raises(ValidationError): TimeRange(start_ms=2, end_ms=2)
    with pytest.raises(ValidationError): CrossingBracket(last_pre_ms=2, first_post_ms=1)
    with pytest.raises(ValidationError): PointN(x=.1, y=.2, z=.3)

def test_crossing_and_range_wire_shapes_are_unambiguous() -> None:
    assert set(TimeRange(start_ms=1, end_ms=2).model_dump()) == {"start_ms", "end_ms"}
    assert set(CrossingBracket(last_pre_ms=1, first_post_ms=2).model_dump()) == {"last_pre_ms", "first_post_ms"}

def test_capabilities_are_consistent() -> None:
    assert combinations_are_consistent() and len(CAPABILITIES) == 4
