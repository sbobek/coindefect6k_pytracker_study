# CoinDefect6k study for Tobii-PyTracker

This package has one entry point, `run_study.py`. It downloads and extracts one CoinDefect6k variant when needed, selects a reproducible batch of previously unprocessed samples, writes a Tobii-PyTracker image-dataset directory, patches the study configuration, and optionally launches the experiment.

## What is included

- `run_study.py`: downloader, safe ZIP extractor, indexer, sampler, output scanner, dataset builder, configuration updater, and launcher.
- `configs/config.yaml`: image-study configuration. The monitor resolution is set automatically from the required `--resolution` argument. Edit the physical width, viewing distance, display number, AOI size, and instructions before collection.
- `configs/mouse_eyetracker_config.yaml`: mouse-emulated tracker for workflow testing.
- `configs/eyetracker_config.yaml`: physical-tracker template. Replace it with the physical-device configuration from the installed Tobii-PyTracker version.
- `data/source/`: extracted full dataset, created on demand.
- `data/study_dataset/<variant>/{good,bad}/`: only the batch selected for the current run.
- `output/`: Tobii-PyTracker recordings. Do not delete this directory between sessions if previously processed samples must be excluded from future studies.

## Requirements

Tobii-PyTracker currently documents Python `>=3.10,<3.11`. Create a Python 3.10 environment and install the project:

```bash
python3.10 -m venv .venv
source .venv/bin/activate        # Windows PowerShell: .venv\Scripts\Activate.ps1
python -m pip install --upgrade pip
pip install -r requirements.txt
```

For installation from source, follow the Tobii-PyTracker documentation because PsychoPy and platform packages may need pinned or system-specific installation.

## Screen resolution

The `--resolution` argument is required for every run. It must use the following format:

```text
WIDTHxHEIGHT
```

For example:

```text
800x600
1920x1080
2560x1440
```

The value specifies the display resolution in pixels. The script writes it to `configs/config.yaml` as:

```yaml
display:
  monitor:
    resolution:
      - 2560
      - 1440
```

The specified resolution should match the actual resolution of the monitor on which the study is displayed. Otherwise, PsychoPy may replace it with the detected resolution, and screenshots or calculated image regions may have unexpected dimensions.

Values that do not follow the required format, such as `800`, `800*600`, or `x600`, are rejected.

## Prepare without launching

Use `--prepare-only` to download or reuse the dataset, select the samples, populate the study dataset, and update `configs/config.yaml` without launching Tobii-PyTracker.

Manufacturing defects:

```bash
python run_study.py --dataset manufacturing --samples 40 --resolution 2560x1440 --prepare-only
```

Circulation quality:

```bash
python run_study.py --dataset circulation --samples 40 --resolution 2560x1440 --prepare-only
```

The first run downloads the matching archive from Zenodo record `18773634`. Later runs skip download and extraction when images already exist in `data/source/<dataset-directory>`. Use `--force-redownload` only to replace the local archive and extracted dataset.

## Run with mouse emulation

```bash
python run_study.py --dataset manufacturing --samples 40 --resolution 2560x1440 --enable_voice
```

The script launches approximately:

```bash
tobii-pytracker --config_file configs/config.yaml \
  --eyetracker_config_file configs/mouse_eyetracker_config.yaml \
  --loop_count 40 --enable_eyetracker --enable_voice
```

The `--enable_voice` option enables voice recording during the study.

## Run with a physical Tobii tracker

First replace `configs/eyetracker_config.yaml` with the physical-device configuration appropriate for the installed Tobii-PyTracker and PsychoPy versions and your tracker.

Then run:

```bash
python run_study.py --dataset circulation --samples 40 --resolution 2560x1440 --physical-eyetracker --enable_voice
```

Calibration and device setup remain the responsibility of Tobii-PyTracker and PsychoPy.

## Sampling behavior

`--samples N` requests **N new stimuli for this run**, not N cumulative stimuli.

