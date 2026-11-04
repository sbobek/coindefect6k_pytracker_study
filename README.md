# CoinDefect6k study for Tobii-PyTracker

This package has one entry point, `run_study.py`. It downloads and extracts one CoinDefect6k variant when needed, selects a reproducible stratified batch not previously processed, writes a Tobii-PyTracker image-dataset directory, patches the study configuration, and optionally launches the experiment.

## What is included

- `run_study.py`: downloader, safe ZIP extractor, indexer, sampler, output scanner, dataset builder, and launcher.
- `configs/config.yaml`: image-study configuration. Edit monitor resolution, physical width, viewing distance, display number, AOI size, and instructions before collection.
- `configs/mouse_eyetracker_config.yaml`: mouse-emulated tracker for workflow testing.
- `configs/eyetracker_config.yaml`: physical-tracker template. Replace it with the physical-device configuration from the installed Tobii-PyTracker version.
- `data/source/`: extracted full dataset, created on demand.
- `data/study_dataset/<variant>/{good,bad}/`: only the batch selected for the current run.
- `output/`: Tobii-PyTracker recordings. Do not delete it between sessions if previously shown samples must be excluded.

## Requirements

Tobii-PyTracker currently documents Python `>=3.10,<3.11`. Create a Python 3.10 environment and install the project:

```bash
python3.10 -m venv .venv
source .venv/bin/activate        # Windows PowerShell: .venv\Scripts\Activate.ps1
python -m pip install --upgrade pip
pip install -r requirements.txt
```

For installation from source, follow the Tobii-PyTracker documentation because PsychoPy and platform packages may need pinned or system-specific installation.

## Prepare without launching

Manufacturing defects:

```bash
python run_study.py --dataset manufacturing --samples 40 --prepare-only
```

Circulation quality:

```bash
python run_study.py --dataset circulation --samples 40 --prepare-only
```

The first run downloads the matching archive from Zenodo record `18773634`. Later runs skip download and extraction when images already exist in `data/source/<dataset-directory>`. Use `--force-redownload` only to replace the local archive/extraction.

## Run with mouse emulation

```bash
python run_study.py --dataset manufacturing --samples 40
```

The script launches approximately:

```bash
tobii-pytracker --config_file configs/config.yaml \
  --eyetracker_config_file configs/mouse_eyetracker_config.yaml \
  --loop_count 40 --enable_eyetracker
```

Add `--enable-voice` to record voice.

## Run with a physical Tobii tracker

First replace `configs/eyetracker_config.yaml` with the physical-device configuration appropriate for the installed Tobii-PyTracker/PsychoPy version and your tracker. Then run:

```bash
python run_study.py --dataset circulation --samples 40 --physical-eyetracker
```

Calibration and device setup remain the responsibility of Tobii-PyTracker/PsychoPy.

## Sampling behavior

`--samples N` requests **N new stimuli for this run**, not N cumulative stimuli.

1. Images are indexed recursively from the selected CoinDefect6k extraction.
2. Labels are inferred from `good` and `bad` directories. The original `train`/`test` split is recorded in the manifest.
3. Existing `output/` files are scanned recursively. A sample counts as processed only when its stable `cd6k_<12-hex-id>__` token occurs in a screenshot path/name, or in a `data.csv` row with a non-empty `screenshot_file` field.
4. Processed IDs are removed from the candidate pool.
5. The requested batch is allocated as evenly as possible across the remaining `good` and `bad` classes. If one class is exhausted, remaining slots are filled from the other class.
6. Selection is reproducible for a fixed remaining pool and `--seed` (default `42`).
7. The current study folder is rebuilt and a `selection_manifest.csv` maps every copied file to its original path, class, split, and stable ID.

Copied filenames preserve the stable ID. This is necessary for detecting prior trials reliably across output layouts. Keep the `output/` directory and do not rename screenshots until data collection is complete.

If there are fewer than N unprocessed images, the script stops with a clear error rather than silently returning a smaller batch.

## Important configuration checks

Before collecting real data, edit `configs/config.yaml`:

- `display.monitor.resolution`: monitor pixel width and height.
- `display.monitor.width`: physical width in cm.
- `display.monitor.distance`: participant distance in cm.
- `display.monitor.display_number`: PsychoPy display index.
- `display.gui.aoe`: area in which images are presented.
- instructions and optional `bbox_model` (`grid`, `superpixel`, or `saliency`).

The entry point rewrites only `dataset.image.path` and `output.folder` to absolute paths. Other edits are preserved.

## Useful options

```text
--dataset {manufacturing,circulation}  required dataset variant
--samples N                            required number of new stimuli
--seed N                               sampling seed, default 42
--data-dir PATH                        source and study data root
--output-dir PATH                      outputs scanned for screenshots
--config PATH                          main YAML config
--eyetracker-config PATH               mouse/alternative tracker YAML
--physical-eyetracker                  use configs/eyetracker_config.yaml
--enable-voice                         pass --enable_voice
--prepare-only                         do not launch Tobii-PyTracker
--force-redownload                     replace archive and extraction
```

## Validation performed for this package

- `run_study.py` is compiled with `python -m py_compile`.
- A synthetic nested CoinDefect6k layout is indexed.
- Stratified selection is checked.
- A fake screenshot containing a stable ID is detected and excluded from the next selection.
- The generated study dataset contains `good/` and `bad/` class directories plus a manifest.

The actual multi-gigabyte Zenodo archives and a hardware session are not run during package validation. Use `--prepare-only` first to validate download, extraction, and local display configuration.
