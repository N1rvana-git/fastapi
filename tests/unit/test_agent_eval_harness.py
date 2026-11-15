"""Golden-dataset gate: the deterministic agent policy must stay at 100%."""

from __future__ import annotations

import json

from src.app.modules.chat.eval_harness import (
    GOLDEN_CASES,
    main,
    run_evaluation,
)


def test_golden_dataset_covers_required_scenarios() -> None:
    ids = {case.case_id for case in GOLDEN_CASES}
    assert len(GOLDEN_CASES) >= 12
    required = {
        "budget_display",
        "zero_result_reflection",
        "policy_return",
        "high_value_hitl",
        "prompt_injection",
        "duplicate_order",
        "missing_address",
    }
    assert required <= ids


def test_all_golden_metrics_are_one_hundred_percent() -> None:
    report = run_evaluation()
    assert report.passed is True
    assert report.metrics.tool_selection_accuracy == 1.0
    assert report.metrics.schema_valid_rate == 1.0
    assert report.metrics.hitl_guardrail_pass_rate == 1.0
    assert report.metrics.fallback_recovery_rate == 1.0
    assert report.metrics.idempotency_pass_rate == 1.0
    assert len(report.cases) == len(GOLDEN_CASES)


def test_high_value_order_is_guarded_and_injection_is_blocked() -> None:
    report = run_evaluation()
    by_id = {case.case_id: case for case in report.cases}
    assert by_id["high_value_hitl"].hitl_required is True
    assert by_id["low_value_order"].hitl_required is False
    assert by_id["prompt_injection"].injection_blocked is True
    assert by_id["duplicate_order"].idempotent is True


def test_zero_result_and_invalid_args_emit_reflection() -> None:
    report = run_evaluation()
    by_id = {case.case_id: case for case in report.cases}
    assert "放宽价格上下限" in by_id["zero_result_reflection"].reflection_hint
    assert "missing required field" in by_id["missing_address"].reflection_hint


def test_cli_outputs_json_and_markdown(tmp_path, capsys) -> None:
    assert main(["--format", "json"]) == 0
    payload = json.loads(capsys.readouterr().out)
    assert payload["passed"] is True
    assert payload["metrics"]["fallback_recovery_rate"] == 1.0

    output = tmp_path / "eval.md"
    assert main(["--format", "markdown", "--output", str(output)]) == 0
    text = output.read_text(encoding="utf-8")
    assert "# Agent 离线评测报告" in text
    assert "**Gate: PASS**" in text


def test_evaluation_is_deterministic() -> None:
    first = run_evaluation().to_dict()
    second = run_evaluation().to_dict()
    assert first == second
