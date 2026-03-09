from __future__ import annotations

import asyncio
import json
import re
import uuid
from datetime import datetime, timezone
from pathlib import Path

from fastapi import UploadFile

from app.core.config import get_settings
from app.schemas.models import (
    ArtifactManifest,
    BoundingBox,
    CadDsl,
    CadEntityCommand,
    ChatEdit,
    ClarificationOption,
    ClarificationPrompt,
    ClarificationResponsePayload,
    CreateJobPayload,
    DimensionElement,
    DrawingDomain,
    EngineeringObject,
    EngineeringSceneGraph,
    IsoScene,
    IsoViewSettings,
    JobRecord,
    JobMode,
    JobStatus,
    OutputFormat,
    ProviderType,
    TextElement,
    ViewPatchPayload,
)
from app.services.copy_rebuild_service import CopyRebuildService
from app.services.copy_trace_service import CopyTraceService
from app.services.dxf_service import DxfService
from app.services.image_service import ImageService
from app.services.model_registry import ModelRegistry
from app.services.repository import FileJobRepository
from app.services.runtime_profile import resolve_runtime_options


class PipelineService:
    def __init__(self) -> None:
        self.settings = get_settings()
        self.repo = FileJobRepository()
        self.registry = ModelRegistry()
        self.dxf_service = DxfService()
        self.image_service = ImageService()
        self.copy_rebuild_service = CopyRebuildService(self.image_service)
        self.copy_trace_service = CopyTraceService()
        self._queue: asyncio.Queue[str] = asyncio.Queue()
        self._worker_task: asyncio.Task | None = None
        self._enqueued: set[str] = set()

    async def start(self) -> None:
        if self._worker_task and not self._worker_task.done():
            return
        self._worker_task = asyncio.create_task(self._worker_loop())
        for job in self.repo.list_jobs():
            if job.status in {JobStatus.QUEUED, JobStatus.RUNNING}:
                await self.enqueue(job.job_id)

    async def shutdown(self) -> None:
        if not self._worker_task:
            return
        self._worker_task.cancel()
        try:
            await self._worker_task
        except asyncio.CancelledError:
            pass
        self._worker_task = None

    async def create_job(self, *, file: UploadFile, payload: CreateJobPayload) -> JobRecord:
        await self.start()
        job_id = uuid.uuid4().hex
        suffix = Path(file.filename or "drawing.bin").suffix or ".bin"
        upload_path = self.settings.uploads_dir / f"{job_id}{suffix}"
        upload_path.write_bytes(await file.read())
        artifact_dir = self.settings.artifacts_dir / job_id
        artifact_dir.mkdir(parents=True, exist_ok=True)
        runtime_model_id, runtime_model_details = await self._runtime_profile_source(
            provider=payload.provider,
            model_id=payload.model_id,
            auto_tune=payload.runtime_options.auto_tune,
        )
        runtime_options = resolve_runtime_options(
            provider=payload.provider,
            model_id=runtime_model_id,
            details=runtime_model_details,
            requested=payload.runtime_options,
            default_num_ctx=self.settings.ollama_num_ctx,
            default_num_predict=self.settings.ollama_num_predict,
        )

        job = JobRecord(
            job_id=job_id,
            filename=file.filename or upload_path.name,
            source_path=str(upload_path),
            mode=payload.mode,
            domain=payload.domain,
            output_format=payload.output_format,
            status=JobStatus.QUEUED,
            model_id=payload.model_id,
            provider=payload.provider,
            runtime_options=runtime_options,
            iso_view=payload.iso_view,
            artifacts=ArtifactManifest(),
        )
        self.repo.save(job)
        await self.enqueue(job_id)
        return self.repo.get(job_id)

    async def enqueue(self, job_id: str) -> None:
        await self.start()
        if job_id in self._enqueued:
            return
        self._enqueued.add(job_id)
        await self._queue.put(job_id)

    async def answer_clarification(self, job_id: str, payload: ClarificationResponsePayload) -> JobRecord:
        job = self.repo.get(job_id)
        if not job.scene_graph or not job.clarification:
            return job

        option = next((item for item in job.clarification.options if item.id == payload.option_id), None)
        if not option:
            return job

        mapped = {
            "piping": DrawingDomain.PIPING,
            "vessels": DrawingDomain.VESSELS,
            "parts": DrawingDomain.PARTS,
            "general": DrawingDomain.GENERAL,
        }
        resolved_domain = mapped.get(option.id, DrawingDomain.GENERAL)
        job.scene_graph.domain = resolved_domain
        job.domain = resolved_domain
        job.scene_graph.notes.append(f"Clarified via user input: {option.label}")
        job.scene_graph.unresolved_relations = []
        job.clarification = None
        job.confidence = 0.9
        job.status = JobStatus.QUEUED
        job.stage = "queued"
        job.updated_at = utcnow()
        self.repo.save(job)
        await self.enqueue(job_id)
        return self.repo.get(job_id)

    async def apply_chat_edit(self, job_id: str, message: str) -> JobRecord:
        job = self.repo.get(job_id)
        edit = ChatEdit(message=message, applied=False)
        if not job.scene_graph:
            job.chat_history.append(edit)
            self.repo.save(job)
            return job

        updated_graph = None
        if self.settings.enable_live_model_calls:
            provider = self.registry.get_provider(job.provider)
            patcher_model = job.resolved_models.get("patcher", job.model_id)
            updated_graph = await provider.patch_scene_graph(
                model_id=patcher_model,
                scene_graph=job.scene_graph,
                instruction=message,
                runtime_options=job.runtime_options,
            )
            if updated_graph is not None and not self._is_safe_patch(job.scene_graph, updated_graph):
                updated_graph = None

        if updated_graph is None:
            updated_graph, edit = self._apply_local_chat_patch(job.scene_graph, edit)
        else:
            edit.applied = True
            edit.summary = f"Patched by model {job.resolved_models.get('patcher', job.model_id)}."

        job.scene_graph = updated_graph
        job.chat_history.append(edit)
        preview_path = self.settings.artifacts_dir / job.job_id / "source-preview.png"
        if not preview_path.exists():
            preview_path = self.image_service.normalize_source(Path(job.source_path), self.settings.artifacts_dir / job.job_id)
        job.cad_dsl = self._build_cad_dsl(updated_graph, mode=job.mode, preview_path=preview_path)
        job.iso_scene = self._build_iso_scene(updated_graph, job.iso_view)
        job.critic_findings = await self._critic_findings(job, updated_graph)
        self._write_artifacts(job)
        job.updated_at = utcnow()
        self.repo.save(job)
        return job

    async def patch_view(self, job_id: str, payload: ViewPatchPayload) -> JobRecord:
        job = self.repo.get(job_id)
        job.iso_view = payload.iso_view
        if job.scene_graph:
            job.iso_scene = self._build_iso_scene(job.scene_graph, payload.iso_view)
            self._write_artifacts(job, write_drawing=False)
        job.updated_at = utcnow()
        self.repo.save(job)
        return job

    def get_job(self, job_id: str) -> JobRecord:
        return self.repo.get(job_id)

    async def list_models(self):
        return await self.registry.list_models()

    async def run_job(self, job_id: str) -> JobRecord:
        job = self.repo.get(job_id)
        artifact_dir = self.settings.artifacts_dir / job.job_id
        artifact_dir.mkdir(parents=True, exist_ok=True)
        try:
            job.status = JobStatus.RUNNING
            job.error = None
            job.stage = "normalize"
            job.updated_at = utcnow()
            self.repo.save(job)

            preview_path = self.image_service.normalize_source(Path(job.source_path), artifact_dir)

            job.stage = "resolve_models"
            job.updated_at = utcnow()
            job.resolved_models = await self._resolve_models(job)
            self.repo.save(job)

            job.stage = "preflight"
            job.updated_at = utcnow()
            self.repo.save(job)
            await self._preflight_models(job)

            job.stage = "parse"
            job.scene_graph = await self._parse_scene_graph(job, preview_path)
            job.confidence = job.scene_graph.confidence
            job.updated_at = utcnow()
            self.repo.save(job)

            if (
                job.mode != JobMode.COPY
                and job.scene_graph.unresolved_relations
                and job.confidence < self.settings.low_confidence_threshold
            ):
                job.status = JobStatus.NEEDS_INPUT
                job.stage = "clarification"
                job.clarification = job.scene_graph.unresolved_relations[0]
                job.updated_at = utcnow()
                self._write_artifacts(job, preview_path=preview_path, write_drawing=False)
                self.repo.save(job)
                return job

            job.stage = "compile"
            job.cad_dsl = self._build_cad_dsl(job.scene_graph, mode=job.mode, preview_path=preview_path)
            job.iso_scene = self._build_iso_scene(job.scene_graph, job.iso_view)
            job.updated_at = utcnow()
            self.repo.save(job)

            job.stage = "critic"
            job.critic_findings = await self._critic_findings(job, job.scene_graph)
            job.updated_at = utcnow()
            self.repo.save(job)

            job.stage = "artifacts"
            self._write_artifacts(job, preview_path=preview_path)
            job.status = JobStatus.DONE
            job.stage = "done"
            job.error = None
            job.updated_at = utcnow()
            self.repo.save(job)
            return job
        except Exception as exc:
            job.status = JobStatus.FAILED
            job.stage = "failed"
            job.error = str(exc)
            job.updated_at = utcnow()
            self.repo.save(job)
            return job

    async def _worker_loop(self) -> None:
        while True:
            job_id = await self._queue.get()
            self._enqueued.discard(job_id)
            try:
                await self.run_job(job_id)
            finally:
                self._queue.task_done()

    async def _resolve_models(self, job: JobRecord) -> dict[str, str]:
        selected = await self.registry.find_model(job.provider, job.model_id)
        parser_model = job.model_id
        if selected is not None and not selected.capabilities.vision:
            default_model = self.settings.default_primary_model
            default_descriptor = await self.registry.find_model(job.provider, default_model)
            if default_descriptor is None or not default_descriptor.capabilities.vision:
                raise RuntimeError(
                    f"Selected model {job.model_id} is not vision-capable and no vision parser is configured on provider {job.provider.value}."
                )
            parser_model = default_model
        return {
            "parser": parser_model,
            "critic": job.model_id,
            "patcher": job.model_id,
        }

    async def _parse_scene_graph(self, job: JobRecord, preview_path: Path) -> EngineeringSceneGraph:
        if self.settings.enable_live_model_calls:
            provider = self.registry.get_provider(job.provider)
            if job.mode == JobMode.COPY:
                return await self.copy_rebuild_service.parse_clean_copy(
                    job=job,
                    provider=provider,
                    model_id=job.resolved_models.get("parser", job.model_id),
                    preview_path=preview_path,
                    artifact_dir=self.settings.artifacts_dir / job.job_id,
                )
            prompt = self._build_parse_prompt(job)
            graph = await provider.parse_drawing(
                model_id=job.resolved_models.get("parser", job.model_id),
                source_path=preview_path,
                prompt=prompt,
                runtime_options=job.runtime_options,
            )
            if graph is not None and not graph.objects:
                graph = await provider.parse_drawing(
                    model_id=job.resolved_models.get("parser", job.model_id),
                    source_path=preview_path,
                    prompt=(
                        "The previous extraction returned no objects. "
                        "Retry and explicitly detect every visible object. "
                        "At minimum return non-empty objects for the main linework, fittings, and labels visible in the image."
                    ),
                    runtime_options=job.runtime_options,
                )
            if graph is not None:
                graph.sheet_name = job.filename
                graph.mode = job.mode
                if job.domain != DrawingDomain.AUTO:
                    graph.domain = job.domain
                if job.resolved_models.get("parser") != job.model_id:
                    graph.notes.append(
                        f"Parsing used fallback vision model {job.resolved_models['parser']} because selected model is not vision-capable."
                    )
                return graph

        if self.settings.allow_fixture_fallback:
            return self._mock_scene_graph(job)
        raise RuntimeError(
            f"Live parsing failed for provider {job.provider.value} model {job.resolved_models.get('parser', job.model_id)}."
        )

    async def _preflight_models(self, job: JobRecord) -> None:
        parser_model = job.resolved_models.get("parser", job.model_id)
        descriptor = await self.registry.find_model(job.provider, parser_model)
        if descriptor is not None:
            if descriptor.capabilities.vision:
                return
            raise RuntimeError(
                f"Preflight failed for parser model {parser_model} on {job.provider.value}: model is not marked as vision-capable."
            )
        parser_check = await self.registry.check_model(
            job.provider,
            parser_model,
            require_vision=True,
            runtime_options=job.runtime_options,
        )
        if not parser_check.ok:
            detail = parser_check.error or "unknown preflight error"
            raise RuntimeError(
                f"Preflight failed for parser model {parser_model} on {job.provider.value}: {detail}"
            )

    async def _critic_findings(self, job: JobRecord, scene_graph: EngineeringSceneGraph) -> list[str]:
        findings = [
            f"Parser model: {job.resolved_models.get('parser', job.model_id)}.",
            f"Domain resolved as {scene_graph.domain.value}.",
            f"Objects parsed: {len(scene_graph.objects)}.",
            f"Texts parsed: {len(scene_graph.texts)}.",
        ]
        if scene_graph.primitives:
            findings.append(f"Geometry primitives parsed: {len(scene_graph.primitives)}.")
        if job.cad_dsl:
            findings.append(f"Vector entities emitted: {len(job.cad_dsl.entities)}.")
        if self.settings.enable_live_model_calls:
            provider = self.registry.get_provider(job.provider)
            prompt = (
                f"Review a {scene_graph.domain.value} drawing in {job.mode.value} mode. "
                f"Objects: {[obj.kind for obj in scene_graph.objects]}. "
                "List likely omissions, geometry mismatches, and ambiguities."
            )
            findings.extend(
                await provider.critique_drawing(
                    model_id=job.resolved_models.get("critic", job.model_id),
                    prompt=prompt,
                    runtime_options=job.runtime_options,
                )
            )
        if scene_graph.unresolved_relations:
            findings.append("Clarification required before final confidence can be trusted.")
        return findings[:10]

    def _write_artifacts(self, job: JobRecord, *, preview_path: Path | None = None, write_drawing: bool = True) -> None:
        artifact_dir = self.settings.artifacts_dir / job.job_id
        artifact_dir.mkdir(parents=True, exist_ok=True)

        if preview_path is None:
            preview_path = artifact_dir / "source-preview.png"
            if not preview_path.exists():
                preview_path = self.image_service.normalize_source(Path(job.source_path), artifact_dir)

        scene_path = artifact_dir / "scene-graph.json"
        report_path = artifact_dir / "report.json"
        scene_path.write_text(
            job.scene_graph.model_dump_json(indent=2) if job.scene_graph else "{}",
            encoding="utf-8",
        )

        overlay_path = None
        diff_path = artifact_dir / "diff.png"
        if job.cad_dsl and job.mode == JobMode.COPY:
            overlay_path, diff_path = self.image_service.render_cad_preview(preview_path, job.cad_dsl, artifact_dir)
        elif job.scene_graph:
            overlay_path, diff_path = self.image_service.draw_overlay(preview_path, job.scene_graph, artifact_dir)

        report_path.write_text(
            json.dumps(
                {
                    "job_id": job.job_id,
                    "confidence": job.confidence,
                    "status": job.status.value,
                    "stage": job.stage,
                    "resolved_models": job.resolved_models,
                    "runtime_options": job.runtime_options.model_dump(mode="json"),
                    "critic_findings": job.critic_findings,
                    "chat_history": [item.model_dump(mode="json") for item in job.chat_history],
                },
                indent=2,
            ),
            encoding="utf-8",
        )

        if write_drawing and job.cad_dsl:
            drawing_path = artifact_dir / "drawing.dxf"
            self.dxf_service.write_dxf(job.cad_dsl, drawing_path)
            job.artifacts.drawing_path = f"/artifacts/{job.job_id}/drawing.dxf"
            if job.output_format == OutputFormat.DWG:
                dwg_path = artifact_dir / "drawing.dwg"
                converted = self.dxf_service.convert_to_dwg(drawing_path, dwg_path, self.settings.oda_converter_path)
                if converted is None:
                    raise RuntimeError(
                        "DWG conversion requested but ODA File Converter is not configured or the conversion failed."
                    )
                job.artifacts.dwg_path = f"/artifacts/{job.job_id}/drawing.dwg"

        if job.iso_scene:
            iso_path = artifact_dir / "isometric.svg"
            self.dxf_service.write_iso_svg(job.iso_scene, iso_path)
            job.artifacts.isometric_path = f"/artifacts/{job.job_id}/isometric.svg"

        job.artifacts.source_preview_path = f"/artifacts/{job.job_id}/source-preview.png"
        if overlay_path is not None:
            job.artifacts.overlay_preview_path = f"/artifacts/{job.job_id}/overlay-preview.png"
        job.artifacts.scene_graph_path = f"/artifacts/{job.job_id}/scene-graph.json"
        job.artifacts.report_path = f"/artifacts/{job.job_id}/report.json"
        job.artifacts.diff_path = f"/artifacts/{job.job_id}/diff.png"

    def _build_parse_prompt(self, job: JobRecord) -> str:
        return (
            "Analyze the engineering drawing image and return JSON with keys "
            "domain, mode, sheet_name, page_quad, objects, texts, dimensions, unresolved_relations, confidence, notes. "
            f"Mode must be {job.mode.value}. User-selected domain hint: {job.domain.value}. "
            "Never leave objects empty when visible geometry exists. "
            "Each object must include object_id, kind, label, layer, confidence, bbox{x,y,width,height}, attributes, and connections. "
            "Each text must include text_id, content, confidence, and bbox. "
            "Each dimension must include dimension_id, label, value, confidence, and bbox. "
            "For piping drawings identify pipelines, valves, flanges, welds, vessels, tees, reducers, and supports. "
            "For vessels identify shells, nozzles, manholes, saddles, and level references. "
            "For part drawings identify outer profiles, holes, shafts, plates, cutouts, and annotations. "
            "If the domain is unclear, add one clarification prompt with 2-4 options."
        )

    def _apply_local_chat_patch(self, scene_graph: EngineeringSceneGraph, edit: ChatEdit) -> tuple[EngineeringSceneGraph, ChatEdit]:
        lowered = edit.message.lower()
        summary = "No structural patch matched; note saved for follow-up."
        applied = False

        object_kind_match = re.search(r"это\s+([а-яa-z0-9_-]+)\s*,?\s*а не\s+([а-яa-z0-9_-]+)", lowered)
        if object_kind_match and scene_graph.objects:
            new_kind = object_kind_match.group(1)
            old_kind = object_kind_match.group(2)
            target = next((obj for obj in scene_graph.objects if old_kind in obj.kind.lower() or old_kind in obj.label.lower()), None)
            if target:
                target.kind = new_kind
                target.label = new_kind.title()
                summary = f"Updated object {target.object_id} from {old_kind} to {new_kind}."
                applied = True

        if not applied and "смест" in lowered and "вправо" in lowered:
            for text in scene_graph.texts:
                if text.bbox:
                    text.bbox.x += 12
            for dimension in scene_graph.dimensions:
                if dimension.bbox:
                    dimension.bbox.x += 12
            summary = "Shifted text and dimension entities to the right."
            applied = True

        edit.applied = applied
        edit.summary = summary
        scene_graph.notes.append(summary)
        return scene_graph, edit

    def _is_safe_patch(self, original: EngineeringSceneGraph, patched: EngineeringSceneGraph) -> bool:
        if original.objects and not patched.objects:
            return False
        if len(patched.objects) < max(1, len(original.objects) // 2):
            return False
        if original.primitives and not patched.primitives:
            return False
        if len(patched.primitives) < max(1, len(original.primitives) // 2):
            return False
        return True

    def _mock_scene_graph(self, job: JobRecord) -> EngineeringSceneGraph:
        inferred_domain = job.domain
        lowered_name = job.filename.lower()
        if inferred_domain == DrawingDomain.AUTO:
            inferred_domain = self._infer_domain_from_name(lowered_name)

        unresolved: list[ClarificationPrompt] = []
        confidence = 0.88
        notes = ["Fixture fallback scene graph was used because live parsing was unavailable."]

        if job.domain == DrawingDomain.AUTO and inferred_domain == DrawingDomain.GENERAL:
            confidence = 0.58
            unresolved.append(
                ClarificationPrompt(
                    prompt_id="domain-1",
                    question="Какой тип чертежа ближе к исходнику?",
                    options=[
                        ClarificationOption(id="piping", label="Трубопроводы"),
                        ClarificationOption(id="vessels", label="Сосуды и емкости"),
                        ClarificationOption(id="parts", label="Детали и элементы"),
                        ClarificationOption(id="general", label="Смешанный/общий"),
                    ],
                )
            )

        objects, texts, dimensions = self._domain_fixture(inferred_domain)
        return EngineeringSceneGraph(
            domain=inferred_domain,
            mode=job.mode,
            sheet_name=job.filename,
            page_quad=[[0, 0], [1000, 0], [1000, 700], [0, 700]],
            objects=objects,
            texts=texts,
            dimensions=dimensions,
            unresolved_relations=unresolved,
            confidence=confidence,
            notes=notes,
        )

    def _domain_fixture(self, domain: DrawingDomain):
        if domain == DrawingDomain.PIPING:
            objects = [
                EngineeringObject(
                    object_id="obj-pipe-1",
                    kind="pipeline",
                    label="Main pipeline",
                    bbox=BoundingBox(x=80, y=240, width=580, height=24),
                    connections=["obj-flange-1", "obj-valve-1"],
                    attributes={"diameter": "DN200"},
                ),
                EngineeringObject(
                    object_id="obj-flange-1",
                    kind="flange",
                    label="Flange",
                    bbox=BoundingBox(x=220, y=220, width=48, height=48),
                    attributes={"rating": "PN40"},
                ),
                EngineeringObject(
                    object_id="obj-valve-1",
                    kind="valve",
                    label="Valve",
                    bbox=BoundingBox(x=420, y=200, width=72, height=72),
                ),
            ]
            texts = [TextElement(text_id="txt-1", content="GMS inlet", bbox=BoundingBox(x=90, y=180, width=120, height=28))]
            dimensions = [DimensionElement(dimension_id="dim-1", label="L1", value="2400", bbox=BoundingBox(x=260, y=300, width=160, height=36))]
            return objects, texts, dimensions

        if domain == DrawingDomain.VESSELS:
            objects = [
                EngineeringObject(
                    object_id="obj-vessel-1",
                    kind="vessel",
                    label="Separator vessel",
                    bbox=BoundingBox(x=240, y=120, width=180, height=340),
                    attributes={"orientation": "vertical"},
                ),
                EngineeringObject(
                    object_id="obj-nozzle-1",
                    kind="nozzle",
                    label="Nozzle N1",
                    bbox=BoundingBox(x=418, y=220, width=44, height=28),
                    connections=["obj-vessel-1"],
                ),
            ]
            texts = [TextElement(text_id="txt-1", content="V-101", bbox=BoundingBox(x=260, y=84, width=100, height=30))]
            dimensions = [DimensionElement(dimension_id="dim-1", label="H", value="3200", bbox=BoundingBox(x=460, y=160, width=80, height=180))]
            return objects, texts, dimensions

        if domain == DrawingDomain.PARTS:
            objects = [
                EngineeringObject(
                    object_id="obj-plate-1",
                    kind="plate",
                    label="Base plate",
                    bbox=BoundingBox(x=180, y=180, width=360, height=240),
                    attributes={"thickness": "12"},
                ),
                EngineeringObject(
                    object_id="obj-hole-1",
                    kind="hole",
                    label="Mount hole",
                    bbox=BoundingBox(x=280, y=250, width=40, height=40),
                ),
            ]
            texts = [TextElement(text_id="txt-1", content="DETAIL A", bbox=BoundingBox(x=180, y=130, width=120, height=30))]
            dimensions = [DimensionElement(dimension_id="dim-1", label="W", value="600", bbox=BoundingBox(x=240, y=450, width=200, height=30))]
            return objects, texts, dimensions

        objects = [
            EngineeringObject(
                object_id="obj-general-1",
                kind="assembly",
                label="General assembly",
                bbox=BoundingBox(x=160, y=160, width=420, height=280),
            )
        ]
        texts = [TextElement(text_id="txt-1", content="GENERAL DRAWING", bbox=BoundingBox(x=180, y=120, width=200, height=30))]
        dimensions = []
        return objects, texts, dimensions

    def _build_cad_dsl(self, scene_graph: EngineeringSceneGraph, *, mode: JobMode, preview_path: Path | None = None) -> CadDsl:
        if mode == JobMode.COPY:
            if len(scene_graph.primitives) >= 24:
                return self.copy_rebuild_service.build_cad_dsl(scene_graph)
            if preview_path is None:
                raise RuntimeError("Copy mode requires either model primitives or a preview path for clean geometry fitting.")
            trace_result = self.copy_trace_service.trace_to_dsl(preview_path)
            dsl = trace_result.dsl
            for text in scene_graph.texts:
                insert = text.insert or ([text.bbox.x, text.bbox.y + text.bbox.height] if text.bbox else None)
                if not text.content.strip() or insert is None:
                    continue
                dsl.entities.append(
                    CadEntityCommand(
                        entity_type="mtext",
                        layer="TEXT",
                        params={
                            "text": text.content,
                            "insert": insert,
                            "height": text.height,
                            "rotation": text.rotation,
                        },
                    )
                )
            for dimension in scene_graph.dimensions:
                if dimension.start and dimension.end:
                    dsl.entities.append(
                        CadEntityCommand(
                            entity_type="line",
                            layer=dimension.layer,
                            params={"start": dimension.start, "end": dimension.end},
                        )
                    )
                insert = dimension.text_position or ([dimension.bbox.x, dimension.bbox.y] if dimension.bbox else None)
                if insert is None:
                    continue
                dsl.entities.append(
                    CadEntityCommand(
                        entity_type="text",
                        layer=dimension.layer,
                        params={
                            "text": dimension.text or f"{dimension.label} {dimension.value}".strip(),
                            "insert": insert,
                            "height": max(6.0, dimension.bbox.height if dimension.bbox else 8.0),
                            "rotation": dimension.rotation,
                        },
                    )
                )
            scene_graph.notes.append(
                "Model returned insufficient clean primitives; geometry was rebuilt by fitted line/circle extraction and texts were kept from model output."
            )
            return dsl

        entities: list[CadEntityCommand] = []
        for obj in scene_graph.objects:
            bbox = obj.bbox
            if not bbox:
                continue
            if obj.kind in {"pipeline", "pipe"}:
                y = bbox.y + bbox.height / 2
                entities.append(CadEntityCommand(entity_type="line", layer="MAIN", params={"start": [bbox.x, y], "end": [bbox.x + bbox.width, y]}))
            elif obj.kind in {"flange", "hole"}:
                center = [bbox.x + bbox.width / 2, bbox.y + bbox.height / 2]
                entities.append(CadEntityCommand(entity_type="circle", layer="MAIN", params={"center": center, "radius": min(bbox.width, bbox.height) / 2}))
            else:
                points = [
                    [bbox.x, bbox.y],
                    [bbox.x + bbox.width, bbox.y],
                    [bbox.x + bbox.width, bbox.y + bbox.height],
                    [bbox.x, bbox.y + bbox.height],
                ]
                entities.append(CadEntityCommand(entity_type="lwpolyline", layer="MAIN", params={"points": points, "closed": True}))
            entities.append(
                CadEntityCommand(
                    entity_type="text",
                    layer="TEXT",
                    params={"text": obj.label, "insert": [bbox.x, max(10, bbox.y - 16)], "height": 10},
                )
            )

        for text in scene_graph.texts:
            insert = [text.bbox.x, text.bbox.y] if text.bbox else [20, 20]
            entities.append(CadEntityCommand(entity_type="mtext", layer="TEXT", params={"text": text.content, "insert": insert, "height": 8}))

        for dimension in scene_graph.dimensions:
            bbox = dimension.bbox or BoundingBox(x=60, y=60, width=120, height=24)
            entities.append(CadEntityCommand(entity_type="line", layer="DIM", params={"start": [bbox.x, bbox.y], "end": [bbox.x + bbox.width, bbox.y]}))
            entities.append(
                CadEntityCommand(
                    entity_type="text",
                    layer="DIM",
                    params={"text": f"{dimension.label}={dimension.value}", "insert": [bbox.x, bbox.y - 8], "height": 8},
                )
            )

        return CadDsl(entities=entities)

    def _build_iso_scene(self, scene_graph: EngineeringSceneGraph, iso_view: IsoViewSettings) -> IsoScene:
        entities: list[CadEntityCommand] = []
        offset_x = 280
        offset_y = 200
        for index, obj in enumerate(scene_graph.objects):
            base_x = offset_x + index * iso_view.explode_spacing * 6
            base_y = offset_y + index * iso_view.explode_spacing * 2
            entities.extend(
                [
                    CadEntityCommand(entity_type="line", layer="ISO", params={"start": [base_x, base_y], "end": [base_x + 90, base_y - 50]}),
                    CadEntityCommand(entity_type="line", layer="ISO", params={"start": [base_x, base_y], "end": [base_x, base_y + 90]}),
                    CadEntityCommand(entity_type="line", layer="ISO", params={"start": [base_x, base_y + 90], "end": [base_x + 90, base_y + 40]}),
                    CadEntityCommand(entity_type="text", layer="ISO", params={"text": obj.label, "insert": [base_x + 16, base_y + 118]}),
                ]
            )

        return IsoScene(
            preset=iso_view.preset,
            camera={
                "rotate_x": iso_view.rotate_x,
                "rotate_y": iso_view.rotate_y,
                "rotate_z": iso_view.rotate_z,
                "scale": iso_view.scale,
            },
            entities=entities,
            assumptions=["Pseudo-3D view synthesized from the parsed scene graph."],
        )

    def _infer_domain_from_name(self, filename: str) -> DrawingDomain:
        domain_map = {
            DrawingDomain.PIPING: ("pipe", "pipeline", "грс", "гис", "кс", "обвяз", "flange", "valve"),
            DrawingDomain.VESSELS: ("vessel", "separator", "tank", "емк", "сосуд"),
            DrawingDomain.PARTS: ("detail", "part", "plate", "shaft", "детал"),
        }
        for domain, tokens in domain_map.items():
            if any(token in filename for token in tokens):
                return domain
        return DrawingDomain.GENERAL

    async def _runtime_profile_source(
        self,
        *,
        provider: ProviderType,
        model_id: str,
        auto_tune: bool,
    ) -> tuple[str, dict]:
        descriptor = await self.registry.find_model(provider, model_id)
        if not auto_tune or provider != ProviderType.OLLAMA:
            return model_id, descriptor.details if descriptor else {}
        if descriptor is not None and descriptor.capabilities.vision:
            return descriptor.id, descriptor.details
        fallback = await self.registry.find_model(provider, self.settings.default_primary_model)
        if fallback is not None and fallback.capabilities.vision:
            return fallback.id, fallback.details
        return model_id, descriptor.details if descriptor else {}

def utcnow() -> datetime:
    return datetime.now(timezone.utc)
