from __future__ import annotations

from typing import Any


def copy_system_prompt() -> str:
    return (
        "You are a multimodal engineering CAD reconstruction model. "
        "Your job is to rebuild a clean editable CAD scene from a raster drawing. "
        "Return JSON only. Do not include markdown or explanations. "
        "Critical rules: "
        "1) Never use objects to store loose text or numeric callouts. "
        "2) Every object must be a physical engineering entity or a pipe run with a real bounding box. "
        "3) Every readable inscription must go to texts or dimensions, preserving visible spelling and language exactly. "
        "4) Every geometry item must be ideal CAD geometry only: line, polyline, circle, or arc. "
        "5) Never emit empty primitives. "
        "6) Use absolute full-page image coordinates in pixels. "
        "7) If an entity is unreadable or cannot be located, omit it instead of guessing. "
        "8) Prefer fewer long clean primitives over many short fragments. "
        "9) Do not invent hidden geometry outside the visible image. "
        "10) Preserve Cyrillic, Latin, numbers, symbols, diameter marks, and punctuation verbatim."
    )


def full_scene_graph_schema() -> dict[str, Any]:
    return _scene_schema(
        include_objects=True,
        include_texts=True,
        include_dimensions=True,
        include_primitives=True,
        include_unresolved=True,
    )


def copy_overview_schema() -> dict[str, Any]:
    return _scene_schema(
        include_objects=True,
        include_texts=False,
        include_dimensions=False,
        include_primitives=False,
        include_unresolved=True,
    )


def copy_geometry_schema() -> dict[str, Any]:
    return _scene_schema(
        include_objects=True,
        include_texts=False,
        include_dimensions=False,
        include_primitives=True,
        include_unresolved=False,
    )


def copy_text_schema() -> dict[str, Any]:
    return _scene_schema(
        include_objects=False,
        include_texts=True,
        include_dimensions=False,
        include_primitives=False,
        include_unresolved=False,
    )


def copy_annotation_schema() -> dict[str, Any]:
    return _scene_schema(
        include_objects=False,
        include_texts=True,
        include_dimensions=True,
        include_primitives=False,
        include_unresolved=False,
    )


def copy_dimension_schema() -> dict[str, Any]:
    return _scene_schema(
        include_objects=False,
        include_texts=False,
        include_dimensions=True,
        include_primitives=False,
        include_unresolved=False,
    )


def _scene_schema(
    *,
    include_objects: bool,
    include_texts: bool,
    include_dimensions: bool,
    include_primitives: bool,
    include_unresolved: bool,
) -> dict[str, Any]:
    properties: dict[str, Any] = {
        "domain": {
            "type": "string",
            "enum": ["auto", "piping", "vessels", "parts", "general"],
        },
        "mode": {
            "type": "string",
            "enum": ["copy", "isometry"],
        },
        "sheet_name": {"type": "string"},
        "page_quad": {
            "type": "array",
            "items": _point_schema(),
            "minItems": 0,
            "maxItems": 4,
        },
        "confidence": {"type": "number", "minimum": 0, "maximum": 1},
        "notes": {
            "type": "array",
            "items": {"type": "string"},
        },
    }
    required = ["domain", "mode", "confidence"]

    if include_objects:
        properties["objects"] = {
            "type": "array",
            "items": _object_schema(),
        }
        required.append("objects")
    if include_texts:
        properties["texts"] = {
            "type": "array",
            "items": _text_schema(),
        }
        required.append("texts")
    if include_dimensions:
        properties["dimensions"] = {
            "type": "array",
            "items": _dimension_schema(),
        }
        required.append("dimensions")
    if include_primitives:
        properties["primitives"] = {
            "type": "array",
            "items": _primitive_schema(),
        }
        required.append("primitives")
    if include_unresolved:
        properties["unresolved_relations"] = {
            "type": "array",
            "items": _clarification_schema(),
        }
        required.append("unresolved_relations")

    return {
        "type": "object",
        "additionalProperties": False,
        "properties": properties,
        "required": required,
    }


def _point_schema() -> dict[str, Any]:
    return {
        "type": "array",
        "items": {"type": "number"},
        "minItems": 2,
        "maxItems": 2,
    }


def _bbox_schema() -> dict[str, Any]:
    return {
        "type": "object",
        "additionalProperties": False,
        "properties": {
            "x": {"type": "number"},
            "y": {"type": "number"},
            "width": {"type": "number", "exclusiveMinimum": 0},
            "height": {"type": "number", "exclusiveMinimum": 0},
        },
        "required": ["x", "y", "width", "height"],
    }


