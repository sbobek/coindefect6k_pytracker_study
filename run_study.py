#!/usr/bin/env python3
"""Prepare and run a CoinDefect6k Tobii-PyTracker study."""
from __future__ import annotations

import argparse
import csv
import hashlib
import json
import os
import random
import re
import shutil
import subprocess
import sys
import urllib.request
import zipfile
from collections import defaultdict
from dataclasses import dataclass
from pathlib import Path
from typing import Iterable

RECORD_ID = re.compile(r"cd6k_([0-9a-f]{12})__", re.IGNORECASE)
IMAGE_EXTENSIONS = {".jpg", ".jpeg", ".png", ".bmp", ".tif", ".tiff", ".webp"}
DATASETS = {
    "manufacturing": {
        "archive": "dataset_public_manufacturing_defects.zip",
        "dirname": "dataset_public_manufacturing_defects",
        "url": "https://zenodo.org/api/records/18773634/files/dataset_public_manufacturing_defects.zip/content",
    },
    "circulation": {
        "archive": "dataset_public_circulation_quality.zip",
        "dirname": "dataset_public_circulation_quality",
        "url": "https://zenodo.org/api/records/18773634/files/dataset_public_circulation_quality.zip/content",
    },
}

@dataclass(frozen=True)
class Sample:
    source: Path
    relative: str
    split: str
    label: str
    sample_id: str


def parse_args() -> argparse.Namespace:
    p = argparse.ArgumentParser(description=__doc__)
    p.add_argument("--dataset", choices=DATASETS, required=True)
    p.add_argument("--samples", type=int, required=True,
                   help="Number of not-yet-processed samples for this run.")
    p.add_argument("--seed", type=int, default=42)
    p.add_argument("--data-dir", type=Path, default=Path("data"))
    p.add_argument("--output-dir", type=Path, default=Path("output"))
    p.add_argument("--config", type=Path, default=Path("configs/config.yaml"))
    p.add_argument("--eyetracker-config", type=Path,
                   default=Path("configs/mouse_eyetracker_config.yaml"))
    p.add_argument("--physical-eyetracker", action="store_true")
    p.add_argument("--enable-voice", action="store_true")
    p.add_argument("--prepare-only", action="store_true")
    p.add_argument("--force-redownload", action="store_true")
    return p.parse_args()


def download(url: str, destination: Path) -> None:
    destination.parent.mkdir(parents=True, exist_ok=True)
    partial = destination.with_suffix(destination.suffix + ".part")
    print(f"Downloading {url} -> {destination}")
    with urllib.request.urlopen(url) as response, partial.open("wb") as out:
        shutil.copyfileobj(response, out, length=1024 * 1024)
    partial.replace(destination)


def safe_extract(archive: Path, destination: Path) -> None:
    destination.mkdir(parents=True, exist_ok=True)
    base = destination.resolve()
    with zipfile.ZipFile(archive) as zf:
        for member in zf.infolist():
            target = (destination / member.filename).resolve()
            if os.path.commonpath([str(base), str(target)]) != str(base):
                raise RuntimeError(f"Unsafe archive member: {member.filename}")
        zf.extractall(destination)


def has_images(path: Path) -> bool:
    return path.is_dir() and any(p.suffix.lower() in IMAGE_EXTENSIONS for p in path.rglob("*"))


def ensure_dataset(kind: str, data_dir: Path, force: bool) -> Path:
    spec = DATASETS[kind]
    source_dir = data_dir / "source" / spec["dirname"]
    if has_images(source_dir) and not force:
        print(f"Using existing extracted dataset: {source_dir}")
        return source_dir
    archive = data_dir / "archives" / spec["archive"]
    if force or not archive.exists():
        download(spec["url"], archive)
    if source_dir.exists():
        shutil.rmtree(source_dir)
    safe_extract(archive, source_dir)
    if not has_images(source_dir):
        raise RuntimeError(f"No images found after extracting {archive}")
    return source_dir


