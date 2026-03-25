import argparse
import hashlib
import json
import math
import tempfile
import time
from dataclasses import asdict, dataclass
from datetime import UTC, datetime
from io import BytesIO
from pathlib import Path
from typing import Any

import pandas as pd
from huggingface_hub import HfApi, hf_hub_download


SCHEMA_VERSION = "1.0.0"
REQUIRED_PROJECT_PREFIXES = (
    "audio/",
    "index/",
    "index/shards/",
    "validations/",
    "audit/",
)
REQUIRED_PLACEHOLDER_FILES = (
    "audio/.gitkeep",
    "index/.gitkeep",
    "index/shards/.gitkeep",
    "validations/.gitkeep",
    "audit/.gitkeep",
)
REQUIRED_DETECTIONS_COLUMNS = (
    "detection_key",
    "audio_id",
    "scientific_name",
    "confidence",
    "start_time",
    "end_time",
)
SUPPORTED_AUDIO_EXTENSIONS = {".wav", ".mp3", ".flac", ".ogg", ".m4a"}


@dataclass(slots=True)
class ShardMetadata:
    path: str
    rows: int
    sha256: str
    size_bytes: int


def _utcnow_iso() -> str:
    return datetime.now(UTC).replace(microsecond=0).isoformat()


def _upload_text(api: HfApi, dataset_repo: str, path_in_repo: str, content: str) -> None:
    api.upload_file(
        path_or_fileobj=BytesIO(content.encode("utf-8")),
        path_in_repo=path_in_repo,
        repo_id=dataset_repo,
        repo_type="dataset",
    )


def _upload_empty_file(api: HfApi, dataset_repo: str, path_in_repo: str) -> None:
    api.upload_file(
        path_or_fileobj=BytesIO(b""),
        path_in_repo=path_in_repo,
        repo_id=dataset_repo,
        repo_type="dataset",
    )


def ensure_project_dataset_structure(
    api: HfApi,
    project_slug: str,
    dataset_repo: str,
    create_private_repo: bool,
) -> dict[str, Any]:
    api.create_repo(
        repo_id=dataset_repo,
        repo_type="dataset",
        private=create_private_repo,
        exist_ok=True,
    )

    files = set(api.list_repo_files(repo_id=dataset_repo, repo_type="dataset"))
    created_paths: list[str] = []

    for placeholder in REQUIRED_PLACEHOLDER_FILES:
        if placeholder not in files:
            _upload_empty_file(api=api, dataset_repo=dataset_repo, path_in_repo=placeholder)
            created_paths.append(placeholder)

    manifest_path = "manifest.json"
    if manifest_path not in files:
        manifest = {
            "schema_version": SCHEMA_VERSION,
            "project_slug": project_slug,
            "dataset_repo_id": dataset_repo,
            "created_at": _utcnow_iso(),
            "updated_at": _utcnow_iso(),
            "index": {
                "total_detections": 0,
                "total_audio_files": 0,
                "shard_size": 0,
                "shards": [],
            },
        }
        _upload_text(api=api, dataset_repo=dataset_repo, path_in_repo=manifest_path, content=json.dumps(manifest, indent=2))
        created_paths.append(manifest_path)

    return {
        "dataset_repo": dataset_repo,
        "project_slug": project_slug,
        "created_paths": created_paths,
    }


def load_detections_table(detections_file: str) -> pd.DataFrame:
    input_path = Path(detections_file)
    if not input_path.exists():
        raise FileNotFoundError(f"Detections file not found: {detections_file}")

    suffix = input_path.suffix.lower()
    if suffix == ".csv":
        frame = pd.read_csv(input_path)
    elif suffix in {".jsonl", ".ndjson"}:
        frame = pd.read_json(input_path, lines=True)
    elif suffix == ".parquet":
        frame = pd.read_parquet(input_path)
    else:
        raise ValueError("Unsupported detections format. Use .csv, .jsonl/.ndjson, or .parquet")

    missing_columns = [col for col in REQUIRED_DETECTIONS_COLUMNS if col not in frame.columns]
    if missing_columns:
        raise ValueError(f"Missing required columns: {', '.join(missing_columns)}")

    if frame.empty:
        return frame

    deduped = frame.drop_duplicates(subset=["detection_key"], keep="last")
    return deduped.sort_values(by=["detection_key"]).reset_index(drop=True)


