"""Export stable C0 JSON schemas from authoritative Pydantic models."""
import hashlib, json, sys
from pathlib import Path
from pydantic import TypeAdapter

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "backend/src"))
from vision_app.contracts import models
NAMES = ["ResourceId","SourceTimeMs","UtcTimestamp","TimeRange","CrossingBracket","PointN","BoxN","FrameRef","ObservationQuality","MoneyMicrousd","ModelInvocationMetadata","VisionApp","AppVersion","Calibration","SourceAsset","BuildTurn","DecodedFrame","DetectionBatch","TrackObservation","SignalObservation","SignalInterval","RuleCandidate","SemanticObservation","EvidenceManifest","Event","RunProgress"]

def main() -> None:
    out = ROOT / "packages/contracts/schemas"; out.mkdir(parents=True, exist_ok=True)
    bundle = {name: TypeAdapter(getattr(models, name)).json_schema() for name in NAMES}
    bundle["AppSpec"] = TypeAdapter(models.AppSpec).json_schema()
    bundle["CompilerOutcome"] = TypeAdapter(models.CompilerOutcome).json_schema()
    payload = json.dumps(bundle, sort_keys=True, separators=(",", ":"))
    (out / "c0.schema.json").write_text(json.dumps(bundle, indent=2, sort_keys=True) + "\n")
    (out / "c0.sha256").write_text(hashlib.sha256(payload.encode()).hexdigest() + "\n")
if __name__ == "__main__": main()
