"""Generate the authoritative Ficta Cast portrait batch on CUDA."""

from __future__ import annotations

import argparse
import hashlib
import json
from pathlib import Path

import torch
from diffusers import StableDiffusionXLPipeline


MODEL = "SG161222/RealVisXL_V5.0"
REVISION = "ac93e0dda1f6d448cae19bbfab8c5e720a5e48bc"
ETHNICITY_PROMPT = {
    "European": "European",
    "Muslim": "Middle Eastern or South Asian",
    "Hispanic": "Hispanic or Latino",
    "EastAsian": "East Asian",
    "Celtic": "north-west European",
}


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("jobs", type=Path)
    parser.add_argument("output", type=Path)
    parser.add_argument("--model-file", type=Path, required=True)
    parser.add_argument("--batch-size", type=int, default=2)
    parser.add_argument("--person-key", action="append", default=[])
    args = parser.parse_args()
    payload = json.loads(args.jobs.read_text(encoding="utf-8"))
    jobs = payload["people"] if isinstance(payload, dict) else payload
    args.output.mkdir(parents=True, exist_ok=True)
    if not torch.cuda.is_available():
        raise RuntimeError("CUDA is required for the Cast portrait release")
    if args.person_key:
        requested = set(args.person_key)
        jobs = [job for job in jobs if job["key"] in requested]
        missing = requested - {job["key"] for job in jobs}
        if missing:
            raise ValueError("unknown Cast person keys: " + ", ".join(sorted(missing)))
    signatures_path = args.output / ".headshot-signatures.json"
    try:
        signatures = json.loads(signatures_path.read_text(encoding="utf-8"))
    except (FileNotFoundError, json.JSONDecodeError):
        signatures = {}
    pending = [
        job for job in jobs
        if signatures.get(job["key"]) != job["profile_signature"]
        or not (args.output / f"{job['key']}.png").is_file()
    ]
    pipe = StableDiffusionXLPipeline.from_single_file(
        str(args.model_file.resolve()), config=MODEL, revision=REVISION,
        torch_dtype=torch.float16, safety_checker=None,
    ).to("cuda")
    pipe.set_progress_bar_config(disable=True)
    negative = (
        "side view, three-quarter view, tilted head, hand, glamour, editorial, scarf, "
        "dramatic shadow, shallow focus, airbrushed, waxy, CGI, illustration, cyan skin, "
        "corpse skin, text, logo, watermark, malformed face, duplicate person"
    )
    for offset in range(0, len(pending), args.batch_size):
        batch = pending[offset:offset + args.batch_size]
        prompts = [
            "photorealistic passport headshot, "
            f"{ETHNICITY_PROMPT.get(job['ethnicity'], job['ethnicity'])} {job['sex']} "
            f"age {job['age_group']}, {job['seniority']} business professional, "
            "frontal, direct eye contact, upright, square shoulders, centered symmetrical ID crop, "
            "dark navy or charcoal business clothing, pale blue-grey studio, even biometric lighting, "
            "sharp natural skin texture, contemporary corporate photography, cool desaturated "
            "steel-blue wash, lifted cool blacks, believable warm skin, low saturation"
            for job in batch
        ]
        generators = [
            torch.Generator(device="cuda").manual_seed(
                int.from_bytes(hashlib.sha256(
                    (job["key"] + ":" + job["profile_signature"]).encode()
                ).digest()[:8], "big")
            )
            for job in batch
        ]
        images = pipe(
            prompts, negative_prompt=[negative] * len(batch), generator=generators,
            num_inference_steps=30, guidance_scale=5.0, height=1024, width=1024,
        ).images
        for job, image in zip(batch, images, strict=True):
            image.save(args.output / f"{job['key']}.png", optimize=True)
            signatures[job["key"]] = job["profile_signature"]
        candidate = signatures_path.with_suffix(".tmp")
        candidate.write_text(
            json.dumps(signatures, indent=2, sort_keys=True) + "\n", encoding="utf-8"
        )
        candidate.replace(signatures_path)
        print(f"generated {min(offset + len(batch), len(pending))}/{len(pending)}", flush=True)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