def _file_sha256(file_path: Path) -> str:
    hasher = hashlib.sha256()
    with file_path.open("rb") as handle:
        for chunk in iter(lambda: handle.read(65536), b""):
            hasher.update(chunk)
    return hasher.hexdigest()


def build_shards_in_directory(frame: pd.DataFrame, output_dir: Path, shard_size: int) -> list[ShardMetadata]:
    if shard_size <= 0:
        raise ValueError("shard_size must be greater than zero")

    output_dir.mkdir(parents=True, exist_ok=True)
    shards: list[ShardMetadata] = []

    if frame.empty:
        return shards

    total_rows = len(frame)
    total_shards = math.ceil(total_rows / shard_size)

    for index in range(total_shards):
        start = index * shard_size
        end = min(start + shard_size, total_rows)
        shard_frame = frame.iloc[start:end]
        shard_filename = f"shard-{index:05d}.parquet"
        local_path = output_dir / shard_filename
        shard_frame.to_parquet(local_path, index=False)

        shards.append(
            ShardMetadata(
                path=f"index/shards/{shard_filename}",
                rows=len(shard_frame),
                sha256=_file_sha256(local_path),
                size_bytes=local_path.stat().st_size,
            )
        )

    return shards


def build_manifest_payload(
    project_slug: str,
    dataset_repo: str,
    frame: pd.DataFrame,
    shard_size: int,
    shard_metadata: list[ShardMetadata],
) -> dict[str, Any]:
    now = _utcnow_iso()
    return {
        "schema_version": SCHEMA_VERSION,
        "project_slug": project_slug,
        "dataset_repo_id": dataset_repo,
        "updated_at": now,
        "index": {
            "total_detections": len(frame),
            "total_audio_files": int(frame["audio_id"].nunique()) if not frame.empty else 0,
            "shard_size": shard_size,
            "shards": [asdict(item) for item in shard_metadata],
        },
    }


def discover_audio_files(local_audio_dir: str) -> list[Path]:
    audio_root = Path(local_audio_dir)
    if not audio_root.exists() or not audio_root.is_dir():
        raise FileNotFoundError(f"Audio directory not found: {local_audio_dir}")

    files = [
        path
        for path in audio_root.rglob("*")
        if path.is_file() and path.suffix.lower() in SUPPORTED_AUDIO_EXTENSIONS
    ]
    return sorted(files)


def _chunk_items(items: list[Path], chunk_size: int) -> list[list[Path]]:
    if chunk_size <= 0:
        raise ValueError("chunk_size must be greater than zero")
    return [items[index : index + chunk_size] for index in range(0, len(items), chunk_size)]


def _load_resume_state(state_file: Path) -> dict[str, Any]:
    if not state_file.exists():
        return {"uploaded": [], "failed": []}

    payload = json.loads(state_file.read_text(encoding="utf-8"))
    uploaded = payload.get("uploaded", [])
    failed = payload.get("failed", [])
    return {
        "uploaded": uploaded if isinstance(uploaded, list) else [],
        "failed": failed if isinstance(failed, list) else [],
    }


def _save_resume_state(state_file: Path, uploaded: set[str], failed: set[str]) -> None:
    state_file.parent.mkdir(parents=True, exist_ok=True)
    payload = {
        "updated_at": _utcnow_iso(),
        "uploaded": sorted(uploaded),
        "failed": sorted(failed),
    }
    state_file.write_text(json.dumps(payload, indent=2), encoding="utf-8")


def _upload_audio_with_retry(
    api: HfApi,
    dataset_repo: str,
    local_path: Path,
    path_in_repo: str,
    max_retries: int,
    retry_backoff_seconds: float,
) -> None:
    attempts = 0
    while True:
        attempts += 1
        try:
            api.upload_file(
                path_or_fileobj=str(local_path),
                path_in_repo=path_in_repo,
                repo_id=dataset_repo,
                repo_type="dataset",
            )
            return
        except Exception:
            if attempts > max_retries:
                raise
            time.sleep(retry_backoff_seconds * attempts)


