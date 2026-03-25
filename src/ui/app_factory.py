import gradio as gr
import tempfile
from pathlib import Path
from typing import Protocol

from src.cache.ephemeral_cache_manager import EphemeralCacheManager
from src.domain.models import Detection
from src.repositories.append_only_validation_repository import AppendOnlyValidationRepository, OptimisticLockError
from src.repositories.in_memory_detection_repository import InMemoryDetectionRepository
from src.services.audio_fetch_service import AudioFetchService
from src.services.detection_queue_service import DetectionQueueService
from src.services.validation_service import ValidationService


class _AudioFetchResultProtocol(Protocol):
    cache_key: str
    local_path: str
    source: str


class _AudioServiceProtocol(Protocol):
    def fetch(self, dataset_repo: str, audio_id: str) -> _AudioFetchResultProtocol: ...

    def cleanup_after_validation(self, cache_key: str) -> None: ...


class _ValidationServiceProtocol(Protocol):
    def validate_detection(
        self,
        project_slug: str,
        detection_key: str,
        status: str,
        validator: str,
        notes: str = "",
        corrected_species: str | None = None,
        expected_version: int | None = None,
    ) -> object: ...


class _ValidationReadRepositoryProtocol(Protocol):
    def load_current_snapshot(self, project_slug: str) -> dict[str, dict[str, object]]: ...

    def list_events(self, project_slug: str) -> list[dict[str, object]]: ...


class _QueueServiceProtocol(Protocol):
    def get_page(
        self,
        project_slug: str,
        page: int,
        page_size: int,
        scientific_name: str | None = None,
        min_confidence: float | None = None,
        max_confidence: float | None = None,
    ) -> object: ...


def _seed_service() -> DetectionQueueService:
    repo = InMemoryDetectionRepository()
    demo_items = [
        Detection(
            detection_key="0000000000001001",
            audio_id="audio_1001",
            scientific_name="Cyanocorax cyanopogon",
            confidence=0.93,
            start_time=1.2,
            end_time=2.5,
        ),
        Detection(
            detection_key="0000000000001002",
            audio_id="audio_1002",
            scientific_name="Ramphastos toco",
            confidence=0.88,
            start_time=0.8,
            end_time=2.1,
        ),
        Detection(
            detection_key="0000000000001003",
            audio_id="audio_1003",
            scientific_name="Cyanocorax cyanopogon",
            confidence=0.72,
            start_time=3.1,
            end_time=4.0,
        ),
        Detection(
            detection_key="0000000000001004",
            audio_id="audio_1004",
            scientific_name="Psarocolius decumanus",
            confidence=0.67,
            start_time=5.0,
            end_time=6.3,
        ),
    ]
    repo.seed("demo-project", demo_items)
    return DetectionQueueService(repo)


def _page_to_table(
    service: _QueueServiceProtocol,
    snapshot_reader: _ValidationReadRepositoryProtocol,
    project_slug: str,
    page: int,
    scientific_name: str,
    min_confidence: float,
    conflict_detection_key: str = "",
    show_conflicts_only: bool = False,
):
    filter_name = scientific_name.strip() if scientific_name.strip() else None
    page_obj = service.get_page(
        project_slug="demo-project",
        page=page,
        page_size=2,
        scientific_name=filter_name,
        min_confidence=min_confidence,
    )

    snapshot = snapshot_reader.load_current_snapshot(project_slug=project_slug)

    rows = [
        [
            item.detection_key,
            item.audio_id,
            item.scientific_name,
            round(item.confidence, 3),
            item.start_time,
            item.end_time,
            str(snapshot.get(item.detection_key, {}).get("status", "pending")),
            int(snapshot.get(item.detection_key, {}).get("version", 0)),
            "CONFLICT" if conflict_detection_key and item.detection_key == conflict_detection_key else "",
            "HIGH" if conflict_detection_key and item.detection_key == conflict_detection_key else "",
        ]
        for item in page_obj.items
    ]

    if show_conflicts_only:
        rows = [row for row in rows if str(row[8]) == "CONFLICT"]

    status = f"Pagina {page_obj.page}/{page_obj.total_pages} | Total filtrado: {page_obj.total_items}"
    if show_conflicts_only:
        status = f"{status} | Apenas conflitos: {len(rows)} item(ns)"
    return rows, status, page_obj.page


