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


def main(argv=None):
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--input", required=True,
                        help="JSON file containing human relevance labels")
    parser.add_argument("--output", default="data/research_precision_report.json")
    parser.add_argument("--k", type=int, default=10)
    args = parser.parse_args(argv)
    with open(args.input, encoding="utf-8") as handle:
        dataset = json.load(handle)
    report = evaluate_precision_at_k(dataset, args.k)
    with open(args.output, "w", encoding="utf-8") as handle:
        json.dump(report, handle, indent=2, ensure_ascii=False)
    print("Human-labelled {} across {} topics: {:.3f}".format(
        report["metric"], report["topic_count"], report["mean_precision_at_k"]))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
