from __future__ import annotations

from typing import Any

from app.schemas.models import (
    BoundingBox,
    CadPrimitive,
    ClarificationOption,
    ClarificationPrompt,
    DimensionElement,
    DrawingDomain,
    EngineeringObject,
    EngineeringSceneGraph,
    JobMode,
    TextElement,
)

GENERIC_OBJECT_KINDS = {"object", "item", "entity", "label", "text"}


def normalize_scene_graph_payload(payload: dict[str, Any]) -> EngineeringSceneGraph:
    domain = _map_domain(payload.get("domain"))
    mode = _map_mode(payload.get("mode"))
    sheet_name = str(payload.get("sheet_name") or "Sheet1")
    page_quad = _normalize_page_quad(payload.get("page_quad"))

    objects = []
    for index, item in enumerate(_list(payload.get("objects")), start=1):
        normalized = _normalize_object(item, index)
        if normalized is not None:
            objects.append(normalized)

    texts = []
    for index, item in enumerate(_list(payload.get("texts")), start=1):
        normalized = _normalize_text(item, index)
        if normalized is not None:
            texts.append(normalized)

    dimensions = []
    for index, item in enumerate(_list(payload.get("dimensions")), start=1):
        normalized = _normalize_dimension(item, index)
        if normalized is not None:
            dimensions.append(normalized)

    primitives = []
    for index, item in enumerate(_list(payload.get("primitives")), start=1):
        normalized = _normalize_primitive(item, index)
        if normalized is not None:
            primitives.append(normalized)

    unresolved = [_normalize_clarification(item, index) for index, item in enumerate(_list(payload.get("unresolved_relations")), start=1)]
    confidence = _as_confidence(payload.get("confidence"), default=0.75)
    notes_raw = payload.get("notes")
    if isinstance(notes_raw, str):
        notes = [notes_raw]
    elif isinstance(notes_raw, list):
        notes = [str(item) for item in notes_raw if str(item).strip()]
    else:
        notes = []

    return EngineeringSceneGraph(
        domain=domain,
        mode=mode,
        sheet_name=sheet_name,
        page_quad=page_quad,
        objects=objects,
        texts=texts,
        dimensions=dimensions,
        primitives=primitives,
        unresolved_relations=unresolved,
        confidence=confidence,
        notes=notes,
    )


def _map_domain(value: Any) -> DrawingDomain:
    text = str(value or "").strip().lower()
    if "pipe" in text or "piping" in text or "process" in text:
        return DrawingDomain.PIPING
    if "vessel" in text or "tank" in text or "емк" in text or "сосуд" in text:
        return DrawingDomain.VESSELS
    if "part" in text or "detail" in text or "mechanical" in text:
        return DrawingDomain.PARTS
    if text == "auto":
        return DrawingDomain.AUTO
    return DrawingDomain.GENERAL


def _map_mode(value: Any) -> JobMode:
    text = str(value or "").strip().lower()
    if "iso" in text:
        return JobMode.ISOMETRY
    return JobMode.COPY


def _normalize_page_quad(value: Any) -> list[list[float]]:
    if isinstance(value, dict):
        x = _as_float(value.get("x"), 0.0)
        y = _as_float(value.get("y"), 0.0)
        width = _as_float(value.get("width"), 1000.0)
        height = _as_float(value.get("height"), 700.0)
        return [[x, y], [x + width, y], [x + width, y + height], [x, y + height]]
    if isinstance(value, list):
        quad: list[list[float]] = []
        for item in value:
            point = _normalize_point(item)
            if point is not None:
                quad.append(point)
        return quad[:4]
    return []