def _build_validation_report(snapshot_reader: _ValidationReadRepositoryProtocol, project_slug: str) -> str:
    snapshot = snapshot_reader.load_current_snapshot(project_slug=project_slug)
    events = snapshot_reader.list_events(project_slug=project_slug)

    counts: dict[str, int] = {}
    for payload in snapshot.values():
        status_value = str(payload.get("status", "unknown"))
        counts[status_value] = counts.get(status_value, 0) + 1

    parts = [
        f"Projeto: {project_slug}",
        f"Eventos append-only: {len(events)}",
        f"Deteccoes com estado atual: {len(snapshot)}",
    ]
    if counts:
        summary = ", ".join(f"{key}={value}" for key, value in sorted(counts.items()))
        parts.append(f"Status atual: {summary}")
    else:
        parts.append("Status atual: sem validacoes")
    return " | ".join(parts)


def _extract_audio_id(rows: object, selected_index: int) -> str:
    normalized_rows: list[list[object]]

    if hasattr(rows, "values"):
        normalized_rows = [list(item) for item in rows.values.tolist()]
    else:
        normalized_rows = [list(item) for item in rows] if rows else []

    if not normalized_rows:
        raise ValueError("Nenhuma deteccao carregada na tabela")
    if selected_index < 0 or selected_index >= len(normalized_rows):
        raise ValueError("Selecione uma deteccao valida na tabela")

    value = normalized_rows[selected_index][1]
    audio_id = str(value).strip()
    if not audio_id:
        raise ValueError("audio_id invalido na deteccao selecionada")
    return audio_id


def _extract_detection_key(rows: object, selected_index: int) -> str:
    normalized_rows: list[list[object]]

    if hasattr(rows, "values"):
        normalized_rows = [list(item) for item in rows.values.tolist()]
    else:
        normalized_rows = [list(item) for item in rows] if rows else []

    if not normalized_rows:
        raise ValueError("Nenhuma deteccao carregada na tabela")
    if selected_index < 0 or selected_index >= len(normalized_rows):
        raise ValueError("Selecione uma deteccao valida na tabela")

    value = normalized_rows[selected_index][0]
    detection_key = str(value).strip()
    if not detection_key:
        raise ValueError("detection_key invalido na deteccao selecionada")
    return detection_key


def _find_detection_row_index(rows: object, detection_key: str) -> int:
    normalized_rows: list[list[object]]

    if hasattr(rows, "values"):
        normalized_rows = [list(item) for item in rows.values.tolist()]
    else:
        normalized_rows = [list(item) for item in rows] if rows else []

    for index, row in enumerate(normalized_rows):
        if str(row[0]).strip() == detection_key:
            return index
    return 0


def _extract_expected_version(rows: object, selected_index: int) -> int:
    normalized_rows: list[list[object]]

    if hasattr(rows, "values"):
        normalized_rows = [list(item) for item in rows.values.tolist()]
    else:
        normalized_rows = [list(item) for item in rows] if rows else []

    if not normalized_rows:
        raise ValueError("Nenhuma deteccao carregada na tabela")
    if selected_index < 0 or selected_index >= len(normalized_rows):
        raise ValueError("Selecione uma deteccao valida na tabela")

    value = normalized_rows[selected_index][7]
    return int(value)


def _fetch_selected_audio(
    audio_service: _AudioServiceProtocol,
    dataset_repo: str,
    rows: object,
    selected_index: int,
    previous_cache_key: str,
) -> tuple[str | None, str, str]:
    repo = dataset_repo.strip()
    if not repo:
        return None, "", "Informe dataset repo no formato owner/repo"

    try:
        audio_id = _extract_audio_id(rows=rows, selected_index=selected_index)
        result = audio_service.fetch(dataset_repo=repo, audio_id=audio_id)
        status = f"Audio carregado ({result.source}) para audio_id={audio_id}"
        return result.local_path, result.cache_key, status
    except Exception as exc:
        if previous_cache_key:
            return None, previous_cache_key, f"Falha ao carregar audio: {exc}"
        return None, "", f"Falha ao carregar audio: {exc}"


