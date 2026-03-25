import gradio as gr

from src.domain.models import Detection
from src.repositories.in_memory_detection_repository import InMemoryDetectionRepository
from src.services.detection_queue_service import DetectionQueueService


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


def _page_to_table(service: DetectionQueueService, page: int, scientific_name: str, min_confidence: float):
    filter_name = scientific_name.strip() if scientific_name.strip() else None
    page_obj = service.get_page(
        project_slug="demo-project",
        page=page,
        page_size=2,
        scientific_name=filter_name,
        min_confidence=min_confidence,
    )

    rows = [
        [
            item.detection_key,
            item.audio_id,
            item.scientific_name,
            round(item.confidence, 3),
            item.start_time,
            item.end_time,
        ]
        for item in page_obj.items
    ]
    status = f"Pagina {page_obj.page}/{page_obj.total_pages} | Total filtrado: {page_obj.total_items}"
    return rows, status, page_obj.page


def create_app() -> gr.Blocks:
    service = _seed_service()

    with gr.Blocks(title="BirdNET Validator HF") as demo:
        gr.Markdown("# BirdNET Validator HF")
        gr.Markdown("Sprint 2 kickoff: fila paginada de deteccoes (demo local).")

        with gr.Row():
            species_filter = gr.Textbox(label="Filtro especie", placeholder="Ex: Cyanocorax cyanopogon")
            min_confidence = gr.Slider(label="Confianca minima", minimum=0.0, maximum=1.0, step=0.01, value=0.0)

        with gr.Row():
            prev_btn = gr.Button("Pagina anterior")
            next_btn = gr.Button("Proxima pagina")
            refresh_btn = gr.Button("Aplicar filtros")

        page_state = gr.State(value=1)
        table = gr.Dataframe(
            headers=["detection_key", "audio_id", "scientific_name", "confidence", "start_time", "end_time"],
            label="Deteccoes",
            interactive=False,
        )
        status = gr.Textbox(label="Status", interactive=False)

        def refresh(page: int, species: str, confidence: float):
            return _page_to_table(service, page=page, scientific_name=species, min_confidence=confidence)

        def go_next(page: int, species: str, confidence: float):
            return refresh(page + 1, species, confidence)

        def go_prev(page: int, species: str, confidence: float):
            return refresh(max(1, page - 1), species, confidence)

        demo.load(
            fn=refresh,
            inputs=[page_state, species_filter, min_confidence],
            outputs=[table, status, page_state],
        )
        refresh_btn.click(
            fn=lambda species, confidence: refresh(1, species, confidence),
            inputs=[species_filter, min_confidence],
            outputs=[table, status, page_state],
        )
        next_btn.click(
            fn=go_next,
            inputs=[page_state, species_filter, min_confidence],
            outputs=[table, status, page_state],
        )
        prev_btn.click(
            fn=go_prev,
            inputs=[page_state, species_filter, min_confidence],
            outputs=[table, status, page_state],
        )

    return demo