def _normalize_object(value: Any, index: int) -> EngineeringObject | None:
    data = value if isinstance(value, dict) else {}
    label = str(data.get("label") or data.get("name") or data.get("kind") or "").strip()
    kind = str(data.get("kind") or data.get("type") or "object").strip()
    bbox = _normalize_bbox(data.get("bbox") or _bbox_from_points(data.get("points")))
    connections = [str(item) for item in _list(data.get("connections")) if str(item).strip()]
    attributes = data.get("attributes") if isinstance(data.get("attributes"), dict) else {}

    if bbox is None:
        return None
    if not label:
        label = kind
    if not label:
        return None
    if kind.lower() in GENERIC_OBJECT_KINDS and (label.lower().startswith("object ") or label.lower() == kind.lower()):
        return None

    return EngineeringObject(
        object_id=str(data.get("object_id") or f"obj-{index}"),
        kind=kind,
        label=label,
        bbox=bbox,
        layer=str(data.get("layer") or "MAIN"),
        confidence=_as_confidence(data.get("confidence"), default=0.8),
        attributes=attributes,
        connections=connections,
    )


def _normalize_text(value: Any, index: int) -> TextElement | None:
    data = value if isinstance(value, dict) else {}
    content = str(data.get("content") or data.get("text") or data.get("label") or "").strip()
    if not content:
        return None
    bbox = _normalize_bbox(data.get("bbox"))
    insert = _normalize_point(data.get("insert") or data.get("position") or data.get("text_position"))
    if insert is None and bbox is not None:
        insert = [bbox.x, bbox.y + bbox.height]
    if bbox is None and insert is None:
        return None
    height = _as_float(data.get("height"), bbox.height if bbox else 8.0)
    return TextElement(
        text_id=str(data.get("text_id") or f"text-{index}"),
        content=content,
        bbox=bbox,
        insert=insert,
        height=max(1.0, height),
        rotation=_as_float(data.get("rotation"), 0.0),
        style=str(data.get("style") or "STANDARD"),
        confidence=_as_confidence(data.get("confidence"), default=0.8),
    )


def _normalize_dimension(value: Any, index: int) -> DimensionElement | None:
    data = value if isinstance(value, dict) else {}
    label = str(data.get("label") or "").strip()
    value_text = str(data.get("value") or data.get("measurement") or "").strip()
    text = str(data.get("text") or data.get("content") or "").strip()
    bbox = _normalize_bbox(data.get("bbox"))
    start = _normalize_point(data.get("start") or data.get("p1"))
    end = _normalize_point(data.get("end") or data.get("p2"))
    text_position = _normalize_point(data.get("text_position") or data.get("insert"))
    if not text and label and value_text:
        text = f"{label} {value_text}".strip()
    if not value_text and text:
        value_text = text
    if not label and text:
        label = text
    if not text and not value_text:
        return None
    if bbox is None and start and end:
        bbox = _bbox_from_points([start, end, text_position] if text_position else [start, end])
    if bbox is None:
        return None
    return DimensionElement(
        dimension_id=str(data.get("dimension_id") or f"dim-{index}"),
        label=label or f"D{index}",
        value=value_text or text,
        text=text or value_text,
        bbox=bbox,
        start=start,
        end=end,
        text_position=text_position,
        rotation=_as_float(data.get("rotation"), 0.0),
        layer=str(data.get("layer") or "DIM"),
        confidence=_as_confidence(data.get("confidence"), default=0.8),
    )