def _cleanup_selected_audio(audio_service: _AudioServiceProtocol, cache_key: str) -> tuple[str, str | None]:
    if not cache_key:
        return "Nenhum audio em cache para limpar", None

    audio_service.cleanup_after_validation(cache_key=cache_key)
    return "Cache de audio limpo apos validacao", None


def _save_selected_validation(
    validation_service: _ValidationServiceProtocol,
    audio_service: _AudioServiceProtocol,
    project_slug: str,
    rows: object,
    selected_index: int,
    status_value: str,
    validator: str,
    notes: str,
    cache_key: str,
) -> tuple[str, str, str | None]:
    validator_name = validator.strip()
    if not validator_name:
        return "Informe o nome do validador", cache_key, None

    try:
        detection_key = _extract_detection_key(rows=rows, selected_index=selected_index)
        expected_version = _extract_expected_version(rows=rows, selected_index=selected_index)
        _ = validation_service.validate_detection(
            project_slug=project_slug,
            detection_key=detection_key,
            status=status_value,
            validator=validator_name,
            notes=notes.strip(),
            expected_version=expected_version,
        )
        if cache_key:
            audio_service.cleanup_after_validation(cache_key=cache_key)
        return f"Validacao salva: {detection_key} -> {status_value}", "", None
    except OptimisticLockError as exc:
        return (
            "Conflito de concorrencia: esta deteccao foi atualizada por outro validador "
            f"(detection_key={exc.detection_key}, versao atual={exc.current_version}, esperada={exc.expected_version}). "
            "Recarregue a tabela.",
            cache_key,
            None,
        )
    except Exception as exc:
        return f"Falha ao salvar validacao: {exc}", cache_key, None


def _save_selected_validation_with_refresh(
    validation_service: _ValidationServiceProtocol,
    audio_service: _AudioServiceProtocol,
    queue_service: _QueueServiceProtocol,
    snapshot_reader: _ValidationReadRepositoryProtocol,
    project_slug: str,
    rows: object,
    selected_index: int,
    status_value: str,
    validator: str,
    notes: str,
    cache_key: str,
    page: int,
    scientific_name: str,
    min_confidence: float,
    show_conflicts_only: bool,
) -> tuple[str, str, str | None, list[list[object]], int, int, str, str]:
    selected_key = ""
    try:
        selected_key = _extract_detection_key(rows=rows, selected_index=selected_index)
    except Exception:
        selected_key = ""

    save_status, updated_cache_key, audio_path = _save_selected_validation(
        validation_service=validation_service,
        audio_service=audio_service,
        project_slug=project_slug,
        rows=rows,
        selected_index=selected_index,
        status_value=status_value,
        validator=validator,
        notes=notes,
        cache_key=cache_key,
    )

    refreshed_rows, page_status, refreshed_page = _page_to_table(
        service=queue_service,
        snapshot_reader=snapshot_reader,
        project_slug=project_slug,
        page=page,
        scientific_name=scientific_name,
        min_confidence=min_confidence,
        show_conflicts_only=show_conflicts_only,
    )

    if selected_key:
        refreshed_index = _find_detection_row_index(refreshed_rows, selected_key)
    else:
        refreshed_index = 0

    if "Conflito de concorrencia" in save_status:
        conflict_key = selected_key
        refreshed_rows, page_status, refreshed_page = _page_to_table(
            service=queue_service,
            snapshot_reader=snapshot_reader,
            project_slug=project_slug,
            page=refreshed_page,
            scientific_name=scientific_name,
            min_confidence=min_confidence,
            conflict_detection_key=conflict_key,
            show_conflicts_only=show_conflicts_only,
        )
        refreshed_index = _find_detection_row_index(refreshed_rows, selected_key) if selected_key else 0
        pending_status_value = status_value
        status = f"{save_status} Tabela recarregada para resolver conflito."
    else:
        conflict_key = ""
        pending_status_value = ""
        status = f"{save_status} | {page_status}"

    return (
        status,
        updated_cache_key,
        audio_path,
        refreshed_rows,
        refreshed_page,
        refreshed_index,
        pending_status_value,
        conflict_key,
    )


