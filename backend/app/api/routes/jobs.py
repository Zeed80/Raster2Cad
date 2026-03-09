from __future__ import annotations

from fastapi import APIRouter, File, Form, HTTPException, UploadFile

from app.schemas.models import (
    ClarificationResponsePayload,
    ChatEditPayload,
    CreateJobPayload,
    DrawingDomain,
    IsoViewSettings,
    JobMode,
    ModelRuntimeOptions,
    OutputFormat,
    ProviderType,
    ViewPatchPayload,
    ViewPreset,
)
from app.services.pipeline import PipelineService

router = APIRouter(prefix="/jobs", tags=["jobs"])
pipeline = PipelineService()


@router.post("")
async def create_job(
    file: UploadFile = File(...),
    mode: JobMode = Form(...),
    domain: DrawingDomain = Form(DrawingDomain.AUTO),
    output_format: OutputFormat = Form(OutputFormat.DXF),
    model_id: str = Form(...),
    provider: ProviderType = Form(ProviderType.VLLM),
    auto_tune: bool = Form(True),
    num_ctx: int | None = Form(None),
    num_predict: int | None = Form(None),
    keep_alive: str | None = Form(None),
    iso_preset: ViewPreset = Form(ViewPreset.ISO_NE),
    rotate_x: float = Form(35.264),
    rotate_y: float = Form(45.0),
    rotate_z: float = Form(0.0),
    scale: float = Form(1.0),
    explode_spacing: float = Form(12.0),
    annotation_density: float = Form(0.5),
):
    payload = CreateJobPayload(
        mode=mode,
        domain=domain,
        output_format=output_format,
        model_id=model_id,
        provider=provider,
        runtime_options=ModelRuntimeOptions(
            auto_tune=auto_tune,
            num_ctx=num_ctx,
            num_predict=num_predict,
            keep_alive=keep_alive,
        ),
        iso_view=IsoViewSettings(
            preset=iso_preset,
            rotate_x=rotate_x,
            rotate_y=rotate_y,
            rotate_z=rotate_z,
            scale=scale,
            explode_spacing=explode_spacing,
            annotation_density=annotation_density,
        ),
    )
    job = await pipeline.create_job(file=file, payload=payload)
    return job.model_dump(mode="json")


@router.get("/{job_id}")
async def get_job(job_id: str):
    try:
        return pipeline.get_job(job_id).model_dump(mode="json")
    except FileNotFoundError as exc:
        raise HTTPException(status_code=404, detail="Job not found") from exc


@router.get("/{job_id}/artifacts")
async def get_artifacts(job_id: str):
    try:
        job = pipeline.get_job(job_id)
    except FileNotFoundError as exc:
        raise HTTPException(status_code=404, detail="Job not found") from exc
    return job.artifacts.model_dump(mode="json")


@router.post("/{job_id}/clarification")
async def answer_clarification(job_id: str, payload: ClarificationResponsePayload):
    try:
        job = await pipeline.answer_clarification(job_id, payload)
    except FileNotFoundError as exc:
        raise HTTPException(status_code=404, detail="Job not found") from exc
    return job.model_dump(mode="json")


@router.post("/{job_id}/chat-edit")
async def chat_edit(job_id: str, payload: ChatEditPayload):
    try:
        job = await pipeline.apply_chat_edit(job_id, payload.message)
    except FileNotFoundError as exc:
        raise HTTPException(status_code=404, detail="Job not found") from exc
    return job.model_dump(mode="json")


@router.patch("/{job_id}/view")
async def patch_view(job_id: str, payload: ViewPatchPayload):
    try:
        job = await pipeline.patch_view(job_id, payload)
    except FileNotFoundError as exc:
        raise HTTPException(status_code=404, detail="Job not found") from exc
    return job.model_dump(mode="json")
