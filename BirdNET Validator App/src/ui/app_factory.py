import gradio as gr
import tempfile
from datetime import date, datetime
from pathlib import Path
from typing import Protocol

from src.cache.ephemeral_cache_manager import EphemeralCacheManager
from src.domain.models import Detection, Project, Role
from src.repositories.append_only_validation_repository import AppendOnlyValidationRepository, OptimisticLockError
from src.repositories.in_memory_detection_repository import InMemoryDetectionRepository
from src.services.audio_fetch_service import AudioFetchService
from src.services.detection_queue_service import DetectionQueueService
from src.services.validation_service import ValidationService
from src.auth.auth_service import AuthService
from src.ui.login_page import create_login_page
from src.ui.project_selector import create_project_selector
from src.ui.admin_panel import AdminPanelManager, create_admin_panel


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
    validator_filter: str = "",
    status_filter: str = "all",
    updated_after: object = None,
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

    normalized_status_filter = status_filter.strip().lower() if status_filter else "all"
    normalized_validator_filter = validator_filter.strip().lower()
    updated_after_date: date | None = None
    if updated_after is not None:
        if isinstance(updated_after, datetime):
            updated_after_date = updated_after.date()
        elif isinstance(updated_after, date):
            updated_after_date = updated_after
        elif isinstance(updated_after, (int, float)):
            updated_after_date = datetime.fromtimestamp(float(updated_after)).date()
        else:
            updated_after_text = str(updated_after).strip()
            if updated_after_text:
                try:
                    updated_after_date = datetime.strptime(updated_after_text, "%Y-%m-%d").date()
                except ValueError:
                    try:
                        updated_after_date = datetime.fromisoformat(updated_after_text.replace("Z", "+00:00")).date()
                    except ValueError:
                        updated_after_date = None

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

    if normalized_validator_filter:
        rows = [
            row
            for row in rows
            if normalized_validator_filter in str(snapshot.get(str(row[0]), {}).get("validator", "")).strip().lower()
        ]

    if normalized_status_filter and normalized_status_filter != "all":
        rows = [row for row in rows if str(row[6]).strip().lower() == normalized_status_filter]

    if updated_after_date:
        filtered_rows: list[list[object]] = []
        for row in rows:
            snapshot_item = snapshot.get(str(row[0]), {})
            updated_at_value = str(snapshot_item.get("updated_at", "")).strip()
            if not updated_at_value:
                continue
            try:
                item_date = datetime.fromisoformat(updated_at_value.replace("Z", "+00:00")).date()
                if item_date >= updated_after_date:
                    filtered_rows.append(row)
            except ValueError:
                continue
        rows = filtered_rows

    if show_conflicts_only:
        rows = [row for row in rows if str(row[8]) == "CONFLICT"]

    status = f"Pagina {page_obj.page}/{page_obj.total_pages} | Total base: {page_obj.total_items} | Exibidos: {len(rows)}"
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
    validator_filter: str,
    status_filter: str,
    updated_after: object,
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
        validator_filter=validator_filter,
        status_filter=status_filter,
        updated_after=updated_after,
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
            validator_filter=validator_filter,
            status_filter=status_filter,
            updated_after=updated_after,
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
    validator_filter: str,
    status_filter: str,
    updated_after: object,
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
            validator_filter=validator_filter,
            status_filter=status_filter,
            updated_after=updated_after,
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
        validator_filter=validator_filter,
        status_filter=status_filter,
        updated_after=updated_after,
        show_conflicts_only=show_conflicts_only,
    )


