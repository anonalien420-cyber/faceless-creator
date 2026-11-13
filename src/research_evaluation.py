"""Human-labelled precision@k evaluation for Deep Scan research discovery.

This tool never creates relevance labels. Every result must be judged by a
human as relevant=True or relevant=False before a metric is reported.
"""
import argparse
import json


def evaluate_precision_at_k(dataset, k=10):
    if not isinstance(k, int) or k < 1:
        raise ValueError("k must be a positive integer")
    topics = dataset.get("topics", [])
    if not topics:
        raise ValueError("At least one human-labelled topic is required")
    per_topic = []
    for topic in topics:
        name = str(topic.get("topic") or "").strip()
        results = topic.get("results", [])
        if not name:
            raise ValueError("Every evaluation topic needs a name")
        if len(results) < k:
            raise ValueError("{} needs at least {} labelled results".format(name, k))
        labels = []
        seen = set()
        for row in results[:k]:
            source_id = str(row.get("source_id") or "").strip()
            if not source_id or source_id in seen:
                raise ValueError("{} has a missing or duplicate source_id".format(name))
            seen.add(source_id)
            label = row.get("relevant")
            if not isinstance(label, bool):
                raise ValueError("{} source {} needs a human boolean relevance label".format(name, source_id))
            labels.append(label)
        precision = sum(1 for label in labels if label) / float(k)
        per_topic.append({"topic": name, "k": k, "relevant": sum(labels),
                          "labelled": k, "precision_at_k": precision})
    mean_precision = sum(row["precision_at_k"] for row in per_topic) / len(per_topic)
    return {
        "schema_version": 1,
        "metric": "precision@{}".format(k),
        "topic_count": len(per_topic),
        "mean_precision_at_k": mean_precision,
        "per_topic": per_topic,
        "disclaimer": "Human-labelled topical relevance only; not source authenticity, claim truth, or statistical significance.",
    }


def compare_precision_at_k(dataset, k=10):
    if "baseline" not in dataset or "phase2" not in dataset:
        raise ValueError("Comparison input requires baseline and phase2 datasets")
    baseline = evaluate_precision_at_k(dataset["baseline"], k)
    phase2 = evaluate_precision_at_k(dataset["phase2"], k)
    return {
        "schema_version": 1,
        "metric": "precision@{}".format(k),
        "baseline": baseline,
        "phase2": phase2,
        "absolute_delta": phase2["mean_precision_at_k"] - baseline["mean_precision_at_k"],
        "disclaimer": "Difference in human-labelled topical relevance only; not claim truth, source authenticity, or causal proof.",
    }


def main(argv=None):
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--input", required=True,
                        help="JSON file containing human relevance labels")
    parser.add_argument("--output", default="data/research_precision_report.json")
    parser.add_argument("--k", type=int, default=10)
    args = parser.parse_args(argv)
    with open(args.input, encoding="utf-8") as handle:
        dataset = json.load(handle)
    if "baseline" in dataset and "phase2" in dataset:
        report = compare_precision_at_k(dataset, args.k)
        score = report["phase2"]["mean_precision_at_k"]
        count = report["phase2"]["topic_count"]
    else:
        report = evaluate_precision_at_k(dataset, args.k)
        score = report["mean_precision_at_k"]
        count = report["topic_count"]
    with open(args.output, "w", encoding="utf-8") as handle:
        json.dump(report, handle, indent=2, ensure_ascii=False)
    print("Human-labelled {} across {} topics: {:.3f}".format(
        report["metric"], count, score))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
