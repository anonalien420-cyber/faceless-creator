"""Validate generated visual manifests against reviewed scene evidence."""
import argparse
import json
import os


def check_visual_manifest(script, manifest):
    expected = {str(scene.get("scene")): scene for scene in script.get("scenes", [])}
    actual = {str(asset.get("scene")): asset for asset in manifest.get("assets", [])}
    errors, warnings = [], []
    for scene_id, scene in expected.items():
        asset = actual.get(scene_id)
        if not asset:
            errors.append("scene {} has no generated asset".format(scene_id))
            continue
        path = asset.get("path", "")
        if not path or not os.path.isfile(path) or os.path.getsize(path) == 0:
            errors.append("scene {} asset is missing or empty".format(scene_id))
        if set(asset.get("claim_ids", [])) != set(scene.get("claim_ids", [])):
            errors.append("scene {} claim IDs do not match its reviewed scene".format(scene_id))
        if set(asset.get("source_ids", [])) != set(scene.get("source_ids", [])):
            errors.append("scene {} source IDs do not match its reviewed scene".format(scene_id))
        if "reconstruction" not in str(asset.get("visual_type", "")).lower():
            errors.append("scene {} lacks AI reconstruction disclosure metadata".format(scene_id))
        if not asset.get("prompt"):
            warnings.append("scene {} has no stored generation prompt".format(scene_id))
    for scene_id in sorted(set(actual) - set(expected)):
        warnings.append("manifest contains unexpected scene {}".format(scene_id))
    return {"passed": not errors, "errors": errors, "warnings": warnings,
            "expected_scenes": len(expected), "generated_scenes": len(actual),
            "disclaimer": manifest.get("disclaimer", "")}


def main(argv=None):
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--script", required=True)
    parser.add_argument("--manifest", required=True)
    parser.add_argument("--output", default="data/visual_qa.json")
    args = parser.parse_args(argv)
    with open(args.script, encoding="utf-8") as fh:
        script = json.load(fh)
    with open(args.manifest, encoding="utf-8") as fh:
        manifest = json.load(fh)
    report = check_visual_manifest(script, manifest)
    os.makedirs(os.path.dirname(args.output) or ".", exist_ok=True)
    with open(args.output, "w", encoding="utf-8") as fh:
        json.dump(report, fh, indent=2)
    print("Visual QA {}: {} scene(s)".format("PASS" if report["passed"] else "FAIL",
                                             report["generated_scenes"]))
    return 0 if report["passed"] else 1


if __name__ == "__main__":
    raise SystemExit(main())
