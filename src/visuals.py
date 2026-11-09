"""Optional ComfyUI API integration for AI reconstruction assets.

Requires a user-supplied ComfyUI API workflow JSON. The workflow must contain
{{PROMPT}} and optionally {{NEGATIVE_PROMPT}} / {{SEED}} placeholders in node
inputs. No provider is called unless COMFYUI_BASE_URL is configured.
"""
import argparse
import hashlib
import json
import os
import random
import time
import urllib.parse
import urllib.request


NEGATIVE = ("modern objects, anachronistic clothing, fantasy armor, invented "
            "insignia, readable fake text, watermark, logo, impossible anatomy")


def _request(base, path, payload=None, timeout=30):
    data = None if payload is None else json.dumps(payload).encode("utf-8")
    req = urllib.request.Request(base.rstrip("/") + path, data=data,
        headers={"Content-Type": "application/json"} if data is not None else {})
    with urllib.request.urlopen(req, timeout=timeout) as response:
        raw = response.read()
        return json.loads(raw.decode("utf-8")) if raw else {}


def _replace(value, prompt, negative, seed):
    if isinstance(value, dict):
        return {k: _replace(v, prompt, negative, seed) for k, v in value.items()}
    if isinstance(value, list):
        return [_replace(v, prompt, negative, seed) for v in value]
    if isinstance(value, str):
        return (value.replace("{{PROMPT}}", prompt)
                     .replace("{{NEGATIVE_PROMPT}}", negative)
                     .replace("{{SEED}}", str(seed)))
    return value


def _download(base, item, output):
    query = urllib.parse.urlencode({k: item.get(k, "") for k in
                                    ("filename", "subfolder", "type")})
    req = urllib.request.Request(base.rstrip("/") + "/view?" + query)
    with urllib.request.urlopen(req, timeout=120) as response, open(output, "wb") as fh:
        fh.write(response.read())
    if not os.path.exists(output) or os.path.getsize(output) == 0:
        raise RuntimeError("ComfyUI returned an empty asset")
    return output


def generate_scene(scene, workflow, base_url, outdir, media_type="image",
                   timeout=600, poll_interval=2):
    if media_type not in ("image", "video"):
        raise ValueError("media_type must be image or video")
    os.makedirs(outdir, exist_ok=True)
    prompt = scene.get("image_prompt" if media_type == "image" else "animation_prompt", "")
    if not prompt.strip():
        raise ValueError("Scene has no {} prompt".format(media_type))
    seed = random.randint(1, 2**31 - 1)
    payload = _replace(workflow, prompt, NEGATIVE, seed)
    response = _request(base_url, "/prompt", {"prompt": payload})
    prompt_id = response.get("prompt_id")
    if not prompt_id:
        raise RuntimeError("ComfyUI did not return a prompt_id: {}".format(response))
    deadline = time.time() + timeout
    history = {}
    while time.time() < deadline:
        history = _request(base_url, "/history/" + urllib.parse.quote(prompt_id))
        if prompt_id in history and history[prompt_id].get("outputs"):
            break
        time.sleep(poll_interval)
    else:
        raise TimeoutError("ComfyUI generation timed out for {}".format(prompt_id))
    outputs = history[prompt_id].get("outputs", {})
    images, videos = [], []
    for node in outputs.values():
        images.extend(node.get("images", []))
        videos.extend(node.get("videos", []))
        videos.extend(node.get("gifs", []))
    candidates = images if media_type == "image" else videos
    if not candidates:
        expected = "image" if media_type == "image" else "video/GIF"
        raise RuntimeError("ComfyUI completed without requested {} output".format(expected))
    item = candidates[0]
    ext = os.path.splitext(item.get("filename", ""))[1] or (".png" if media_type == "image" else ".mp4")
    filename = "scene-{:03d}-{}{}".format(int(scene.get("scene", 0)),
                                           media_type, ext)
    path = _download(base_url, item, os.path.join(outdir, filename))
    return {"path": path, "type": "image" if media_type == "image" else "video",
            "scene": scene.get("scene"), "claim_ids": scene.get("claim_ids", []),
            "source_ids": scene.get("source_ids", []), "prompt_id": prompt_id,
            "seed": seed, "visual_type": scene.get("visual_type",
                "AI reconstruction: interpretive, not archival"),
            "prompt": prompt}


def generate_script_assets(script, workflow_path, base_url, outdir,
                           media_type="image", timeout=600):
    with open(workflow_path, encoding="utf-8") as fh:
        workflow = json.load(fh)
    workflow_hash = hashlib.sha256(json.dumps(workflow, sort_keys=True).encode("utf-8")).hexdigest()
    manifest_path = os.path.join(outdir, "visual_manifest.json")
    os.makedirs(outdir, exist_ok=True)
    previous = {}
    if os.path.exists(manifest_path):
        try:
            with open(manifest_path, encoding="utf-8") as fh:
                previous = {str(a.get("scene")): a for a in json.load(fh).get("assets", [])}
        except (OSError, ValueError, AttributeError):
            previous = {}
    manifest = []
    for scene in script.get("scenes", []):
        prompt = scene.get("image_prompt" if media_type == "image" else "animation_prompt", "")
        fingerprint = hashlib.sha256((prompt + workflow_hash + media_type).encode("utf-8")).hexdigest()
        cached = previous.get(str(scene.get("scene")))
        if (cached and cached.get("fingerprint") == fingerprint
                and os.path.exists(cached.get("path", ""))
                and os.path.getsize(cached.get("path", "")) > 0):
            manifest.append(cached)
            continue
        asset = generate_scene(scene, workflow, base_url, outdir,
                               media_type=media_type, timeout=timeout)
        asset["fingerprint"] = fingerprint
        manifest.append(asset)
        # Persist after every completed scene so an interrupted job can resume.
        partial = {"topic": script.get("topic"), "format": script.get("format"),
                   "assets": manifest,
                   "disclaimer": "AI-generated interpretive reconstructions; never archival footage."}
        with open(manifest_path + ".tmp", "w", encoding="utf-8") as fh:
            json.dump(partial, fh, indent=2, ensure_ascii=False)
            fh.flush()
            os.fsync(fh.fileno())
        os.replace(manifest_path + ".tmp", manifest_path)
    result = {"topic": script.get("topic"), "format": script.get("format"),
              "assets": manifest,
              "disclaimer": "AI-generated interpretive reconstructions; never archival footage."}
    with open(manifest_path, "w", encoding="utf-8") as fh:
        json.dump(result, fh, indent=2, ensure_ascii=False)
    return result


def main(argv=None):
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--script", required=True)
    parser.add_argument("--workflow", required=True)
    parser.add_argument("--outdir", default="data/generated_visuals")
    parser.add_argument("--media-type", choices=["image", "video"], default="image")
    parser.add_argument("--base-url", default=os.environ.get("COMFYUI_BASE_URL", ""))
    parser.add_argument("--timeout", type=int, default=600)
    args = parser.parse_args(argv)
    if not args.base_url:
        parser.error("Set COMFYUI_BASE_URL or pass --base-url")
    with open(args.script, encoding="utf-8") as fh:
        script = json.load(fh)
    result = generate_script_assets(script, args.workflow, args.base_url,
                                    args.outdir, args.media_type, args.timeout)
    print("Generated {} {} asset(s)".format(len(result["assets"]), args.media_type))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
