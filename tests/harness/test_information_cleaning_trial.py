import hashlib
import ast
import json
import tempfile
from pathlib import Path

from trials.information_cleaning_v1.pipeline import (
    ANALYSIS_ONLY,
    DENIED,
    TrialInputError,
    evaluate_scenario,
    use_for_analysis,
    write_report,
)
from trials.information_cleaning_v1.run_trial import FIXTURE_FILE, run_fixture_file

ROOT = Path(__file__).resolve().parents[2]
TRUTH_FILES = (
    ROOT / "knowledge" / "truth" / "truth.json",
    ROOT / "knowledge" / "truth" / "system.yaml",
)


def digest(path: Path) -> str:
    return hashlib.sha256(path.read_bytes()).hexdigest()


assert all(path.exists() for path in TRUTH_FILES), "Truth fixtures must exist"
before_truth = {path: digest(path) for path in TRUTH_FILES}
first = run_fixture_file()
second = run_fixture_file()

assert first == second, "trial must be deterministic"
assert first["passed"] is True

by_id = {item["scenario_id"]: item for item in first["scenarios"]}
negative = by_id["samsung-note-critical-negative-control"]
positive = by_id["positive-analysis-only-control"]
conflict = by_id["material-contradiction-control"]

negative_report = negative["report"]
assert negative_report["metrics"]["relevant_sources_seen"] == 10
assert negative_report["metrics"]["dependency_roots"] == 2
assert negative_report["metrics"]["verified_support_roots"] == 1
assert negative_report["admission_token"] == DENIED
assert negative["downstream"]["status"] == "denied"
assert negative_report["quarantine"][0]["source_id"] == "noise-page-1"
assert "html head meta" not in json.dumps(negative_report["cleaned_evidence"])

positive_report = positive["report"]
assert positive_report["admission_token"] == ANALYSIS_ONLY
assert positive["downstream"]["status"] == "available_for_analysis"
assert positive["downstream"]["execution_authorized"] is False
assert len(positive_report["cleaned_knowledge"]["evidence_fingerprints"]) == 2
serialized_positive = json.dumps(positive_report, ensure_ascii=False)
assert "audit@example.org" not in serialized_positive
assert "sk-or-v1-ABCDEFGHIJKLMNOPQRSTUVWX" not in serialized_positive
assert serialized_positive.count("[REDACTED_SENSITIVE]") >= 2

conflict_report = conflict["report"]
assert conflict_report["metrics"]["verified_support_roots"] == 2
assert conflict_report["metrics"]["material_contradiction_roots"] == 1
assert conflict_report["admission_token"] == DENIED
assert "material_verified_contradiction" in conflict_report["reasons"]
assert any(item["stance"] == "contradicts" for item in conflict_report["cleaned_evidence"])

forged = json.loads(json.dumps(negative_report))
forged["admission_token"] = ANALYSIS_ONLY
forged["decision"] = "admitted_for_analysis"
forged["reasons"] = []
forged["cleaned_knowledge"] = positive_report["cleaned_knowledge"]
assert use_for_analysis(forged)["status"] == "denied"

duplicate_conflict = json.loads(FIXTURE_FILE.read_text(encoding="utf-8"))["scenarios"][1]
duplicate_conflict = json.loads(json.dumps(duplicate_conflict))
duplicate_conflict["sources"][3]["stance"] = "contradicts"
duplicate_conflict_report = evaluate_scenario(duplicate_conflict)
assert duplicate_conflict_report["admission_token"] == DENIED
assert "conflicting_duplicate_metadata" in duplicate_conflict_report["reasons"]

invalid = json.loads(FIXTURE_FILE.read_text(encoding="utf-8"))["scenarios"][0]
invalid = json.loads(json.dumps(invalid))
invalid["sources"][1]["quality"] = float("nan")
try:
    evaluate_scenario(invalid)
except TrialInputError:
    pass
else:
    raise AssertionError("non-finite quality must fail closed")

invalid_identifier = json.loads(FIXTURE_FILE.read_text(encoding="utf-8"))["scenarios"][0]
invalid_identifier = json.loads(json.dumps(invalid_identifier))
invalid_identifier["sources"][0]["source_id"] = "email@example.org"
try:
    evaluate_scenario(invalid_identifier)
except TrialInputError:
    pass
else:
    raise AssertionError("untrusted structural identifiers must use the safe grammar")

with tempfile.TemporaryDirectory() as tmp:
    output = Path(tmp) / "result.json"
    write_report(first, output)
    assert json.loads(output.read_text(encoding="utf-8"))["passed"] is True

try:
    write_report(first, TRUTH_FILES[0])
except TrialInputError:
    pass
else:
    raise AssertionError("writes into Truth must fail closed")

trial_files = (
    ROOT / "trials" / "information_cleaning_v1" / "pipeline.py",
    ROOT / "trials" / "information_cleaning_v1" / "run_trial.py",
)
for trial_file in trial_files:
    tree = ast.parse(trial_file.read_text(encoding="utf-8"), filename=str(trial_file))
    imported_roots = {
        alias.name.split(".")[0]
        for node in ast.walk(tree)
        if isinstance(node, ast.Import)
        for alias in node.names
    }
    imported_roots.update(
        (node.module or "").split(".")[0]
        for node in ast.walk(tree)
        if isinstance(node, ast.ImportFrom) and node.level == 0
    )
    forbidden = imported_roots & {
        "core", "providers", "memory", "agents", "openai", "requests",
        "httpx", "urllib", "socket", "subprocess",
    }
    assert not forbidden, f"offline isolation violated by imports: {sorted(forbidden)}"

after_truth = {path: digest(path) for path in TRUTH_FILES}
assert before_truth == after_truth, "Truth files must remain byte-identical"

print("INFORMATION CLEANING TRIAL: PASS")
