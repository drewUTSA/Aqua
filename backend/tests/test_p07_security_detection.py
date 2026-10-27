"""Blue-side terminal evidence is useful without reflecting private failures."""

import logging

from workspace.contracts import FirstSubmission


def test_child_failure_logs_fixed_correlated_outcome_without_private_content(
    security, caplog
):
    service = security.service()
    _, session = security.session()
    private_prompt = "PRIVATE_PROMPT_DO_NOT_LOG"
    private_error = "PRIVATE_PROVIDER_ERROR token=password SQL=SELECT_SECRET"
    saved, _ = service.enqueue(
        session, FirstSubmission(**security.world.body(private_prompt))
    )

    def fail():
        raise RuntimeError(private_error)

    security.engine.hook = fail
    caplog.set_level(logging.INFO, logger="aqua.analysis")
    assert service.tick()
    messages = [
        item.getMessage() for item in caplog.records if item.name == "aqua.analysis"
    ]
    assert len(messages) == 1
    assert "analysis_terminal" in messages[0] and saved["request"]["id"] in messages[0]
    assert "outcome=interrupted" in messages[0] and "child_reaped=True" in messages[0]
    assert private_prompt not in caplog.text and private_error not in caplog.text
    assert "Traceback" not in caplog.text and "SELECT_SECRET" not in caplog.text
