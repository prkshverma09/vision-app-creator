from pathlib import Path

def test_c0_export_exists_and_is_hashed() -> None:
    root = Path(__file__).resolve().parents[3]
    assert (root / "packages/contracts/schemas/c0.schema.json").is_file()
    assert len((root / "packages/contracts/schemas/c0.sha256").read_text().strip()) == 64