def _object_schema() -> dict[str, Any]:
    return {
        "type": "object",
        "additionalProperties": False,
        "properties": {
            "object_id": {"type": "string", "minLength": 1},
            "kind": {"type": "string", "minLength": 2},
            "label": {"type": "string", "minLength": 1},
            "bbox": _bbox_schema(),
            "layer": {"type": "string"},
            "confidence": {"type": "number", "minimum": 0, "maximum": 1},
            "attributes": {
                "type": "object",
                "additionalProperties": {
                    "type": ["string", "number", "boolean", "null"],
                },
            },
            "connections": {
                "type": "array",
                "items": {"type": "string"},
            },
        },
        "required": [
            "object_id",
            "kind",
            "label",
            "bbox",
            "layer",
            "confidence",
            "attributes",
            "connections",
        ],
    }


def _text_schema() -> dict[str, Any]:
    return {
        "type": "object",
        "additionalProperties": False,
        "properties": {
            "text_id": {"type": "string", "minLength": 1},
            "content": {"type": "string", "minLength": 1},
            "bbox": _bbox_schema(),
            "insert": _point_schema(),
            "height": {"type": "number", "exclusiveMinimum": 0},
            "rotation": {"type": "number"},
            "style": {"type": "string"},
            "confidence": {"type": "number", "minimum": 0, "maximum": 1},
        },
        "required": ["text_id", "content", "bbox", "insert", "height", "rotation", "style", "confidence"],
    }


def _dimension_schema() -> dict[str, Any]:
    return {
        "type": "object",
        "additionalProperties": False,
        "properties": {
            "dimension_id": {"type": "string", "minLength": 1},
            "label": {"type": "string", "minLength": 1},
            "value": {"type": "string", "minLength": 1},
            "text": {"type": "string", "minLength": 1},
            "bbox": _bbox_schema(),
            "start": _point_schema(),
            "end": _point_schema(),
            "text_position": _point_schema(),
            "rotation": {"type": "number"},
            "layer": {"type": "string"},
            "confidence": {"type": "number", "minimum": 0, "maximum": 1},
        },
        "required": ["dimension_id", "label", "value", "text", "bbox", "layer", "confidence"],
    }


def _primitive_schema() -> dict[str, Any]:
    return {
        "oneOf": [
            {
                "type": "object",
                "additionalProperties": False,
                "properties": {
                    "primitive_id": {"type": "string", "minLength": 1},
                    "kind": {"type": "string", "const": "line"},
                    "layer": {"type": "string"},
                    "start": _point_schema(),
                    "end": _point_schema(),
                    "metadata": {"type": "object", "additionalProperties": True},
                },
                "required": ["primitive_id", "kind", "layer", "start", "end"],
            },
            {
                "type": "object",
                "additionalProperties": False,
                "properties": {
                    "primitive_id": {"type": "string", "minLength": 1},
                    "kind": {"type": "string", "enum": ["polyline", "lwpolyline"]},
                    "layer": {"type": "string"},
                    "points": {
                        "type": "array",
                        "items": _point_schema(),
                        "minItems": 2,
                    },
                    "closed": {"type": "boolean"},
                    "metadata": {"type": "object", "additionalProperties": True},
                },
                "required": ["primitive_id", "kind", "layer", "points", "closed"],
            },
            {
                "type": "object",
                "additionalProperties": False,
                "properties": {
                    "primitive_id": {"type": "string", "minLength": 1},
                    "kind": {"type": "string", "const": "circle"},
                    "layer": {"type": "string"},
                    "center": _point_schema(),
                    "radius": {"type": "number", "exclusiveMinimum": 0},
                    "metadata": {"type": "object", "additionalProperties": True},
                },
                "required": ["primitive_id", "kind", "layer", "center", "radius"],
            },
            {
                "type": "object",
                "additionalProperties": False,
                "properties": {
                    "primitive_id": {"type": "string", "minLength": 1},
                    "kind": {"type": "string", "const": "arc"},
                    "layer": {"type": "string"},
                    "center": _point_schema(),
                    "radius": {"type": "number", "exclusiveMinimum": 0},
                    "start_angle": {"type": "number"},
                    "end_angle": {"type": "number"},
                    "metadata": {"type": "object", "additionalProperties": True},
                },
                "required": ["primitive_id", "kind", "layer", "center", "radius", "start_angle", "end_angle"],
            },
        ]
    }


def _clarification_schema() -> dict[str, Any]:
    return {
        "type": "object",
        "additionalProperties": False,
        "properties": {
            "prompt_id": {"type": "string", "minLength": 1},
            "question": {"type": "string", "minLength": 1},
            "related_object_ids": {
                "type": "array",
                "items": {"type": "string"},
            },
            "options": {
                "type": "array",
                "items": {
                    "type": "object",
                    "additionalProperties": False,
                    "properties": {
                        "id": {"type": "string", "minLength": 1},
                        "label": {"type": "string", "minLength": 1},
                        "description": {"type": "string"},
                    },
                    "required": ["id", "label"],
                },
                "minItems": 2,
                "maxItems": 4,
            },
        },
        "required": ["prompt_id", "question", "options", "related_object_ids"],
    }