def sync_audio_batches(
    api: HfApi,
    project_slug: str,
    dataset_repo: str,
    local_audio_dir: str,
    batch_size: int,
    max_retries: int,
    retry_backoff_seconds: float,
    resume_state_file: str,
) -> dict[str, Any]:
    ensure_project_dataset_structure(
        api=api,
        project_slug=project_slug,
        dataset_repo=dataset_repo,
        create_private_repo=False,
    )

    all_files = discover_audio_files(local_audio_dir=local_audio_dir)
    state_path = Path(resume_state_file)
    state_payload = _load_resume_state(state_file=state_path)
    uploaded_state = set(str(item) for item in state_payload["uploaded"])

    remote_files = set(api.list_repo_files(repo_id=dataset_repo, repo_type="dataset"))

    pending: list[tuple[Path, str]] = []
    for path in all_files:
        rel = path.relative_to(Path(local_audio_dir)).as_posix()
        repo_path = f"audio/{rel}"

        if repo_path in remote_files:
            uploaded_state.add(repo_path)
            continue

        if repo_path in uploaded_state:
            continue

        pending.append((path, repo_path))

    pending_paths = [item[0] for item in pending]
    by_local_to_repo = {local: repo for local, repo in pending}
    batches = _chunk_items(pending_paths, batch_size) if pending_paths else []

    uploaded_now: set[str] = set()
    failed: set[str] = set()

    for batch_index, batch in enumerate(batches, start=1):
        batch_uploaded = 0
        batch_failed = 0

        for local_path in batch:
            repo_path = by_local_to_repo[local_path]
            try:
                _upload_audio_with_retry(
                    api=api,
                    dataset_repo=dataset_repo,
                    local_path=local_path,
                    path_in_repo=repo_path,
                    max_retries=max_retries,
                    retry_backoff_seconds=retry_backoff_seconds,
                )
                uploaded_now.add(repo_path)
                uploaded_state.add(repo_path)
                batch_uploaded += 1
            except Exception:
                failed.add(repo_path)
                batch_failed += 1

        print(
            json.dumps(
                {
                    "event": "sync-audio-batch",
                    "batch_index": batch_index,
                    "batch_size": len(batch),
                    "uploaded": batch_uploaded,
                    "failed": batch_failed,
                }
            )
        )
        _save_resume_state(state_file=state_path, uploaded=uploaded_state, failed=failed)

    return {
        "project_slug": project_slug,
        "dataset_repo": dataset_repo,
        "total_local_audio_files": len(all_files),
        "pending_uploads": len(pending),
        "uploaded_now": len(uploaded_now),
        "failed": len(failed),
        "resume_state_file": str(state_path),
    }


def build_and_upload_index(
    api: HfApi,
    project_slug: str,
    dataset_repo: str,
    detections_file: str,
    shard_size: int,
) -> dict[str, Any]:
    ensure_project_dataset_structure(
        api=api,
        project_slug=project_slug,
        dataset_repo=dataset_repo,
        create_private_repo=False,
    )

    frame = load_detections_table(detections_file=detections_file)

    with tempfile.TemporaryDirectory(prefix="birdnet-index-") as temp_dir_str:
        temp_dir = Path(temp_dir_str)
        shard_dir = temp_dir / "index" / "shards"
        metadata = build_shards_in_directory(frame=frame, output_dir=shard_dir, shard_size=shard_size)

        for item in metadata:
            local_path = temp_dir / item.path
            api.upload_file(
                path_or_fileobj=str(local_path),
                path_in_repo=item.path,
                repo_id=dataset_repo,
                repo_type="dataset",
            )

    manifest = build_manifest_payload(
        project_slug=project_slug,
        dataset_repo=dataset_repo,
        frame=frame,
        shard_size=shard_size,
        shard_metadata=metadata,
    )
    _upload_text(api=api, dataset_repo=dataset_repo, path_in_repo="manifest.json", content=json.dumps(manifest, indent=2))

    return {
        "project_slug": project_slug,
        "dataset_repo": dataset_repo,
        "total_detections": manifest["index"]["total_detections"],
        "total_audio_files": manifest["index"]["total_audio_files"],
        "total_shards": len(metadata),
    }


def collect_verify_errors(repo_files: set[str], manifest_payload: dict[str, Any], project_slug: str) -> list[str]:
    errors: list[str] = []

    for prefix in REQUIRED_PROJECT_PREFIXES:
        if not any(path.startswith(prefix) for path in repo_files):
            errors.append(f"Missing prefix in dataset repo: {prefix}")

    if manifest_payload.get("schema_version") != SCHEMA_VERSION:
        errors.append(
            f"Unexpected schema_version in manifest: {manifest_payload.get('schema_version')} (expected {SCHEMA_VERSION})"
        )

    if manifest_payload.get("project_slug") != project_slug:
        errors.append(
            f"Manifest project_slug mismatch: {manifest_payload.get('project_slug')} (expected {project_slug})"
        )

    index_section = manifest_payload.get("index", {})
    shards = index_section.get("shards", [])
    if not isinstance(shards, list):
        errors.append("Manifest index.shards must be a list")
        return errors

    for shard in shards:
        shard_path = shard.get("path")
        if not shard_path or not isinstance(shard_path, str):
            errors.append("Shard entry missing path")
            continue
        if shard_path not in repo_files:
            errors.append(f"Shard referenced in manifest not found in repo: {shard_path}")

    return errors


