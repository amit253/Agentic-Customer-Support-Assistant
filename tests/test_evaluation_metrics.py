from __future__ import annotations

from scripts.run_evaluation import binary_metrics, classification_metrics


def test_binary_metrics_are_computed_from_labels() -> None:
    metrics = binary_metrics(
        [True, True, False, False],
        [True, False, True, False],
    )

    assert metrics["true_positive"] == 1
    assert metrics["true_negative"] == 1
    assert metrics["false_positive"] == 1
    assert metrics["false_negative"] == 1
    assert metrics["precision"] == 0.5
    assert metrics["recall"] == 0.5


def test_classification_metrics_include_confusion_matrix() -> None:
    metrics = classification_metrics(
        ["product_question", "order_status", "order_status"],
        ["product_question", "order_status", "escalate_to_human"],
        ("product_question", "order_status", "escalate_to_human"),
    )

    assert metrics["sample_count"] == 3
    assert metrics["accuracy"] == 2 / 3
    assert metrics["confusion_matrix"]["order_status"]["escalate_to_human"] == 1