1. Images are indexed recursively from the selected CoinDefect6k extraction.
2. Labels are inferred from the `good` and `bad` directories. The original `train`, `test`, or validation split is recorded in the manifest.
3. All files matching `output/<manufacturing|circulation>/<study-directory>/data.csv` are found recursively.
4. Processed samples are identified using the stable `cd6k_<12-hex-id>__` token stored in the `input_data` or `screenshot_file` columns.
5. Processed IDs from all previous studies are removed from the candidate pool.
6. The script checks whether the current study dataset contains already processed samples. If it does, the study dataset is rebuilt automatically.
7. The script first attempts to allocate the requested batch evenly across the remaining `good` and `bad` classes.
8. If stratified sampling is not possible, the script selects the requested number of samples from all remaining unprocessed samples without enforcing class balance.
9. Selection is reproducible for a fixed remaining pool and `--seed`, whose default value is `42`.
10. The current study directory is rebuilt, and `selection_manifest.csv` maps every copied file to its original path, class, split, and stable ID.
11. The selected sampling strategy is recorded in `selection_metadata.json` as either `stratified` or `fallback-unstratified`.

Copied filenames preserve the stable sample ID. This is necessary for reliably matching samples against records from previous studies.

Keep the complete `output/` directory until data collection is finished. Removing study output directories may cause previously investigated samples to become eligible for selection again.

If fewer than `N` unprocessed images remain, the script stops with an error rather than silently returning a smaller batch.

## Important configuration checks

Before collecting real data, check `configs/config.yaml`:

- `display.monitor.resolution`: set automatically from the required `--resolution WIDTHxHEIGHT` argument.
- `display.monitor.width`: physical monitor width in centimetres.
- `display.monitor.distance`: distance between the participant and monitor in centimetres.
- `display.monitor.display_number`: PsychoPy display index.
- `display.gui.aoe`: area in which images are presented.
- Instructions shown before and after the study.
- The image `bbox_model`, such as `grid`, `superpixel`, or `saliency`.

The entry point automatically rewrites:

- `dataset.image.path`
- `display.monitor.resolution`
- `output.folder`

Other configuration values are preserved.

## Useful options

```text
--dataset {manufacturing,circulation}
                                      required dataset variant

--samples N                           required number of new stimuli

--resolution WIDTHxHEIGHT             required display resolution in pixels,
                                      for example 800x600 or 2560x1440

--seed N                              sampling seed, default 42

--data-dir PATH                       source and study data root

--output-dir PATH                     directory containing the output of
                                      current and previous studies

--config PATH                         main YAML configuration file

--eyetracker-config PATH              mouse or alternative tracker YAML file

--physical-eyetracker                 use configs/eyetracker_config.yaml

--enable_voice                        enable voice recording

--prepare-only                        prepare the dataset and configuration
                                      without launching Tobii-PyTracker

--force-redownload                    replace the downloaded archive and
                                      extracted dataset
```

## Examples

Prepare four manufacturing samples for a `1920x1080` display without launching the study:

```bash
python run_study.py \
  --dataset manufacturing \
  --samples 4 \
  --resolution 1920x1080 \
  --prepare-only
```

Run a manufacturing study with mouse-based eye-tracker emulation and voice recording:

```bash
python run_study.py \
  --dataset manufacturing \
  --samples 40 \
  --resolution 2560x1440 \
  --enable_voice
```

Run a circulation study with a physical eye tracker and voice recording:

```bash
python run_study.py \
  --dataset circulation \
  --samples 40 \
  --resolution 2560x1440 \
  --physical-eyetracker \
  --enable_voice
```

On Windows PowerShell, the same command can be formatted as:

```powershell
python run_study.py `
  --dataset manufacturing `
  --samples 40 `
  --resolution 2560x1440 `
  --enable_voice
```

## Validation performed for this package

- `run_study.py` is compiled with `python -m py_compile`.
- The `--resolution` argument is validated against the `WIDTHxHEIGHT` format.
- The specified resolution is written to `display.monitor.resolution` in `configs/config.yaml`.
- A synthetic nested CoinDefect6k layout is indexed.
- Stratified selection is checked.
- The unstratified fallback is checked.
- Previous `output/<manufacturing|circulation>/<study-directory>/data.csv` files are analyzed.
- Previously processed samples are excluded from subsequent selection.
- The generated study dataset contains `good/` and `bad/` class directories plus a manifest.

The actual multi-gigabyte Zenodo archives and a hardware session are not run during package validation. Use `--prepare-only` first to validate download, extraction, sample selection, and local display configuration.
