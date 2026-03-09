from __future__ import annotations

from datetime import datetime, timezone
from enum import Enum
from typing import Any

from pydantic import BaseModel, Field


def utcnow() -> datetime:
    return datetime.now(timezone.utc)


class ProviderType(str, Enum):
    VLLM = "vllm"
    OLLAMA = "ollama"


class JobMode(str, Enum):
    COPY = "copy"
    ISOMETRY = "isometry"


class DrawingDomain(str, Enum):
    AUTO = "auto"
    PIPING = "piping"
    VESSELS = "vessels"
    PARTS = "parts"
    GENERAL = "general"


class OutputFormat(str, Enum):
    DXF = "dxf"
    DWG = "dwg"


class JobStatus(str, Enum):
    QUEUED = "queued"
    RUNNING = "running"
    NEEDS_INPUT = "needs_input"
    DONE = "done"
    FAILED = "failed"


class ViewPreset(str, Enum):
    ISO_NE = "iso-ne"
    ISO_NW = "iso-nw"
    ISO_SE = "iso-se"
    ISO_SW = "iso-sw"
    TOP_FRONT_RIGHT = "top-front-right"


class CapabilityProfile(BaseModel):
    vision: bool = False
    reasoning: bool = True
    tool_calling: bool = True
    structured_json: bool = True
    max_context: int | None = None
    provider: ProviderType
    role_fit: list[str] = Field(default_factory=list)


class ModelRuntimeHints(BaseModel):
    num_ctx: int
    num_predict: int
    keep_alive: str | None = None
    rationale: str | None = None


class ModelRuntimeOptions(BaseModel):
    auto_tune: bool = True
    num_ctx: int | None = None
    num_predict: int | None = None
    keep_alive: str | None = None


class ModelDescriptor(BaseModel):
    id: str
    display_name: str
    provider: ProviderType
    capabilities: CapabilityProfile
    recommended: bool = False
    summary: str | None = None
    details: dict[str, Any] = Field(default_factory=dict)
    runtime_hints: ModelRuntimeHints | None = None


class ModelCheckPayload(BaseModel):
    provider: ProviderType
    model_id: str
    require_vision: bool = False


class ModelCheckResult(BaseModel):
    provider: ProviderType
    model_id: str
    reachable: bool = False
    available: bool = False
    vision_capable: bool = False
    can_text: bool = False
    can_vision: bool = False
    ok: bool = False
    error: str | None = None
    details: dict[str, Any] = Field(default_factory=dict)


class IsoViewSettings(BaseModel):
    preset: ViewPreset = ViewPreset.ISO_NE
    rotate_x: float = 35.264
    rotate_y: float = 45.0
    rotate_z: float = 0.0
    scale: float = 1.0
    explode_spacing: float = 12.0
    annotation_density: float = 0.5


class ClarificationOption(BaseModel):
    id: str
    label: str
    description: str | None = None


class ClarificationPrompt(BaseModel):
    prompt_id: str
    question: str
    options: list[ClarificationOption]
    related_object_ids: list[str] = Field(default_factory=list)


class BoundingBox(BaseModel):
    x: float
    y: float
    width: float
    height: float


class EngineeringObject(BaseModel):
    object_id: str
    kind: str
    label: str
    bbox: BoundingBox | None = None
    layer: str = "MAIN"
    confidence: float = 0.8
    attributes: dict[str, Any] = Field(default_factory=dict)
    connections: list[str] = Field(default_factory=list)


class TextElement(BaseModel):
    text_id: str
    content: str
    bbox: BoundingBox | None = None
    insert: list[float] | None = None
    height: float = 8.0
    rotation: float = 0.0
    style: str = "STANDARD"
    confidence: float = 0.8


class DimensionElement(BaseModel):
    dimension_id: str
    label: str
    value: str
    text: str | None = None
    bbox: BoundingBox | None = None
    start: list[float] | None = None
    end: list[float] | None = None
    text_position: list[float] | None = None
    rotation: float = 0.0
    layer: str = "DIM"
    confidence: float = 0.8