def _batch_validate_conflicts(
    validation_service: _ValidationServiceProtocol,
    audio_service: _AudioServiceProtocol,
    queue_service: _QueueServiceProtocol,
    snapshot_reader: _ValidationReadRepositoryProtocol,
    project_slug: str,
    rows: object,
    status_value: str,
    validator: str,
    notes: str,
    cache_key: str,
    page: int,
    scientific_name: str,
    min_confidence: float,
    validator_filter: str,
    status_filter: str,
    updated_after: object,
) -> tuple[str, str, str | None, list[list[object]], int]:
    """Apply the same validation status to all visible conflicts in the table."""
    validator_name = validator.strip()
    if not validator_name:
        return "Informe o nome do validador", "", None, [], page

    normalized_rows: list[list[object]]
    if hasattr(rows, "values"):
        normalized_rows = [list(item) for item in rows.values.tolist()]
    else:
        normalized_rows = [list(item) for item in rows] if rows else []

    if not normalized_rows:
        return "Nenhuma deteccao com conflito para validar", "", None, [], page

    conflict_rows = [row for row in normalized_rows if str(row[8]) == "CONFLICT"]
    if not conflict_rows:
        return "Nenhuma deteccao com conflito identificada na tabela", "", None, normalized_rows, page

    success_count = 0
    failure_count = 0
    conflict_count = 0

    for row in conflict_rows:
        try:
            detection_key = str(row[0]).strip()
            expected_version = int(row[7])

            _ = validation_service.validate_detection(
                project_slug=project_slug,
                detection_key=detection_key,
                status=status_value,
                validator=validator_name,
                notes=notes.strip(),
                expected_version=expected_version,
            )
            success_count += 1
            if cache_key:
                audio_service.cleanup_after_validation(cache_key=cache_key)
        except OptimisticLockError:
            conflict_count += 1
        except Exception:
            failure_count += 1

    refreshed_rows, page_status, refreshed_page = _page_to_table(
        service=queue_service,
        snapshot_reader=snapshot_reader,
        project_slug=project_slug,
        page=page,
        scientific_name=scientific_name,
        min_confidence=min_confidence,
        validator_filter=validator_filter,
        status_filter=status_filter,
        updated_after=updated_after,
        show_conflicts_only=False,
    )

    summary = f"Processados {len(conflict_rows)} conflitos: {success_count} sucesso, {conflict_count} novos conflitos, {failure_count} falhas"
    status = f"{summary} | {page_status}"

    return status, "", None, refreshed_rows, refreshed_page


def _batch_reapply_all_pending(
    validation_service: _ValidationServiceProtocol,
    audio_service: _AudioServiceProtocol,
    queue_service: _QueueServiceProtocol,
    snapshot_reader: _ValidationReadRepositoryProtocol,
    project_slug: str,
    rows: object,
    pending_statuses: dict[str, str],
    validator: str,
    notes: str,
    cache_key: str,
    page: int,
    scientific_name: str,
    min_confidence: float,
    validator_filter: str,
    status_filter: str,
    updated_after: object,
) -> tuple[str, str, str | None, list[list[object]], int]:
    """Reapply all pending validations (stored conflicts) with current version."""
    if not pending_statuses:
        return "Nenhuma validacao pendente para reaplicar", "", None, [], page

    validator_name = validator.strip()
    if not validator_name:
        return "Informe o nome do validador", "", None, [], page

    success_count = 0
    conflict_count = 0
    failure_count = 0

    snapshot = snapshot_reader.load_current_snapshot(project_slug=project_slug)

    for detection_key, status_value in pending_statuses.items():
        try:
            current_version = int(snapshot.get(detection_key, {}).get("version", 0))

            _ = validation_service.validate_detection(
                project_slug=project_slug,
                detection_key=detection_key,
                status=status_value,
                validator=validator_name,
                notes=notes.strip(),
                expected_version=current_version,
            )
            success_count += 1
            if cache_key:
                audio_service.cleanup_after_validation(cache_key=cache_key)
        except OptimisticLockError:
            conflict_count += 1
        except Exception:
            failure_count += 1

    refreshed_rows, page_status, refreshed_page = _page_to_table(
        service=queue_service,
        snapshot_reader=snapshot_reader,
        project_slug=project_slug,
        page=page,
        scientific_name=scientific_name,
        min_confidence=min_confidence,
        validator_filter=validator_filter,
        status_filter=status_filter,
        updated_after=updated_after,
        show_conflicts_only=False,
    )

    summary = f"Reaplicadas {len(pending_statuses)} validacoes: {success_count} sucesso, {conflict_count} novos conflitos, {failure_count} falhas"
    status = f"{summary} | {page_status}"

    return status, "", None, refreshed_rows, refreshed_page