def _reapply_last_conflict_validation_with_refresh(
    validation_service: _ValidationServiceProtocol,
    audio_service: _AudioServiceProtocol,
    queue_service: _QueueServiceProtocol,
    snapshot_reader: _ValidationReadRepositoryProtocol,
    project_slug: str,
    rows: object,
    selected_index: int,
    pending_status_value: str,
    conflict_detection_key: str,
    validator: str,
    notes: str,
    cache_key: str,
    page: int,
    scientific_name: str,
    min_confidence: float,
    show_conflicts_only: bool,
) -> tuple[str, str, str | None, list[list[object]], int, int, str, str]:
    if not pending_status_value:
        refreshed_rows, page_status, refreshed_page = _page_to_table(
            service=queue_service,
            snapshot_reader=snapshot_reader,
            project_slug=project_slug,
            page=page,
            scientific_name=scientific_name,
            min_confidence=min_confidence,
            show_conflicts_only=show_conflicts_only,
        )
        return (
            f"Nenhuma validacao pendente para reaplicar | {page_status}",
            cache_key,
            None,
            refreshed_rows,
            refreshed_page,
            selected_index,
            "",
            "",
        )

    target_index = _find_detection_row_index(rows, conflict_detection_key) if conflict_detection_key else selected_index
    return _save_selected_validation_with_refresh(
        validation_service=validation_service,
        audio_service=audio_service,
        queue_service=queue_service,
        snapshot_reader=snapshot_reader,
        project_slug=project_slug,
        rows=rows,
        selected_index=target_index,
        status_value=pending_status_value,
        validator=validator,
        notes=notes,
        cache_key=cache_key,
        page=page,
        scientific_name=scientific_name,
        min_confidence=min_confidence,
        show_conflicts_only=show_conflicts_only,
    )