def infer_split_and_label(relative: Path) -> tuple[str, str] | None:
    parts = [part.lower() for part in relative.parts]
    split = next((p for p in parts if p in {"train", "test", "val", "validation"}), "unspecified")
    label = next((p for p in reversed(parts[:-1]) if p in {"good", "bad"}), None)
    return (split, label) if label else None


def index_samples(root: Path) -> list[Sample]:
    result = []
    for path in sorted(root.rglob("*")):
        if not path.is_file() or path.suffix.lower() not in IMAGE_EXTENSIONS:
            continue
        relative_path = path.relative_to(root)
        inferred = infer_split_and_label(relative_path)
        if inferred is None:
            continue
        split, label = inferred
        relative = relative_path.as_posix()
        sample_id = hashlib.sha256(relative.encode("utf-8")).hexdigest()[:12]
        result.append(Sample(path, relative, split, label, sample_id))
    if not result:
        raise RuntimeError(f"No classifiable good/bad images found below {root}")
    return result


def ids_from_text(value: object) -> set[str]:
    return {match.group(1).lower() for match in RECORD_ID.finditer(str(value or ""))}


def read_data_csv(path: Path) -> list[dict[str, str]]:
    """Read Tobii data.csv, supporting its semicolon delimiter and CSV variants."""
    with path.open("r", encoding="utf-8-sig", newline="") as stream:
        prefix = stream.read(8192)
        stream.seek(0)
        try:
            dialect = csv.Sniffer().sniff(prefix, delimiters=";,\t,")
        except csv.Error:
            dialect = csv.excel
            dialect.delimiter = ";"
        return list(csv.DictReader(stream, dialect=dialect))


def completed_ids(output_dir: Path) -> set[str]:
    """Collect processed IDs from every output/<study_dir>/data.csv."""
    done: set[str] = set()
    if not output_dir.exists():
        return done
    data_files = sorted(p for p in output_dir.rglob("data.csv") if p.is_file())
    for path in data_files:
        try:
            rows = read_data_csv(path)
        except (OSError, UnicodeError, csv.Error) as exc:
            print(f"Warning: cannot read {path}: {exc}", file=sys.stderr)
            continue
        for row in rows:
            # A row represents an investigated sample when input_data identifies a
            # stimulus. screenshot_file is additionally inspected for compatibility.
            input_data = str(row.get("input_data", "") or "").strip()
            screenshot = str(row.get("screenshot_file", "") or "").strip()
            if input_data or screenshot:
                done.update(ids_from_text(input_data))
                done.update(ids_from_text(screenshot))
    print(f"Analyzed {len(data_files)} completed study data.csv file(s).")
    return done


def current_dataset_ids(study_dir: Path) -> set[str]:
    ids: set[str] = set()
    if not study_dir.exists():
        return ids
    for path in study_dir.rglob("*"):
        if path.is_file() and path.suffix.lower() in IMAGE_EXTENSIONS:
            ids.update(ids_from_text(path.name))
    return ids


def select_samples(samples: Iterable[Sample], done: set[str], n: int, seed: int) -> tuple[list[Sample], str]:
    """Use exact/near-exact class stratification when possible, otherwise random fallback."""
    remaining = [sample for sample in samples if sample.sample_id not in done]
    if n < 1:
        raise ValueError("--samples must be at least 1")
    if n > len(remaining):
        raise ValueError(f"Requested {n} samples, but only {len(remaining)} unprocessed samples remain")

    rng = random.Random(seed)
    groups: dict[str, list[Sample]] = defaultdict(list)
    for sample in remaining:
        groups[sample.label].append(sample)
    for group in groups.values():
        rng.shuffle(group)

    labels = sorted(groups)
    # Stratification means all remaining classes can contribute floor/ceil(n/k).
    base, extra = divmod(n, len(labels))
    needed = {label: base + (1 if i < extra else 0) for i, label in enumerate(labels)}
    stratified_possible = all(len(groups[label]) >= needed[label] for label in labels)

    if stratified_possible:
        selected = [sample for label in labels for sample in groups[label][:needed[label]]]
        mode = "stratified"
    else:
        selected = remaining[:]
        rng.shuffle(selected)
        selected = selected[:n]
        mode = "fallback-unstratified"
    rng.shuffle(selected)
    return selected, mode