def build_demo_app(project_slug: str = "demo-project") -> gr.Blocks:
    """Build the demo validation app for a given project.
    
    Args:
        project_slug: Project identifier (default: demo-project)
    
    Returns:
        Gradio Blocks with validation interface
    """
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
            validator_filter = gr.Textbox(label="Filtro validador", placeholder="Ex: validator-demo")
            validation_status_filter = gr.Dropdown(
                label="Filtro status",
                choices=["all", "pending", "positive", "negative", "uncertain", "skip"],
                value="all",
            )
            updated_after_filter = gr.DateTime(label="Atualizado a partir de", include_time=False, type="string")

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

        with gr.Row():
            batch_approve_conflicts_btn = gr.Button("Aprovar todos os conflitos")
            batch_reject_conflicts_btn = gr.Button("Rejeitar todos os conflitos")

        report_btn = gr.Button("Gerar relatorio de validacoes")

        audio_player = gr.Audio(label="Audio sob demanda", type="filepath")
        cache_key_state = gr.State(value="")
        pending_status_state = gr.State(value="")
        conflict_detection_key_state = gr.State(value="")
        status = gr.Textbox(label="Status", interactive=False)
        report_box = gr.Textbox(label="Relatorio", interactive=False)

        # Keyboard shortcuts: 1=positive, 2=negative, 3=uncertain, 4=skip, R=reapply
        keyboard_shortcuts_info = gr.HTML(
            value="<div style='font-size: 12px; color: #666; padding: 8px; background-color: #f5f5f5; border-radius: 4px; margin-bottom: 10px;'>"
            "<strong>Atalhos de teclado:</strong> 1=Positivo | 2=Negativo | 3=Indeterminado | 4=Pular | R=Reaplicar"
            "</div>"
            "<script>"
            "document.addEventListener('keydown', function(event) {"
            "  if (event.target.tagName === 'INPUT' || event.target.tagName === 'TEXTAREA') return;"
            "  const key = event.key.toLowerCase();"
            "  let buttonText = null;"
            "  if (key === '1') buttonText = 'Validar positivo';"
            "  else if (key === '2') buttonText = 'Validar negativo';"
            "  else if (key === '3') buttonText = 'Indeterminado';"
            "  else if (key === '4') buttonText = 'Pular';"
            "  else if (key === 'r') buttonText = 'Reaplicar validacao apos conflito';"
            "  if (buttonText) {"
            "    event.preventDefault();"
            "    const buttons = document.querySelectorAll('button');"
            "    for (const btn of buttons) {"
            "      if (btn.textContent.includes(buttonText)) {"
            "        btn.click();"
            "        break;"
            "      }"
            "    }"
            "  }"
            "});"
            "</script>"
        )

        def refresh(
            page: int,
            species: str,
            confidence: float,
            validator_filter_value: str,
            status_filter_value: str,
            updated_after_value: object,
            only_conflicts: bool,
        ):
            return _page_to_table(
                service=service,
                snapshot_reader=validation_repository,
                project_slug=project_slug,
                page=page,
                scientific_name=species,
                min_confidence=confidence,
                validator_filter=validator_filter_value,
                status_filter=status_filter_value,
                updated_after=updated_after_value,
                show_conflicts_only=only_conflicts,
            )

        def go_next(
            page: int,
            species: str,
            confidence: float,
            validator_filter_value: str,
            status_filter_value: str,
            updated_after_value: object,
            only_conflicts: bool,
        ):
            return refresh(
                page + 1,
                species,
                confidence,
                validator_filter_value,
                status_filter_value,
                updated_after_value,
                only_conflicts,
            )

        def go_prev(
            page: int,
            species: str,
            confidence: float,
            validator_filter_value: str,
            status_filter_value: str,
            updated_after_value: object,
            only_conflicts: bool,
        ):
            return refresh(
                max(1, page - 1),
                species,
                confidence,
                validator_filter_value,
                status_filter_value,
                updated_after_value,
                only_conflicts,
            )

        def on_select(evt: gr.SelectData):
            if isinstance(evt.index, tuple):
                return int(evt.index[0])
            if isinstance(evt.index, int):
                return int(evt.index)
            return 0

        demo.load(
            fn=refresh,
            inputs=[
                page_state,
                species_filter,
                min_confidence,
                validator_filter,
                validation_status_filter,
                updated_after_filter,
                show_conflicts_only,
            ],
            outputs=[table, status, page_state],
        )
        refresh_btn.click(
            fn=lambda species, confidence, validator_filter_value, status_filter_value, updated_after_value, only_conflicts: refresh(
                1,
                species,
                confidence,
                validator_filter_value,
                status_filter_value,
                updated_after_value,
                only_conflicts,
            ),
            inputs=[
                species_filter,
                min_confidence,
                validator_filter,
                validation_status_filter,
                updated_after_filter,
                show_conflicts_only,
            ],
            outputs=[table, status, page_state],
        )
        next_btn.click(
            fn=go_next,
            inputs=[
                page_state,
                species_filter,
                min_confidence,
                validator_filter,
                validation_status_filter,
                updated_after_filter,
                show_conflicts_only,
            ],
            outputs=[table, status, page_state],
        )
        prev_btn.click(
            fn=go_prev,
            inputs=[
                page_state,
                species_filter,
                min_confidence,
                validator_filter,
                validation_status_filter,
                updated_after_filter,
                show_conflicts_only,
            ],
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
            fn=lambda rows, idx, name, notes, cache_key, page, species, confidence, validator_filter_value, status_filter_value, updated_after_value, only_conflicts: _save_selected_validation_with_refresh(
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
                validator_filter=validator_filter_value,
                status_filter=status_filter_value,
                updated_after=updated_after_value,
                show_conflicts_only=bool(only_conflicts),
            ),
            inputs=[
                table,
                selected_index,
                validator_name,
                validation_notes,
                cache_key_state,
                page_state,
                species_filter,
                min_confidence,
                validator_filter,
                validation_status_filter,
                updated_after_filter,
                show_conflicts_only,
            ],
            outputs=[status, cache_key_state, audio_player, table, page_state, selected_index, pending_status_state, conflict_detection_key_state],
        )
        reject_btn.click(
            fn=lambda rows, idx, name, notes, cache_key, page, species, confidence, validator_filter_value, status_filter_value, updated_after_value, only_conflicts: _save_selected_validation_with_refresh(
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
                validator_filter=validator_filter_value,
                status_filter=status_filter_value,
                updated_after=updated_after_value,
                show_conflicts_only=bool(only_conflicts),
            ),
            inputs=[
                table,
                selected_index,
                validator_name,
                validation_notes,
                cache_key_state,
                page_state,
                species_filter,
                min_confidence,
                validator_filter,
                validation_status_filter,
                updated_after_filter,
                show_conflicts_only,
            ],
            outputs=[status, cache_key_state, audio_player, table, page_state, selected_index, pending_status_state, conflict_detection_key_state],
        )
        uncertain_btn.click(
            fn=lambda rows, idx, name, notes, cache_key, page, species, confidence, validator_filter_value, status_filter_value, updated_after_value, only_conflicts: _save_selected_validation_with_refresh(
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
                validator_filter=validator_filter_value,
                status_filter=status_filter_value,
                updated_after=updated_after_value,
                show_conflicts_only=bool(only_conflicts),
            ),
            inputs=[
                table,
                selected_index,
                validator_name,
                validation_notes,
                cache_key_state,
                page_state,
                species_filter,
                min_confidence,
                validator_filter,
                validation_status_filter,
                updated_after_filter,
                show_conflicts_only,
            ],
            outputs=[status, cache_key_state, audio_player, table, page_state, selected_index, pending_status_state, conflict_detection_key_state],
        )
        skip_btn.click(
            fn=lambda rows, idx, name, notes, cache_key, page, species, confidence, validator_filter_value, status_filter_value, updated_after_value, only_conflicts: _save_selected_validation_with_refresh(
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
                validator_filter=validator_filter_value,
                status_filter=status_filter_value,
                updated_after=updated_after_value,
                show_conflicts_only=bool(only_conflicts),
            ),
            inputs=[
                table,
                selected_index,
                validator_name,
                validation_notes,
                cache_key_state,
                page_state,
                species_filter,
                min_confidence,
                validator_filter,
                validation_status_filter,
                updated_after_filter,
                show_conflicts_only,
            ],
            outputs=[status, cache_key_state, audio_player, table, page_state, selected_index, pending_status_state, conflict_detection_key_state],
        )
        reapply_btn.click(
            fn=lambda rows, idx, pending_status, conflict_key, name, notes, cache_key, page, species, confidence, validator_filter_value, status_filter_value, updated_after_value, only_conflicts: _reapply_last_conflict_validation_with_refresh(
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
                validator_filter=validator_filter_value,
                status_filter=status_filter_value,
                updated_after=updated_after_value,
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
                validator_filter,
                validation_status_filter,
                updated_after_filter,
                show_conflicts_only,
            ],
            outputs=[status, cache_key_state, audio_player, table, page_state, selected_index, pending_status_state, conflict_detection_key_state],
        )
        batch_approve_conflicts_btn.click(
            fn=lambda rows, name, notes, cache_key, page, species, confidence, validator_filter_value, status_filter_value, updated_after_value: _batch_validate_conflicts(
                validation_service=validation_service,
                audio_service=audio_service,
                queue_service=service,
                snapshot_reader=validation_repository,
                project_slug=project_slug,
                rows=rows,
                status_value="positive",
                validator=name,
                notes=notes,
                cache_key=cache_key,
                page=int(page),
                scientific_name=species,
                min_confidence=float(confidence),
                validator_filter=validator_filter_value,
                status_filter=status_filter_value,
                updated_after=updated_after_value,
            ),
            inputs=[
                table,
                validator_name,
                validation_notes,
                cache_key_state,
                page_state,
                species_filter,
                min_confidence,
                validator_filter,
                validation_status_filter,
                updated_after_filter,
            ],
            outputs=[status, cache_key_state, audio_player, table, page_state],
        )
        batch_reject_conflicts_btn.click(
            fn=lambda rows, name, notes, cache_key, page, species, confidence, validator_filter_value, status_filter_value, updated_after_value: _batch_validate_conflicts(
                validation_service=validation_service,
                audio_service=audio_service,
                queue_service=service,
                snapshot_reader=validation_repository,
                project_slug=project_slug,
                rows=rows,
                status_value="negative",
                validator=name,
                notes=notes,
                cache_key=cache_key,
                page=int(page),
                scientific_name=species,
                min_confidence=float(confidence),
                validator_filter=validator_filter_value,
                status_filter=status_filter_value,
                updated_after=updated_after_value,
            ),
            inputs=[
                table,
                validator_name,
                validation_notes,
                cache_key_state,
                page_state,
                species_filter,
                min_confidence,
                validator_filter,
                validation_status_filter,
                updated_after_filter,
            ],
            outputs=[status, cache_key_state, audio_player, table, page_state],
        )
        report_btn.click(
            fn=lambda: _build_validation_report(validation_repository, project_slug),
            inputs=None,
            outputs=[report_box],
        )

    return demo


