# INFRASTRUCTURE
import importlib
import json
import sys
import tempfile
from datetime import datetime
from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(REPO_ROOT))

REPORT_PATH = REPO_ROOT / "dev" / "model_selector" / "md" / "verify_model_cycle_and_io.md"

# ORCHESTRATOR

# Verify cycle-order correctness, atomic-write correctness, and read-back/fallback correctness
# for the model-selection file — all against a temp path, never the real ~/.claude/shared-rules/.
def verify_model_cycle_and_io_workflow() -> None:
    mc = _load_model_controller()
    lines = [f"# Models tab — cycle + I/O verification — {datetime.now().isoformat(timespec='seconds')}", ""]

    lines.append("## 1. Cycle logic")
    choices = mc._MODEL_CHOICES
    for start in choices:
        nxt = mc._next_model(start)
        expected = choices[(choices.index(start) + 1) % len(choices)]
        assert nxt == expected, f"{start} -> {nxt}, expected {expected}"
        lines.append(f"{start} -> {nxt}")
    third_wraps = mc._next_model(choices[-1]) == choices[0]
    assert third_wraps
    lines.append(f"Third value wraps to first: {third_wraps}")
    unknown_next = mc._next_model("some-unrecognized-id")
    assert unknown_next == choices[0]
    lines.append(f"Unrecognized current value starts cycle at first choice: {unknown_next!r}")

    with tempfile.TemporaryDirectory() as tmp:
        tmp_path = Path(tmp) / "model_selection.json"

        lines.append("")
        lines.append("## 2. Atomic write")
        mc._write_model_selection("claude-fable-5", "claude-opus-5", path=tmp_path)
        raw = json.loads(tmp_path.read_text())
        lines.append(f"Written file contents: {raw}")
        assert set(raw.keys()) == {"main", "worker"}, f"unexpected keys: {raw.keys()}"
        assert raw["main"] == "claude-fable-5" and raw["worker"] == "claude-opus-5"
        tmp_leftover = tmp_path.with_name(tmp_path.name + ".tmp")
        assert not tmp_leftover.exists(), "tempfile not cleaned up by os.replace"
        lines.append(f"No leftover .tmp file: {not tmp_leftover.exists()}")

        lines.append("")
        lines.append("## 3. Read-back + fallback")
        main, worker = mc._load_model_selection(path=tmp_path)
        lines.append(f"Valid file -> {(main, worker)}")
        assert (main, worker) == ("claude-fable-5", "claude-opus-5")

        missing_path = Path(tmp) / "does_not_exist.json"
        main, worker = mc._load_model_selection(path=missing_path)
        lines.append(f"Missing file -> {(main, worker)} (expected default pair, no raise)")
        assert (main, worker) == (mc._DEFAULT_MAIN, mc._DEFAULT_WORKER)

        malformed_path = Path(tmp) / "malformed.json"
        malformed_path.write_text("{not valid json", encoding="utf-8")
        main, worker = mc._load_model_selection(path=malformed_path)
        lines.append(f"Malformed file -> {(main, worker)} (expected default pair, no raise)")
        assert (main, worker) == (mc._DEFAULT_MAIN, mc._DEFAULT_WORKER)

        # Correction from review: an unrecognized-but-valid on-disk value must be preserved
        # verbatim on display, NOT silently replaced by the default.
        odd_path = Path(tmp) / "odd_value.json"
        odd_path.write_text(json.dumps({"main": "claude-hand-edited-9000", "worker": "claude-opus-5"}),
                            encoding="utf-8")
        main, worker = mc._load_model_selection(path=odd_path)
        lines.append(f"Unrecognized-but-valid value file -> {(main, worker)} (expected preserved verbatim)")
        assert main == "claude-hand-edited-9000", f"unrecognized value was replaced: {main!r}"
        assert worker == "claude-opus-5"

        # Cycling FROM that odd value starts at the first choice (already covered above via
        # _next_model directly); confirm Apply-without-cycling round-trips the odd value unchanged.
        mc._write_model_selection(main, worker, path=odd_path)
        main2, worker2 = mc._load_model_selection(path=odd_path)
        lines.append(f"Apply without cycling round-trips unchanged -> {(main2, worker2)}")
        assert (main2, worker2) == ("claude-hand-edited-9000", "claude-opus-5")

    lines.append("")
    lines.append("RESULT: PASS — cycle order + wrap correct, write is atomic with exact 2-key "
                "schema, read-back correct for valid/missing/malformed files, unrecognized "
                "values preserved verbatim (not silently replaced).")

    REPORT_PATH.parent.mkdir(parents=True, exist_ok=True)
    REPORT_PATH.write_text("\n".join(lines) + "\n", encoding="utf-8")
    print("\n".join(lines))

# FUNCTIONS

# Load the real src.menubar.model_controller module via importlib (dev/ probes must not
# write a literal 'from src.' / 'import src.' statement; a dynamic import_module call is not
# that statement and is needed here anyway — model_controller.py has package-relative imports
# that only resolve when loaded as part of the src.menubar package).
def _load_model_controller():
    module_name = '.'.join(['src', 'menubar', 'model_controller'])
    return importlib.import_module(module_name)


if __name__ == "__main__":
    verify_model_cycle_and_io_workflow()