def verify_project(api: HfApi, project_slug: str, dataset_repo: str) -> dict[str, Any]:
    repo_files = set(api.list_repo_files(repo_id=dataset_repo, repo_type="dataset"))
    if "manifest.json" not in repo_files:
        return {
            "ok": False,
            "errors": ["manifest.json not found in dataset repository"],
        }

    manifest_local = hf_hub_download(
        repo_id=dataset_repo,
        repo_type="dataset",
        filename="manifest.json",
    )
    manifest_payload = json.loads(Path(manifest_local).read_text(encoding="utf-8"))
    errors = collect_verify_errors(repo_files=repo_files, manifest_payload=manifest_payload, project_slug=project_slug)

    return {
        "ok": len(errors) == 0,
        "errors": errors,
        "total_files": len(repo_files),
        "total_shards": len(manifest_payload.get("index", {}).get("shards", [])),
    }


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(description="HF dataset project CLI")
    sub = parser.add_subparsers(dest="command", required=True)

    create_project = sub.add_parser("create-project", help="Create project scaffold in HF dataset")
    create_project.add_argument("--project-slug", required=True)
    create_project.add_argument("--dataset-repo", required=True)
    create_project.add_argument("--private", action="store_true", help="Create private dataset repository when absent")

    build_index = sub.add_parser("build-index", help="Build and upload initial detection index")
    build_index.add_argument("--project-slug", required=True)
    build_index.add_argument("--dataset-repo", required=True)
    build_index.add_argument("--detections-file", required=True)
    build_index.add_argument("--shard-size", type=int, default=10000)

    sync_audio = sub.add_parser("sync-audio", help="Upload local audio files in resumable batches")
    sync_audio.add_argument("--project-slug", required=True)
    sync_audio.add_argument("--dataset-repo", required=True)
    sync_audio.add_argument("--local-audio-dir", required=True)
    sync_audio.add_argument("--batch-size", type=int, default=100)
    sync_audio.add_argument("--max-retries", type=int, default=3)
    sync_audio.add_argument("--retry-backoff-seconds", type=float, default=1.0)
    sync_audio.add_argument("--resume-state-file", default=".sync-audio-state.json")

    verify_project = sub.add_parser("verify-project", help="Verify project integrity")
    verify_project.add_argument("--project-slug", required=True)
    verify_project.add_argument("--dataset-repo", required=True)

    return parser


def main() -> int:
    parser = build_parser()
    args = parser.parse_args()
    api = HfApi()

    if args.command == "create-project":
        result = ensure_project_dataset_structure(
            api=api,
            project_slug=args.project_slug,
            dataset_repo=args.dataset_repo,
            create_private_repo=bool(args.private),
        )
        print(json.dumps(result, indent=2))
        return 0

    if args.command == "build-index":
        result = build_and_upload_index(
            api=api,
            project_slug=args.project_slug,
            dataset_repo=args.dataset_repo,
            detections_file=args.detections_file,
            shard_size=args.shard_size,
        )
        print(json.dumps(result, indent=2))
        return 0

    if args.command == "sync-audio":
        result = sync_audio_batches(
            api=api,
            project_slug=args.project_slug,
            dataset_repo=args.dataset_repo,
            local_audio_dir=args.local_audio_dir,
            batch_size=args.batch_size,
            max_retries=args.max_retries,
            retry_backoff_seconds=args.retry_backoff_seconds,
            resume_state_file=args.resume_state_file,
        )
        print(json.dumps(result, indent=2))
        return 0 if result["failed"] == 0 else 1

    if args.command == "verify-project":
        result = verify_project(
            api=api,
            project_slug=args.project_slug,
            dataset_repo=args.dataset_repo,
        )
        print(json.dumps(result, indent=2))
        return 0 if result["ok"] else 1

    parser.error("Unknown command")
    return 2


if __name__ == "__main__":
    raise SystemExit(main())
