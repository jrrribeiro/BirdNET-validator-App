from dataclasses import dataclass
from pathlib import Path

from huggingface_hub import hf_hub_download

from src.cache.ephemeral_cache_manager import EphemeralCacheManager


SUPPORTED_AUDIO_EXTENSIONS = (".wav", ".mp3", ".flac", ".ogg", ".m4a")


@dataclass(slots=True)
class AudioFetchResult:
    cache_key: str
    local_path: str
    source: str


class AudioFetchService:
    def __init__(self, cache_manager: EphemeralCacheManager) -> None:
        self._cache = cache_manager

    def fetch(self, dataset_repo: str, audio_id: str) -> AudioFetchResult:
        cache_key = f"{dataset_repo}:{audio_id}"
        cached_path = self._cache.get(cache_key)
        if cached_path:
            return AudioFetchResult(cache_key=cache_key, local_path=str(cached_path), source="cache")

        target_filename, downloaded_path = self._resolve_remote_filename(dataset_repo=dataset_repo, audio_id=audio_id)
        if downloaded_path is None:
            downloaded = hf_hub_download(repo_id=dataset_repo, repo_type="dataset", filename=target_filename)
            downloaded_path = Path(downloaded)

        suffix = downloaded_path.suffix if downloaded_path.suffix else ".bin"
        local_path = self._cache.put_bytes(cache_key, downloaded_path.read_bytes(), suffix=suffix)
        return AudioFetchResult(cache_key=cache_key, local_path=str(local_path), source="remote")

    def cleanup_after_validation(self, cache_key: str) -> None:
        self._cache.cleanup_key(cache_key)

    def _resolve_remote_filename(self, dataset_repo: str, audio_id: str) -> tuple[str, Path | None]:
        audio_path = Path(audio_id)
        if audio_path.suffix:
            return f"audio/{audio_id}", None

        for extension in SUPPORTED_AUDIO_EXTENSIONS:
            candidate = f"audio/{audio_id}{extension}"
            try:
                downloaded = hf_hub_download(repo_id=dataset_repo, repo_type="dataset", filename=candidate)
                return candidate, Path(downloaded)
            except Exception:
                continue

        raise FileNotFoundError(f"Unable to locate audio file for audio_id: {audio_id}")
