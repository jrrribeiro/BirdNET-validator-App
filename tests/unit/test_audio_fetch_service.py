from pathlib import Path

import pytest

from src.cache.ephemeral_cache_manager import EphemeralCacheManager
from src.services.audio_fetch_service import AudioFetchService


def test_fetch_downloads_and_then_hits_cache(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    remote_file = tmp_path / "remote.wav"
    remote_file.write_bytes(b"audio-bytes")
    calls: list[str] = []

    def fake_download(*, repo_id: str, repo_type: str, filename: str) -> str:
        _ = repo_id
        _ = repo_type
        calls.append(filename)
        return str(remote_file)

    monkeypatch.setattr("src.services.audio_fetch_service.hf_hub_download", fake_download)

    cache = EphemeralCacheManager(cache_dir=str(tmp_path / "cache"), ttl_seconds=60, max_files=10)
    service = AudioFetchService(cache)

    first = service.fetch(dataset_repo="org/project-dataset", audio_id="sample.wav")
    second = service.fetch(dataset_repo="org/project-dataset", audio_id="sample.wav")

    assert first.source == "remote"
    assert second.source == "cache"
    assert len(calls) == 1


def test_fetch_without_extension_tries_supported_extensions(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    remote_file = tmp_path / "remote.mp3"
    remote_file.write_bytes(b"audio-bytes")
    attempts: list[str] = []

    def fake_download(*, repo_id: str, repo_type: str, filename: str) -> str:
        _ = repo_id
        _ = repo_type
        attempts.append(filename)
        if filename.endswith(".mp3"):
            return str(remote_file)
        raise RuntimeError("not found")

    monkeypatch.setattr("src.services.audio_fetch_service.hf_hub_download", fake_download)

    cache = EphemeralCacheManager(cache_dir=str(tmp_path / "cache"), ttl_seconds=60, max_files=10)
    service = AudioFetchService(cache)

    result = service.fetch(dataset_repo="org/project-dataset", audio_id="recording_001")

    assert result.source == "remote"
    assert any(path.endswith(".wav") for path in attempts)
    assert any(path.endswith(".mp3") for path in attempts)


def test_cleanup_after_validation_removes_cached_file(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    remote_file = tmp_path / "remote.wav"
    remote_file.write_bytes(b"audio-bytes")

    def fake_download(*, repo_id: str, repo_type: str, filename: str) -> str:
        _ = repo_id
        _ = repo_type
        _ = filename
        return str(remote_file)

    monkeypatch.setattr("src.services.audio_fetch_service.hf_hub_download", fake_download)

    cache = EphemeralCacheManager(cache_dir=str(tmp_path / "cache"), ttl_seconds=60, max_files=10)
    service = AudioFetchService(cache)

    result = service.fetch(dataset_repo="org/project-dataset", audio_id="sample.wav")
    path_before = Path(result.local_path)
    assert path_before.exists()

    service.cleanup_after_validation(result.cache_key)

    assert not path_before.exists()
    assert cache.get(result.cache_key) is None