def create_app() -> gr.Blocks:
    """Build the BirdNET Validator app with multi-project auth integration.
    
    Returns multi-tab interface with:
    - Login tab for user authentication
    - Project selection for authorized projects
    - Admin panel for project/user management (admin only)
    - Validation interface for selected project
    
    Returns:
        Gradio Blocks with full auth-integrated app
    """
    # Initialize auth service
    auth_service = AuthService(session_ttl_minutes=120)

    # Setup demo users (in production: database/LDAP/OAuth)
    auth_service.register_user_project_access(
        "admin_user",
        {"kenya-2024": Role.admin, "nairobi-2023": Role.admin},
    )
    auth_service.register_user_project_access(
        "validator_demo",
        {"demo-project": Role.validator, "kenya-2024": Role.validator},
    )
    auth_service.register_user_project_access(
        "validator_other",
        {"nairobi-2023": Role.validator},
    )

    # Initialize admin panel manager
    admin_manager = AdminPanelManager(auth_service)

    # Register projects
    admin_manager.register_project(
        Project(
            project_slug="kenya-2024",
            name="Kenya Survey 2024",
            dataset_repo_id="birdnet/kenya-2024-dataset",
            active=True,
        )
    )
    admin_manager.register_project(
        Project(
            project_slug="nairobi-2023",
            name="Nairobi Survey 2023",
            dataset_repo_id="birdnet/nairobi-2023-dataset",
            active=True,
        )
    )
    admin_manager.register_project(
        Project(
            project_slug="demo-project",
            name="Demo Project",
            dataset_repo_id="birdnet/demo-dataset",
            active=True,
        )
    )

    with gr.Blocks(title="BirdNET Validator HF - Multi-Project") as wrapper:
        gr.Markdown("# BirdNET Validator HF - Sprint 4: Segurança Multi-Projeto")
        gr.Markdown("**Versão com autenticação, autorização por projeto, e painel admin**")

        # Session state
        session_state = gr.State(value=None)
        selected_project_state = gr.State(value=None)

        def _project_rows() -> list[list[object]]:
            projects = admin_manager.list_projects()
            return [
                [
                    p["project_slug"],
                    p["name"],
                    p["dataset_repo_id"],
                    "yes" if bool(p["active"]) else "no",
                ]
                for p in projects
            ]

        def _project_slugs() -> list[str]:
            return [p["project_slug"] for p in admin_manager.list_projects()]

        with gr.Tabs():
            # ===== TAB 1: Login =====
            with gr.Tab("🔐 Login", id="login_tab"):
                login_block, username_input, session_output, login_button, error_message = (
                    create_login_page(auth_service)
                )

                # Store session ID when login succeeds
                def handle_login_success(session_id: str):
                    """Process successful login and store session."""
                    if session_id:
                        return auth_service.get_session(session_id)
                    return None

                session_output.change(
                    fn=handle_login_success,
                    inputs=[session_output],
                    outputs=[session_state],
                )

            # ===== TAB 2: Admin Panel =====
            with gr.Tab("⚙️ Admin", id="admin_tab"):
                admin_info = gr.Markdown(value="⚠️ Faça login primeiro")

                def create_admin_display(session):
                    """Show admin panel or access denied message."""
                    if session is None:
                        return (
                            "❌ **Not Logged In** — Please login first in the Login tab.",
                            gr.update(visible=False),
                        )
                    if session.role.value != "admin":
                        return (
                            "❌ **Access Denied** — Only administrators can access this panel.",
                            gr.update(visible=False),
                        )
                    return (
                        f"✅ **Admin Panel** — Welcome {session.username}! Click below to manage projects and users.",
                        gr.update(visible=True),
                    )

                with gr.Group(visible=False) as admin_controls:
                    gr.Markdown("#### Projetos Cadastrados")

                    with gr.Row():
                        create_project_slug = gr.Textbox(
                            label="Novo Project Slug",
                            placeholder="ex: amazonas-2026",
                        )
                        create_project_name = gr.Textbox(
                            label="Nome do Projeto",
                            placeholder="ex: Amazonas Survey 2026",
                        )
                        create_project_repo = gr.Textbox(
                            label="HF Dataset Repo ID",
                            placeholder="ex: birdnet/amazonas-2026-dataset",
                        )

                    create_project_message = gr.Markdown()

                    def create_project(session, slug: str, name: str, repo_id: str):
                        if session is None or session.role.value != "admin":
                            return "❌ Access denied. Apenas admin pode criar projetos.", gr.update(), gr.update(), gr.update(), gr.update(), gr.update()

                        slug = (slug or "").strip()
                        name = (name or "").strip()
                        repo_id = (repo_id or "").strip()
                        if not slug or not name or not repo_id:
                            return "⚠️ Preencha slug, nome e repo id.", gr.update(), gr.update(), gr.update(), gr.update(), gr.update()

                        created = admin_manager.register_project(
                            Project(
                                project_slug=slug,
                                name=name,
                                dataset_repo_id=repo_id,
                                active=True,
                            )
                        )
                        if not created:
                            return (
                                f"⚠️ Projeto '{slug}' já existe.",
                                _project_rows(),
                                gr.update(choices=_project_slugs()),
                                gr.update(),
                                gr.update(),
                                gr.update(),
                            )

                        return (
                            f"✅ Projeto '{slug}' criado com sucesso.",
                            _project_rows(),
                            gr.update(choices=_project_slugs(), value=slug),
                            gr.update(value=""),
                            gr.update(value=""),
                            gr.update(value=""),
                        )

                    create_project_btn = gr.Button("➕ Criar Projeto", variant="primary")
                    projects_table = gr.Dataframe(
                        value=_project_rows(),
                        headers=["project_slug", "name", "dataset_repo_id", "active"],
                        interactive=False,
                    )
                    refresh_projects_btn = gr.Button("🔄 Atualizar Lista")

                    def refresh_projects(session):
                        if session is None or session.role.value != "admin":
                            return []
                        return _project_rows()

                    refresh_projects_btn.click(
                        fn=refresh_projects,
                        inputs=[session_state],
                        outputs=[projects_table],
                    )

                with gr.Group(visible=False) as admin_users_controls:
                    gr.Markdown("#### Assignar Usuário a Projeto")
                    with gr.Row():
                        admin_username = gr.Textbox(
                            label="Usuário", placeholder="validator_001"
                        )
                        admin_project = gr.Dropdown(
                            choices=_project_slugs(),
                            label="Projeto",
                        )
                        admin_role = gr.Dropdown(
                            choices=["admin", "validator"],
                            value="validator",
                            label="Role",
                        )

                    admin_message = gr.Markdown()

                    def assign_user(session, username: str, project: str, role: str):
                        if session is None or session.role.value != "admin":
                            return "❌ Access denied. Apenas admin pode atribuir usuários.", gr.update(), gr.update(), gr.update()
                        success, msg = admin_manager.assign_user_to_project(
                            username, project, role
                        )
                        if success:
                            return msg, gr.update(value=""), gr.update(value=None), gr.update(value="validator")
                        return msg, gr.update(), gr.update(), gr.update()

                    assign_btn = gr.Button("✅ Assignar", variant="primary")
                    assign_btn.click(
                        fn=assign_user,
                        inputs=[session_state, admin_username, admin_project, admin_role],
                        outputs=[admin_message, admin_username, admin_project, admin_role],
                    )

                create_project_btn.click(
                    fn=create_project,
                    inputs=[session_state, create_project_slug, create_project_name, create_project_repo],
                    outputs=[
                        create_project_message,
                        projects_table,
                        admin_project,
                        create_project_slug,
                        create_project_name,
                        create_project_repo,
                    ],
                )

                session_state.change(
                    fn=create_admin_display,
                    inputs=[session_state],
                    outputs=[admin_info, admin_controls],
                )

                session_state.change(
                    fn=lambda s: gr.update(visible=bool(s is not None and s.role.value == "admin")),
                    inputs=[session_state],
                    outputs=[admin_users_controls],
                )

            # ===== TAB 3: Project Selection =====
            with gr.Tab("📁 Selecionar Projeto", id="project_tab"):
                project_info_display = gr.Markdown(
                    value="⚠️ Faça login primeiro na aba **Login**"
                )
                project_selector = gr.Dropdown(
                    choices=[],
                    label="Projeto Autorizado",
                    interactive=False,
                )

                def update_project_selector(session):
                    """Update project dropdown when user logs in."""
                    if session is None:
                        return (
                            gr.Dropdown(choices=[], value=None, interactive=False),
                            "❌ Not logged in. Please login first.",
                            None,
                        )

                    projects = session.authorized_projects
                    if not projects:
                        return (
                            gr.Dropdown(choices=[], value=None, interactive=False),
                            "⚠️ **No Projects Assigned**\n\nYou don't have access to any projects yet. Contact an administrator.",
                            None,
                        )

                    selected = projects[0]
                    role = auth_service.get_user_role_for_project(session.username, selected)
                    role_label = role.value.upper() if role else "UNKNOWN"
                    return (
                        gr.Dropdown(choices=projects, value=selected, interactive=True),
                        f"📁 **Project:** {selected} | **Your Role:** {role_label}",
                        selected,
                    )

                session_state.change(
                    fn=update_project_selector,
                    inputs=[session_state],
                    outputs=[project_selector, project_info_display, selected_project_state],
                )

                def update_selected_project(selected: str, session):
                    """Update state when project is selected."""
                    if session and selected:
                        return selected
                    return None

                project_selector.change(
                    fn=update_selected_project,
                    inputs=[project_selector, session_state],
                    outputs=[selected_project_state],
                )

            # ===== TAB 4: Validation =====
            with gr.Tab("✓ Validação", id="validation_tab"):
                validation_status = gr.Markdown(
                    value="ℹ️ Faça login e selecione um projeto para começar"
                )

                def get_validation_status(session, selected_project):
                    """Show status message based on login/project state."""
                    if session is None:
                        return "❌ **Não autenticado** — Faça login na aba **Login** primeiro"
                    if selected_project is None:
                        return f"⚠️ **Projeto não selecionado** — Selecione um projeto na aba **Selecionar Projeto**"
                    return f"✅ **Pronto para validar** — Projeto: **{selected_project}** | Usuário: **{session.username}**\n\n(Validação será carregada abaixo)"

                session_state.change(
                    fn=lambda s, p: get_validation_status(s, p),
                    inputs=[session_state, selected_project_state],
                    outputs=[validation_status],
                )

                selected_project_state.change(
                    fn=lambda s, p: get_validation_status(s, p),
                    inputs=[session_state, selected_project_state],
                    outputs=[validation_status],
                )

                # Note: In a real implementation, we would load build_demo_app(selected_project) here
                # For now, we show a placeholder since Gradio tabs don't support dynamic nested Blocks
                gr.Markdown("---")
                validation_placeholder = gr.Textbox(
                    label="Validação",
                    value="📋 Interface de validação será carregada aqui para o projeto selecionado",
                    interactive=False,
                    lines=10,
                )

    return wrapper