def create_app() -> gr.Blocks:
    project_slug = "demo-project"
    service = _seed_service()
    audio_service = AudioFetchService(EphemeralCacheManager(ttl_seconds=300, max_files=128))
    validation_base_dir = str(Path(tempfile.gettempdir()) / "birdnet-validator-validations")
    validation_repository = AppendOnlyValidationRepository(base_dir=validation_base_dir)
    validation_service = ValidationService(validation_repository)

    with gr.Blocks(title="BirdNET Validator HF") as demo:
        gr.Markdown("# BirdNET Validator HF")
        gr.Markdown("Sprint 2: fila paginada + audio sob demanda com cache efemero.")

        dataset_repo = gr.Textbox(label="Dataset repo", value="SEU_USUARIO/birdnet-projeto-dataset")

        with gr.Row():
            species_filter = gr.Textbox(label="Filtro especie", placeholder="Ex: Cyanocorax cyanopogon")
            min_confidence = gr.Slider(label="Confianca minima", minimum=0.0, maximum=1.0, step=0.01, value=0.0)
            show_conflicts_only = gr.Checkbox(label="Mostrar apenas conflitos", value=False)

        with gr.Row():
            prev_btn = gr.Button("Pagina anterior")
            next_btn = gr.Button("Proxima pagina")
            refresh_btn = gr.Button("Aplicar filtros")

        page_state = gr.State(value=1)
        table = gr.Dataframe(
            headers=[
                "detection_key",
                "audio_id",
                "scientific_name",
                "confidence",
                "start_time",
                "end_time",
                "validation_status",
                "version",
                "conflict_flag",
                "conflict_severity",
            ],
            label="Deteccoes",
            interactive=False,
        )
        selected_index = gr.Number(label="Linha selecionada", value=0, precision=0)

        with gr.Row():
            load_audio_btn = gr.Button("Carregar audio selecionado")
            clear_audio_btn = gr.Button("Limpar cache apos validacao")

        with gr.Row():
            validator_name = gr.Textbox(label="Validador", value="validator-demo")
            validation_notes = gr.Textbox(label="Notas", placeholder="Opcional")

        with gr.Row():
            approve_btn = gr.Button("Validar positivo")
            reject_btn = gr.Button("Validar negativo")
            uncertain_btn = gr.Button("Indeterminado")
            skip_btn = gr.Button("Pular")
            reapply_btn = gr.Button("Reaplicar validacao apos conflito")

        report_btn = gr.Button("Gerar relatorio de validacoes")

        audio_player = gr.Audio(label="Audio sob demanda", type="filepath")
        cache_key_state = gr.State(value="")
        pending_status_state = gr.State(value="")
        conflict_detection_key_state = gr.State(value="")
        status = gr.Textbox(label="Status", interactive=False)
        report_box = gr.Textbox(label="Relatorio", interactive=False)

        def refresh(page: int, species: str, confidence: float, only_conflicts: bool):
            return _page_to_table(
                service=service,
                snapshot_reader=validation_repository,
                project_slug=project_slug,
                page=page,
                scientific_name=species,
                min_confidence=confidence,
                show_conflicts_only=only_conflicts,
            )

        def go_next(page: int, species: str, confidence: float, only_conflicts: bool):
            return refresh(page + 1, species, confidence, only_conflicts)

        def go_prev(page: int, species: str, confidence: float, only_conflicts: bool):
            return refresh(max(1, page - 1), species, confidence, only_conflicts)

        def on_select(evt):
            if isinstance(evt.index, tuple):
                return int(evt.index[0])
            if isinstance(evt.index, int):
                return int(evt.index)
            return 0

        demo.load(
            fn=refresh,
            inputs=[page_state, species_filter, min_confidence, show_conflicts_only],
            outputs=[table, status, page_state],
        )
        refresh_btn.click(
            fn=lambda species, confidence, only_conflicts: refresh(1, species, confidence, only_conflicts),
            inputs=[species_filter, min_confidence, show_conflicts_only],
            outputs=[table, status, page_state],
        )
        next_btn.click(
            fn=go_next,
            inputs=[page_state, species_filter, min_confidence, show_conflicts_only],
            outputs=[table, status, page_state],
        )
        prev_btn.click(
            fn=go_prev,
            inputs=[page_state, species_filter, min_confidence, show_conflicts_only],
            outputs=[table, status, page_state],
        )
        table.select(fn=on_select, inputs=None, outputs=[selected_index])
        load_audio_btn.click(
            fn=lambda repo, rows, idx, cache_key: _fetch_selected_audio(
                audio_service=audio_service,
                dataset_repo=repo,
                rows=rows,
                selected_index=int(idx),
                previous_cache_key=cache_key,
            ),
            inputs=[dataset_repo, table, selected_index, cache_key_state],
            outputs=[audio_player, cache_key_state, status],
        )
        clear_audio_btn.click(
            fn=lambda cache_key: _cleanup_selected_audio(audio_service=audio_service, cache_key=cache_key),
            inputs=[cache_key_state],
            outputs=[status, audio_player],
        )
        approve_btn.click(
            fn=lambda rows, idx, name, notes, cache_key, page, species, confidence, only_conflicts: _save_selected_validation_with_refresh(
                validation_service=validation_service,
                audio_service=audio_service,
                queue_service=service,
                snapshot_reader=validation_repository,
                project_slug=project_slug,
                rows=rows,
                selected_index=int(idx),
                status_value="positive",
                validator=name,
                notes=notes,
                cache_key=cache_key,
                page=int(page),
                scientific_name=species,
                min_confidence=float(confidence),
                show_conflicts_only=bool(only_conflicts),
            ),
            inputs=[table, selected_index, validator_name, validation_notes, cache_key_state, page_state, species_filter, min_confidence, show_conflicts_only],
            outputs=[status, cache_key_state, audio_player, table, page_state, selected_index, pending_status_state, conflict_detection_key_state],
        )
        reject_btn.click(
            fn=lambda rows, idx, name, notes, cache_key, page, species, confidence, only_conflicts: _save_selected_validation_with_refresh(
                validation_service=validation_service,
                audio_service=audio_service,
                queue_service=service,
                snapshot_reader=validation_repository,
                project_slug=project_slug,
                rows=rows,
                selected_index=int(idx),
                status_value="negative",
                validator=name,
                notes=notes,
                cache_key=cache_key,
                page=int(page),
                scientific_name=species,
                min_confidence=float(confidence),
                show_conflicts_only=bool(only_conflicts),
            ),
            inputs=[table, selected_index, validator_name, validation_notes, cache_key_state, page_state, species_filter, min_confidence, show_conflicts_only],
            outputs=[status, cache_key_state, audio_player, table, page_state, selected_index, pending_status_state, conflict_detection_key_state],
        )
        uncertain_btn.click(
            fn=lambda rows, idx, name, notes, cache_key, page, species, confidence, only_conflicts: _save_selected_validation_with_refresh(
                validation_service=validation_service,
                audio_service=audio_service,
                queue_service=service,
                snapshot_reader=validation_repository,
                project_slug=project_slug,
                rows=rows,
                selected_index=int(idx),
                status_value="uncertain",
                validator=name,
                notes=notes,
                cache_key=cache_key,
                page=int(page),
                scientific_name=species,
                min_confidence=float(confidence),
                show_conflicts_only=bool(only_conflicts),
            ),
            inputs=[table, selected_index, validator_name, validation_notes, cache_key_state, page_state, species_filter, min_confidence, show_conflicts_only],
            outputs=[status, cache_key_state, audio_player, table, page_state, selected_index, pending_status_state, conflict_detection_key_state],
        )
        skip_btn.click(
            fn=lambda rows, idx, name, notes, cache_key, page, species, confidence, only_conflicts: _save_selected_validation_with_refresh(
                validation_service=validation_service,
                audio_service=audio_service,
                queue_service=service,
                snapshot_reader=validation_repository,
                project_slug=project_slug,
                rows=rows,
                selected_index=int(idx),
                status_value="skip",
                validator=name,
                notes=notes,
                cache_key=cache_key,
                page=int(page),
                scientific_name=species,
                min_confidence=float(confidence),
                show_conflicts_only=bool(only_conflicts),
            ),
            inputs=[table, selected_index, validator_name, validation_notes, cache_key_state, page_state, species_filter, min_confidence, show_conflicts_only],
            outputs=[status, cache_key_state, audio_player, table, page_state, selected_index, pending_status_state, conflict_detection_key_state],
        )
        reapply_btn.click(
            fn=lambda rows, idx, pending_status, conflict_key, name, notes, cache_key, page, species, confidence, only_conflicts: _reapply_last_conflict_validation_with_refresh(
                validation_service=validation_service,
                audio_service=audio_service,
                queue_service=service,
                snapshot_reader=validation_repository,
                project_slug=project_slug,
                rows=rows,
                selected_index=int(idx),
                pending_status_value=pending_status,
                conflict_detection_key=conflict_key,
                validator=name,
                notes=notes,
                cache_key=cache_key,
                page=int(page),
                scientific_name=species,
                min_confidence=float(confidence),
                show_conflicts_only=bool(only_conflicts),
            ),
            inputs=[
                table,
                selected_index,
                pending_status_state,
                conflict_detection_key_state,
                validator_name,
                validation_notes,
                cache_key_state,
                page_state,
                species_filter,
                min_confidence,
                show_conflicts_only,
            ],
            outputs=[status, cache_key_state, audio_player, table, page_state, selected_index, pending_status_state, conflict_detection_key_state],
        )
        report_btn.click(
            fn=lambda: _build_validation_report(validation_repository, project_slug),
            inputs=None,
            outputs=[report_box],
        )

    return demo
