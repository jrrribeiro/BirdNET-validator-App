from pathlib import Path

import pandas as pd

from cli.hf_dataset_cli import (
    _build_detection_key,
    parse_segment_filename,
    run_ingest_segments_dry_run,
)


def test_parse_segment_filename_extracts_components():
    parsed = parse_segment_filename("Aiuab_LN-0500_U16_20260121_153400_42.0-45.0s_98%.wav")
    assert parsed is not None
    source_stem, start_time, end_time, confidence_pct = parsed
    assert source_stem == "Aiuab_LN-0500_U16_20260121_153400"
    assert start_time == 42.0
    assert end_time == 45.0
    assert confidence_pct == 98


def test_detection_key_is_stable_and_long_enough():
    key1 = _build_detection_key(
        project_slug="ppbio-aiuaba",
        source_file="Aiuab_LN-0500_U16_20260121_153400.wav",
        scientific_name="Cyanocorax cyanopogon",
        start_time=42.0,
        end_time=45.0,
    )
    key2 = _build_detection_key(
        project_slug="ppbio-aiuaba",
        source_file="Aiuab_LN-0500_U16_20260121_153400.wav",
        scientific_name="Cyanocorax cyanopogon",
        start_time=42.0,
        end_time=45.0,
    )
    assert key1 == key2
    assert len(key1) >= 16


def test_run_ingest_segments_dry_run_matches_rows(tmp_path: Path):
    segments_root = tmp_path / "segments"
    species_dir = segments_root / "Cyanocorax cyanopogon"
    species_dir.mkdir(parents=True, exist_ok=True)

    (species_dir / "Aiuab_LN-0500_U16_20260121_153400_42.0-45.0s_98%.wav").write_bytes(b"dummy")
    (species_dir / "Aiuab_LN-0500_U16_20260121_153400_45.0-48.0s_88%.wav").write_bytes(b"dummy")

    frame = pd.DataFrame(
        [
            {
                "locality": "PPBIO Aiuaba",
                "point": "Aiuab_LN-0500_U16",
                "date_folder": "20260121",
                "source_file": "Aiuab_LN-0500_U16_20260121_153400.wav",
                "scientific_name": "Cyanocorax cyanopogon",
                "common_name": "White-naped Jay",
                "confidence": 0.98,
                "start_time": 42.0,
                "end_time": 45.0,
                "exact_start": 42.0,
                "exact_end": 45.0,
                "min_freq": 0,
                "max_freq": 15000,
                "box_source": "BirdNET_Original",
                "label": "Cyanocorax cyanopogon_White-naped Jay",
            },
            {
                "locality": "PPBIO Aiuaba",
                "point": "Aiuab_LN-0500_U16",
                "date_folder": "20260121",
                "source_file": "Aiuab_LN-0500_U16_20260121_153400.wav",
                "scientific_name": "Cyanocorax cyanopogon",
                "common_name": "White-naped Jay",
                "confidence": 0.50,
                "start_time": 0.0,
                "end_time": 3.0,
                "exact_start": 0.0,
                "exact_end": 3.0,
                "min_freq": 0,
                "max_freq": 15000,
                "box_source": "BirdNET_Original",
                "label": "Cyanocorax cyanopogon_White-naped Jay",
            },
        ]
    )

    csv_path = tmp_path / "detections.csv"
    frame.to_csv(csv_path, index=False)

    result = run_ingest_segments_dry_run(
        project_slug="ppbio-aiuaba",
        detections_csv=str(csv_path),
        segments_root=str(segments_root),
    )

    assert result["mode"] == "dry-run"
    assert result["csv_rows_total"] == 2
    assert result["segments_found_total"] == 2
    assert result["matched_rows"] == 1
    assert result["unmatched_rows"] == 1