def populate_study_dataset(selected: list[Sample], target: Path, kind: str,
                           seed: int, mode: str) -> Path:
    if target.exists():
        shutil.rmtree(target)
    target.mkdir(parents=True)
    rows = []
    for order, sample in enumerate(selected):
        class_dir = target / sample.label
        class_dir.mkdir(exist_ok=True)
        safe_name = re.sub(r"[^A-Za-z0-9._-]+", "_", sample.source.name)
        destination = class_dir / f"cd6k_{sample.sample_id}__{safe_name}"
        shutil.copy2(sample.source, destination)
        rows.append({
            "presentation_order": order,
            "sample_id": sample.sample_id,
            "dataset": kind,
            "label": sample.label,
            "source_split": sample.split,
            "source_relative_path": sample.relative,
            "study_relative_path": destination.relative_to(target.parent.parent).as_posix(),
        })
    manifest = target / "selection_manifest.csv"
    with manifest.open("w", encoding="utf-8", newline="") as stream:
        writer = csv.DictWriter(stream, fieldnames=list(rows[0]))
        writer.writeheader()
        writer.writerows(rows)
    (target / "selection_metadata.json").write_text(json.dumps({
        "dataset": kind, "seed": seed, "new_samples": len(selected),
        "sampling_mode": mode,
    }, indent=2), encoding="utf-8")
    return manifest


def patch_config(config_path: Path, dataset_path: Path, output_dir: Path) -> None:
    text = config_path.read_text(encoding="utf-8")
    text, n_dataset = re.subn(r"(?m)^(\s*path:\s*).*$",
                              rf"\g<1>{dataset_path.resolve().as_posix()}", text, count=1)
    text, n_output = re.subn(r"(?m)^(\s*folder:\s*).*$",
                             rf"\g<1>{output_dir.resolve().as_posix()}", text, count=1)
    if n_dataset != 1 or n_output != 1:
        raise RuntimeError(f"Could not patch paths in {config_path}")
    config_path.write_text(text, encoding="utf-8")


def launch(args: argparse.Namespace, count: int) -> int:
    tracker = Path("configs/eyetracker_config.yaml") if args.physical_eyetracker else args.eyetracker_config
    cmd = ["tobii-pytracker", "--config_file", str(args.config),
           "--eyetracker_config_file", str(tracker),
           "--loop_count", str(count), "--enable_eyetracker"]
    if args.enable_voice:
        cmd.append("--enable_voice")
    print("Launching:", " ".join(cmd))
    try:
        return subprocess.run(cmd, check=False).returncode
    except FileNotFoundError:
        print("Error: tobii-pytracker is not installed or is not on PATH.", file=sys.stderr)
        return 127


def main() -> int:
    args = parse_args()
    try:
        root = ensure_dataset(args.dataset, args.data_dir, args.force_redownload)
        all_samples = index_samples(root)
        done = completed_ids(args.output_dir)
        study_dir = args.data_dir / "study_dataset" / args.dataset
        overlap = current_dataset_ids(study_dir) & done
        if overlap:
            print(f"Current study dataset contains {len(overlap)} already processed sample(s); rebuilding it.")
        elif study_dir.exists():
            print("Rebuilding the current study dataset from the remaining sample pool.")
        selected, mode = select_samples(all_samples, done, args.samples, args.seed)
        manifest = populate_study_dataset(selected, study_dir, args.dataset, args.seed, mode)
        patch_config(args.config, study_dir, args.output_dir)
    except (OSError, ValueError, RuntimeError, zipfile.BadZipFile) as exc:
        print(f"Error: {exc}", file=sys.stderr)
        return 2

    counts: dict[str, int] = defaultdict(int)
    for sample in selected:
        counts[sample.label] += 1
    print(f"Indexed {len(all_samples)} images; found {len(done)} processed unique samples.")
    print(f"Prepared {len(selected)} new stimuli ({mode}): {dict(sorted(counts.items()))}")
    print(f"Manifest: {manifest}")
    return 0 if args.prepare_only else launch(args, len(selected))


if __name__ == "__main__":
    raise SystemExit(main())