def _normalize_primitive(value: Any, index: int) -> CadPrimitive | None:
    data = value if isinstance(value, dict) else {}
    kind = str(data.get("kind") or data.get("entity_type") or "line").strip().lower()
    points = _normalize_points(data.get("points") or data.get("vertices"))
    start = _normalize_point(data.get("start"))
    end = _normalize_point(data.get("end"))
    if start is None and all(key in data for key in ("x1", "y1", "x2", "y2")):
        start = [_as_float(data.get("x1"), 0.0), _as_float(data.get("y1"), 0.0)]
        end = [_as_float(data.get("x2"), 0.0), _as_float(data.get("y2"), 0.0)]
    if start is not None and end is not None:
        points = [start, end]

    center = _normalize_point(data.get("center"))
    radius = _positive_or_none(data.get("radius"))
    start_angle = _float_or_none(data.get("start_angle"))
    end_angle = _float_or_none(data.get("end_angle"))

    if kind == "line" and len(points) < 2 and center and radius:
        kind = "arc" if start_angle is not None and end_angle is not None else "circle"

    normalized_kind = kind if kind in {"line", "polyline", "lwpolyline", "circle", "arc"} else "line"

    if normalized_kind == "line":
        if len(points) < 2:
            return None
        points = points[:2]
    elif normalized_kind in {"polyline", "lwpolyline"}:
        if len(points) < 2:
            return None
    elif normalized_kind == "circle":
        if center is None or radius is None:
            return None
    elif normalized_kind == "arc":
        if center is None or radius is None:
            return None
        if start_angle is None or end_angle is None:
            return None

    return CadPrimitive(
        primitive_id=str(data.get("primitive_id") or f"prim-{index}"),
        kind=normalized_kind,
        layer=str(data.get("layer") or "MAIN"),
        points=points,
        closed=bool(data.get("closed", False)),
        center=center,
        radius=radius,
        start_angle=start_angle,
        end_angle=end_angle,
        metadata=data.get("metadata") if isinstance(data.get("metadata"), dict) else {},
    )


def _normalize_clarification(value: Any, index: int) -> ClarificationPrompt:
    data = value if isinstance(value, dict) else {}
    options = [
        ClarificationOption(
            id=str(item.get("id") or f"opt-{option_index}"),
            label=str(item.get("label") or f"Option {option_index}"),
            description=str(item.get("description")) if item.get("description") is not None else None,
        )
        for option_index, item in enumerate(_list(data.get("options")), start=1)
        if isinstance(item, dict)
    ]
    return ClarificationPrompt(
        prompt_id=str(data.get("prompt_id") or f"clarify-{index}"),
        question=str(data.get("question") or "Please clarify the ambiguous object."),
        options=options,
        related_object_ids=[str(item) for item in _list(data.get("related_object_ids"))],
    )


def _normalize_bbox(value: Any) -> BoundingBox | None:
    if not isinstance(value, dict):
        return None
    width = _as_float(value.get("width"), 0.0)
    height = _as_float(value.get("height"), 0.0)
    if width <= 0 or height <= 0:
        return None
    return BoundingBox(
        x=_as_float(value.get("x"), 0.0),
        y=_as_float(value.get("y"), 0.0),
        width=width,
        height=height,
    )


def _normalize_points(value: Any) -> list[list[float]]:
    points: list[list[float]] = []
    if not isinstance(value, list):
        return points
    for item in value:
        point = _normalize_point(item)
        if point is not None:
            points.append(point)
    return points


def _normalize_point(value: Any) -> list[float] | None:
    if isinstance(value, dict):
        if "x" in value and "y" in value:
            return [_as_float(value.get("x"), 0.0), _as_float(value.get("y"), 0.0)]
        return None
    if isinstance(value, list) and len(value) >= 2:
        return [_as_float(value[0], 0.0), _as_float(value[1], 0.0)]
    if isinstance(value, tuple) and len(value) >= 2:
        return [_as_float(value[0], 0.0), _as_float(value[1], 0.0)]
    return None


def _bbox_from_points(value: Any) -> BoundingBox | None:
    points = _normalize_points(value)
    if len(points) < 2:
        return None
    xs = [point[0] for point in points]
    ys = [point[1] for point in points]
    width = max(xs) - min(xs)
    height = max(ys) - min(ys)
    if width <= 0 or height <= 0:
        return None
    return BoundingBox(x=min(xs), y=min(ys), width=width, height=height)


def _list(value: Any) -> list[Any]:
    return value if isinstance(value, list) else []


def _as_confidence(value: Any, *, default: float) -> float:
    number = _as_float(value, default)
    return min(1.0, max(0.0, number))


def _as_float(value: Any, default: float) -> float:
    try:
        return float(value)
    except Exception:
        return default


def _float_or_none(value: Any) -> float | None:
    try:
        return float(value)
    except Exception:
        return None


def _positive_or_none(value: Any) -> float | None:
    number = _float_or_none(value)
    if number is None or number <= 0:
        return None
    return number
