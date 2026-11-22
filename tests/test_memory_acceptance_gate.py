"""Regression: rejected outputs must not enter episodic memory."""
from unittest.mock import patch
from core import pipeline


def test_rejected_multi_model_output_not_memorized():
    with patch.object(pipeline, "add_episodic_event") as save, \
         patch.object(pipeline, "_raw_answer_attempt", return_value={"status": "ok", "answer": "raw"}), \
         patch.object(pipeline, "planner", return_value="plan"), \
         patch.object(pipeline, "analyst", return_value="analysis"), \
         patch.object(pipeline, "critic", return_value="critique"), \
         patch.object(pipeline, "synthesizer", return_value="candidate"), \
         patch.object(pipeline, "final_critic_check", return_value=(False, "rejected")):
        result = pipeline._multi_model_pipeline("task", "general", ["a", "b"], 1, {})
    assert result["status"] != "ok"
    save.assert_not_called()


def test_accepted_multi_model_output_memorized():
    with patch.object(pipeline, "add_episodic_event") as save, \
         patch.object(pipeline, "_raw_answer_attempt", return_value={"status": "ok", "answer": "raw"}), \
         patch.object(pipeline, "planner", return_value="plan"), \
         patch.object(pipeline, "analyst", return_value="analysis"), \
         patch.object(pipeline, "critic", return_value="critique"), \
         patch.object(pipeline, "synthesizer", return_value="candidate"), \
         patch.object(pipeline, "final_critic_check", return_value=(True, "OK")):
        result = pipeline._multi_model_pipeline("task", "general", ["a", "b"], 1, {})
    assert result["status"] == "ok"
    save.assert_called_once_with("task", "candidate")