class CadPrimitive(BaseModel):
    primitive_id: str
    kind: str
    layer: str = "MAIN"
    points: list[list[float]] = Field(default_factory=list)
    closed: bool = False
    center: list[float] | None = None
    radius: float | None = None
    start_angle: float | None = None
    end_angle: float | None = None
    metadata: dict[str, Any] = Field(default_factory=dict)


class EngineeringSceneGraph(BaseModel):
    domain: DrawingDomain
    mode: JobMode
    sheet_name: str
    page_quad: list[list[float]] = Field(default_factory=list)
    objects: list[EngineeringObject] = Field(default_factory=list)
    texts: list[TextElement] = Field(default_factory=list)
    dimensions: list[DimensionElement] = Field(default_factory=list)
    primitives: list[CadPrimitive] = Field(default_factory=list)
    unresolved_relations: list[ClarificationPrompt] = Field(default_factory=list)
    confidence: float = 0.75
    notes: list[str] = Field(default_factory=list)


class CadEntityCommand(BaseModel):
    entity_type: str
    layer: str
    params: dict[str, Any] = Field(default_factory=dict)


class CadDsl(BaseModel):
    layers: list[str] = Field(default_factory=lambda: ["MAIN", "TEXT", "DIM", "ISO"])
    entities: list[CadEntityCommand] = Field(default_factory=list)
    blocks: list[dict[str, Any]] = Field(default_factory=list)


class IsoScene(BaseModel):
    preset: ViewPreset = ViewPreset.ISO_NE
    camera: dict[str, float] = Field(default_factory=dict)
    entities: list[CadEntityCommand] = Field(default_factory=list)
    assumptions: list[str] = Field(default_factory=list)


class ArtifactManifest(BaseModel):
    drawing_path: str | None = None
    dwg_path: str | None = None
    isometric_path: str | None = None
    scene_graph_path: str | None = None
    report_path: str | None = None
    diff_path: str | None = None
    source_preview_path: str | None = None
    overlay_preview_path: str | None = None


class ChatEdit(BaseModel):
    timestamp: datetime = Field(default_factory=utcnow)
    message: str
    applied: bool = False
    summary: str | None = None


class JobRecord(BaseModel):
    job_id: str
    filename: str
    source_path: str
    mode: JobMode
    domain: DrawingDomain
    output_format: OutputFormat
    status: JobStatus
    model_id: str
    provider: ProviderType
    runtime_options: ModelRuntimeOptions = Field(default_factory=ModelRuntimeOptions)
    resolved_models: dict[str, str] = Field(default_factory=dict)
    iso_view: IsoViewSettings = Field(default_factory=IsoViewSettings)
    confidence: float = 0.0
    stage: str = "queued"
    clarification: ClarificationPrompt | None = None
    scene_graph: EngineeringSceneGraph | None = None
    cad_dsl: CadDsl | None = None
    iso_scene: IsoScene | None = None
    artifacts: ArtifactManifest = Field(default_factory=ArtifactManifest)
    critic_findings: list[str] = Field(default_factory=list)
    chat_history: list[ChatEdit] = Field(default_factory=list)
    created_at: datetime = Field(default_factory=utcnow)
    updated_at: datetime = Field(default_factory=utcnow)
    error: str | None = None


class CreateJobPayload(BaseModel):
    mode: JobMode
    domain: DrawingDomain = DrawingDomain.AUTO
    output_format: OutputFormat = OutputFormat.DXF
    model_id: str
    provider: ProviderType
    runtime_options: ModelRuntimeOptions = Field(default_factory=ModelRuntimeOptions)
    iso_view: IsoViewSettings = Field(default_factory=IsoViewSettings)


class ClarificationResponsePayload(BaseModel):
    option_id: str
    note: str | None = None


class ChatEditPayload(BaseModel):
    message: str


class ViewPatchPayload(BaseModel):
    iso_view: IsoViewSettings
