"""Frozen C0 capability vocabulary and valid composition rules."""
from dataclasses import dataclass

@dataclass(frozen=True)
class Capability:
    id: str
    mode: str
    requires: frozenset[str] = frozenset()
    supported_classes: frozenset[str] = frozenset()

CAPABILITIES: dict[str, Capability] = {
    "tracked.line_crossing": Capability("tracked.line_crossing", "tracked_rules", frozenset({"detector.common", "tracker.bytetrack"}), frozenset({"person", "car", "bus", "truck", "motorcycle"})),
    "tracked.person_in_zone": Capability("tracked.person_in_zone", "tracked_rules", frozenset({"detector.common", "tracker.bytetrack"}), frozenset({"person"})),
    "tracked.red_phase_crossing": Capability("tracked.red_phase_crossing", "tracked_rules", frozenset({"detector.common", "tracker.bytetrack", "signal.roi"}), frozenset({"car", "bus", "truck", "motorcycle"})),
    "semantic.visible_condition": Capability("semantic.visible_condition", "semantic_windows", frozenset({"reasoner.window"})),
}
INSTALLED_COMPONENTS = frozenset({"detector.common", "tracker.bytetrack", "signal.roi", "reasoner.window"})

def combinations_are_consistent() -> bool:
    return all(cap.id == key and cap.mode in {"tracked_rules", "semantic_windows"} and cap.requires <= INSTALLED_COMPONENTS for key, cap in CAPABILITIES.items())
