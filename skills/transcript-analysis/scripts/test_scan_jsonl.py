"""Behaviour checks usable directly in OMP eval or by a pytest runner."""

import json
import runpy
from pathlib import Path
from tempfile import TemporaryDirectory

register_scanner = runpy.run_path(
    str(Path(__file__).resolve().parent / "scan_jsonl.py")
)["register_scan_jsonl"]


def scanner(root: Path):
    return register_scanner([str(root)], lambda function: None)


def message(role: str, text: str) -> dict:
    return {"type": "message", "message": {"role": role, "content": [{"type": "text", "text": text}]}}


def save(path: Path, rows: list[dict]) -> None:
    path.write_text("".join(json.dumps(row) + "\n" for row in rows), encoding="utf-8")


def rejected(function, expected: type[Exception]) -> None:
    try:
        function()
    except expected:
        return
    raise AssertionError(f"Expected {expected.__name__}")


def test_field_isolation_and_record_units(tmp_path: Path) -> None:
    path = tmp_path / "mixed.JSONL"
    save(path, [
        message("user", "Dockerfile Dockerfile SYNTHETIC_CANARY_4938"),
        message("assistant", "assistant Dockerfile"),
        {"type": "message", "message": {"role": "assistant", "content": [
            {"type": "toolCall", "name": "edit", "arguments": {"path": "Dockerfile"}},
            {"type": "toolCall", "name": "read", "arguments": {"path": "Dockerfile"}},
        ]}},
        {"type": "user", "message": {"role": "user", "content": [
            {"type": "tool_result", "content": "result Dockerfile"},
        ]}},
        {"type": "assistant", "message": {"role": "assistant", "content": [
            {"type": "tool_use", "name": "Write", "input": {"file_path": "Dockerfile"}},
        ]}},
        message("toolResult", "result Dockerfile"),
        {"display": "history Dockerfile"},
        {"isMeta": True, "message": {"role": "user", "content": "Dockerfile"}},
        {"isCompactSummary": True, "message": {"role": "user", "content": "Dockerfile"}},
        {"type": "message", "message": {"role": "user", "content": [
            {"type": "image", "data": "Dockerfile"},
        ]}},
    ])
    scan = scanner(tmp_path)
    users = scan([str(path)], ["dockerfile"])
    assert users["matched_records"] == 2
    assert users["matched_records_by_term"] == {"dockerfile": 2}
    assert users["records_seen"] == users["records_parsed"] == 10
    assert users["records_with_selected_text"] == 2
    assert users["records_without_selected_text"] == 8
    assert "SYNTHETIC_CANARY_4938" not in json.dumps(users)
    assert scan([str(path)], ["Dockerfile"], "assistant_text")["matched_records"] == 1
    assert scan([str(path)], ["Dockerfile"], "tool_calls")["matched_records"] == 2
    assert scan([str(path)], ["Dockerfile"], "tool_results")["matched_records"] == 2
    assert scan([str(path)], ["Dockerfile"], "all_text")["matched_records"] == 7
    assert scan([str(path)], [], "tool_calls")["matched_records"] == 2


def test_scans_past_file_and_byte_caps(tmp_path: Path) -> None:
    for index in range(205):
        save(tmp_path / f"{index:03}.jsonl", [message("user", "common")])
    late = tmp_path / "z.jsonl"
    save(late, [{"type": "session", "padding": "x" * (5 * 1024 * 1024)},
                message("user", "common late")])
    result = scanner(tmp_path)([str(tmp_path)], ["common", "late"], max_examples=2)
    assert result["files_discovered"] == result["files_scanned"] == 206
    assert result["records_seen"] == result["records_parsed"] == 207
    assert result["matched_records"] == 206
    assert result["matched_records_by_term"] == {"common": 206, "late": 1}
    assert len(result["examples"]) == 2
    assert result["examples_omitted"] == 204
    assert result["complete"] is True


def test_bad_records_remain_visible_and_scanning_continues(tmp_path: Path) -> None:
    path = tmp_path / "broken.jsonl"
    path.write_bytes(b"\n{invalid\n\xff\n" + json.dumps(message("user", "after errors")).encode() + b"\n")
    result = scanner(tmp_path)([str(path)], ["after"], max_examples=0)
    assert result["records_seen"] == 3
    assert result["records_parsed"] == 1
    assert result["parse_errors"] == 2
    assert result["blank_lines"] == 1
    assert result["matched_records"] == 1
    assert result["examples"] == []
    assert result["examples_omitted"] == 1
    assert {error["line"] for error in result["errors"]} == {2, 3}
    assert result["complete"] is False


def test_scope_symlinks_and_overlaps(tmp_path: Path) -> None:
    root = tmp_path / "corpus"
    root.mkdir()
    inside = root / "inside.jsonl"
    outside = tmp_path / "outside.jsonl"
    save(inside, [message("user", "inside")])
    save(outside, [message("user", "outside")])
    (root / "linked.jsonl").symlink_to(outside)
    (root / "linked-directory").symlink_to(tmp_path, target_is_directory=True)
    scan = scanner(root)
    result = scan([str(root), str(inside)], ["inside", "outside"])
    assert result["files_scanned"] == 1
    assert result["matched_records_by_term"] == {"inside": 1, "outside": 0}
    assert result["symlinks_skipped"] == 2
    rejected(lambda: scan([str(outside)], ["outside"]), PermissionError)
    rejected(lambda: scan([str(root / ".." / "outside.jsonl")], []), PermissionError)
    rejected(lambda: scan([str(root / "linked.jsonl")], []), ValueError)


def test_empty_and_invalid_selections_fail_safely(tmp_path: Path) -> None:
    scan = scanner(tmp_path)
    rejected(lambda: scan([str(tmp_path)], []), ValueError)
    rejected(lambda: scan([str(tmp_path / "missing.jsonl")], []), FileNotFoundError)
    rejected(lambda: scan([], []), ValueError)
    rejected(lambda: scan([str(tmp_path)], ["x", "X"]), ValueError)
    rejected(lambda: scan([str(tmp_path)], [""], "user_text"), ValueError)
    rejected(lambda: scan([str(tmp_path)], [], "shell"), ValueError)
    rejected(lambda: scan([str(tmp_path)], [], max_examples=51), ValueError)
    path = tmp_path / "metadata.jsonl"
    save(path, [{"type": "session", "cwd": "unrelated metadata"}])
    assert scan([str(path)], ["metadata"])["complete"] is False


if __name__ == "__main__":
    checks = (
        test_field_isolation_and_record_units,
        test_scans_past_file_and_byte_caps,
        test_bad_records_remain_visible_and_scanning_continues,
        test_scope_symlinks_and_overlaps,
        test_empty_and_invalid_selections_fail_safely,
    )
    for check in checks:
        with TemporaryDirectory(prefix="omp-jsonl-check-") as directory:
            check(Path(directory))
        print(f"PASS {check.__name__}")
    print(f"Passed {len(checks)} scanner behaviour checks")
