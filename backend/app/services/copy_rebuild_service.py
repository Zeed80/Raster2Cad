from __future__ import annotations

from pathlib import Path

from PIL import Image

from app.schemas.models import BoundingBox, CadDsl, CadEntityCommand, CadPrimitive, DimensionElement, DrawingDomain, EngineeringObject, EngineeringSceneGraph, JobRecord, TextElement
from app.services.image_service import ImageService, ImageTile
from app.services.providers.base import BaseModelProvider
from app.services.scene_graph_contract import copy_annotation_schema, copy_geometry_schema, copy_overview_schema, copy_system_prompt


class CopyRebuildService:
    def __init__(self, image_service: ImageService) -> None:
        self.image_service = image_service

    async def parse_clean_copy(
        self,
        *,
        job: JobRecord,
        provider: BaseModelProvider,
        model_id: str,
        preview_path: Path,
        artifact_dir: Path,
    ) -> EngineeringSceneGraph:
        width, height = self._image_size(preview_path)
        if job.domain == DrawingDomain.AUTO:
            overview = await provider.parse_drawing(
                model_id=model_id,
                source_path=preview_path,
                prompt=self._build_overview_prompt(job, width=width, height=height),
                system_prompt=copy_system_prompt(),
                response_schema=copy_overview_schema(),
                temperature=0.0,
                runtime_options=job.runtime_options,
            )
            if overview is None:
                overview = self._fallback_overview(job, width=width, height=height, model_id=model_id)
        else:
            overview = self._fallback_overview(job, width=width, height=height, model_id=model_id, skipped=True)

        overview.mode = job.mode
        overview.sheet_name = job.filename
        overview.page_quad = [[0, 0], [width, 0], [width, height], [0, height]]
        if job.domain != DrawingDomain.AUTO:
            overview.domain = job.domain

        geometry_tiles = self.image_service.split_into_tiles(
            preview_path,
            artifact_dir,
            cols=2,
            rows=2,
            overlap=192,
            name_prefix="geometry",
        )
        detail_tiles = self.image_service.split_into_tiles(
            preview_path,
            artifact_dir,
            cols=2,
            rows=2,
            overlap=128,
            name_prefix="detail",
        )

        geometry_graphs = await self._parse_tiles(
            provider=provider,
            model_id=model_id,
            artifact_dir=artifact_dir,
            pass_name="geometry",
            tiles=geometry_tiles,
            source_builder=lambda tile: self._build_geometry_tile_prompt(
                job,
                tile=tile,
                page_width=width,
                page_height=height,
                resolved_domain=overview.domain,
            ),
            response_schema=copy_geometry_schema(),
            runtime_options=job.runtime_options,
        )
        merged = self._merge_graphs(base=overview, overlays=geometry_graphs, width=width, height=height)

        if len(merged.primitives) < 18:
            recovery_geometry = await self._parse_tiles(
                provider=provider,
                model_id=model_id,
                artifact_dir=artifact_dir,
                pass_name="geometry-recovery",
                tiles=detail_tiles,
                source_builder=lambda tile: self._build_geometry_recovery_prompt(
                    job,
                    tile=tile,
                    page_width=width,
                    page_height=height,
                    resolved_domain=overview.domain,
                ),
                response_schema=copy_geometry_schema(),
                runtime_options=job.runtime_options,
            )
            if recovery_geometry:
                merged = self._merge_graphs(base=merged, overlays=recovery_geometry, width=width, height=height)
                merged.notes.append(
                    f"Geometry recovery pass added detail tiles because primitive count was low; primitives={len(merged.primitives)}."
                )

        annotation_graphs = await self._parse_tiles(
            provider=provider,
            model_id=model_id,
            artifact_dir=artifact_dir,
            pass_name="annotation",
            tiles=detail_tiles,
            source_builder=lambda tile: self._build_annotation_tile_prompt(tile=tile, page_width=width, page_height=height),
            response_schema=copy_annotation_schema(),
            runtime_options=job.runtime_options,
        )
        if annotation_graphs:
            merged = self._merge_graphs(base=merged, overlays=annotation_graphs, width=width, height=height)
            merged.notes.append(
                f"Annotation pass merged {self._count_positioned_texts(merged)} positioned texts and {len(merged.dimensions)} dimensions from {len(annotation_graphs)} detail tiles."
            )

        merged.notes.append(
            f"Copy-mode clean redraw parsed with overview={1 if job.domain == DrawingDomain.AUTO else 0}, {len(geometry_graphs)} geometry tiles, and {len(annotation_graphs)} annotation tiles."
        )
        return merged

    def build_cad_dsl(self, scene_graph: EngineeringSceneGraph) -> CadDsl:
        entities: list[CadEntityCommand] = []
        layers = {"MAIN", "TEXT", "DIM", "ISO"}

        for primitive in scene_graph.primitives:
            entity = self._primitive_to_entity(primitive)
            if entity is None:
                continue
            entities.append(entity)
            layers.add(entity.layer)

        for text in scene_graph.texts:
            insert = text.insert or ([text.bbox.x, text.bbox.y + text.bbox.height] if text.bbox else None)
            if not text.content.strip() or insert is None:
                continue
            entities.append(
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
                entities.append(
                    CadEntityCommand(
                        entity_type="line",
                        layer=dimension.layer,
                        params={"start": dimension.start, "end": dimension.end},
                    )
                )
                layers.add(dimension.layer)
            insert = dimension.text_position or ([dimension.bbox.x, dimension.bbox.y] if dimension.bbox else None)
            if insert is None:
                continue
            entities.append(
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
            layers.add(dimension.layer)

        return CadDsl(layers=sorted(layers), entities=entities)

    async def _parse_tiles(
        self,
        *,
        provider: BaseModelProvider,
        model_id: str,
        artifact_dir: Path,
        pass_name: str,
        tiles: list[ImageTile],
        source_builder,
        response_schema: dict,
        runtime_options,
    ) -> list[EngineeringSceneGraph]:
        graphs: list[EngineeringSceneGraph] = []
        for tile in tiles:
            graphs.extend(
                await self._parse_tile_recursive(
                    provider=provider,
                    model_id=model_id,
                    artifact_dir=artifact_dir,
                    pass_name=pass_name,
                    tile=tile,
                    source_builder=source_builder,
                    response_schema=response_schema,
                    runtime_options=runtime_options,
                    depth=0,
                )
            )
        return graphs

    async def _parse_tile_recursive(
        self,
        *,
        provider: BaseModelProvider,
        model_id: str,
        artifact_dir: Path,
        pass_name: str,
        tile: ImageTile,
        source_builder,
        response_schema: dict,
        runtime_options,
        depth: int,
    ) -> list[EngineeringSceneGraph]:
        parsed_tile = await provider.parse_drawing(
            model_id=model_id,
            source_path=tile.path,
            prompt=source_builder(tile),
            system_prompt=copy_system_prompt(),
            response_schema=response_schema,
            temperature=0.0,
            runtime_options=runtime_options,
        )
        if parsed_tile is not None:
            return [self._normalize_tile_coordinates(parsed_tile, tile=tile)]
        if depth >= 1 or min(tile.width, tile.height) < 420:
            return []
        graphs: list[EngineeringSceneGraph] = []
        for subtile in self._subdivide_tile(tile, artifact_dir=artifact_dir, name_prefix=f"{pass_name}-retry-{depth + 1}"):
            graphs.extend(
                await self._parse_tile_recursive(
                    provider=provider,
                    model_id=model_id,
                    artifact_dir=artifact_dir,
                    pass_name=pass_name,
                    tile=subtile,
                    source_builder=source_builder,
                    response_schema=response_schema,
                    runtime_options=runtime_options,
                    depth=depth + 1,
                )
            )
        return graphs

    def _build_overview_prompt(self, job: JobRecord, *, width: int, height: int) -> str:
        return (
            "Analyze the full engineering drawing and return a COPY-mode overview. "
            f"The full image size is width={width}, height={height}, origin is top-left. "
            f"Set mode={job.mode.value}. Respect the user domain hint {job.domain.value}. "
            "Return only physical engineering objects and pipe runs in objects. "
            "Every object must have a real bbox; omit any object that cannot be located. "
            "Do not use objects for title text, legend text, weld numbers, dimension text, small numeric callouts, or free labels. "
            "For piping drawings, objects may include major pipe runs, vessels, valves, flanges, tees, reducers, supports, and endpoint connections. "
            "If the domain is ambiguous, use unresolved_relations with one short clarification question and 2 to 4 options. "
            "Do not return texts, dimensions, or primitives in this overview pass."
        )

    def _build_geometry_tile_prompt(
        self,
        job: JobRecord,
        *,
        tile: ImageTile,
        page_width: int,
        page_height: int,
        resolved_domain: DrawingDomain,
    ) -> str:
        return (
            "Analyze only the attached crop and return clean geometry for COPY mode. "
            f"Full page size is width={page_width}, height={page_height}. "
            f"This crop origin in full-page coordinates is x={tile.origin_x}, y={tile.origin_y}, crop size is width={tile.width}, height={tile.height}. "
            f"Only include entities whose anchor lies inside the safe full-page rectangle x={tile.safe_left}..{tile.safe_right}, y={tile.safe_top}..{tile.safe_bottom}. "
            "All returned coordinates must be absolute full-page coordinates. "
            f"Use domain {resolved_domain.value}. "
            "Return only objects and primitives. texts=[], dimensions=[], unresolved_relations=[] by omission. "
            "Every primitive must be an ideal line, polyline, circle, or arc with complete coordinates. "
            "Use one long line for a straight pipe segment instead of many short fragments. "
            "Preserve visible symbol outlines like valves, flanges, circles, leader lines, arrow shafts, legend sample strokes, and frames when they appear in the crop. "
            "Do not return loose text as objects. Do not return empty primitives."
        )

    def _build_geometry_recovery_prompt(
        self,
        job: JobRecord,
        *,
        tile: ImageTile,
        page_width: int,
        page_height: int,
        resolved_domain: DrawingDomain,
    ) -> str:
        return (
            "Re-run the crop with aggressive geometry extraction for COPY mode. "
            f"Full page size is width={page_width}, height={page_height}. "
            f"Crop origin is x={tile.origin_x}, y={tile.origin_y}, crop size is width={tile.width}, height={tile.height}. "
            f"Only emit entities anchored inside safe full-page rectangle x={tile.safe_left}..{tile.safe_right}, y={tile.safe_top}..{tile.safe_bottom}. "
            "All coordinates must be absolute full-page coordinates. "
            f"Use domain {resolved_domain.value}. "
            "Focus on missing centerlines, vertical risers, horizontal runs, bends, branch tees, vessel outlines, flange circles, valve outlines, leader lines, and legend geometry. "
            "Do not emit text. Do not emit placeholders. "
            "If a symbol is visible, approximate it using a small set of clean line/circle/arc primitives instead of omitting it."
        )

    def _build_annotation_tile_prompt(self, *, tile: ImageTile, page_width: int, page_height: int) -> str:
        return (
            "Analyze only the attached crop and return every readable text inscription and explicit dimension annotation for COPY mode. "
            f"Full page size is width={page_width}, height={page_height}. "
            f"Crop origin is x={tile.origin_x}, y={tile.origin_y}, crop size is width={tile.width}, height={tile.height}. "
            f"Only include annotation anchors inside safe full-page rectangle x={tile.safe_left}..{tile.safe_right}, y={tile.safe_top}..{tile.safe_bottom}. "
            "All coordinates must be absolute full-page coordinates. "
            "Return only texts and dimensions. Do not return objects or primitives. "
            "Texts must preserve visible content verbatim, including Cyrillic, Latin, numbers, diameter marks, punctuation, hyphens, and section labels. "
            "Include small numeric callouts, weld identifiers, item numbers, flow labels, legend labels, title text, and endpoint notes if readable. "
            "Every text must include content, bbox, insert, height, rotation, and confidence. "
            "Use dimensions only for explicit measurement or leader annotations with visible association to geometry. "
            "Free labels and loose numbers belong to texts, not dimensions. "
            "Each dimension must include the visible text string, bbox, and confidence. "
            "If the extension line or leader endpoints are visible, also include start, end, and text_position. "
            "If unreadable, omit the annotation instead of guessing."
        )

    def _normalize_tile_coordinates(self, scene_graph: EngineeringSceneGraph, *, tile: ImageTile) -> EngineeringSceneGraph:
        if not self._looks_like_local_coordinates(scene_graph, tile=tile):
            return scene_graph
        self._translate_scene_graph(scene_graph, dx=tile.origin_x, dy=tile.origin_y)
        scene_graph.notes.append(f"Tile coordinates translated by ({tile.origin_x}, {tile.origin_y}).")
        return scene_graph

    def _looks_like_local_coordinates(self, scene_graph: EngineeringSceneGraph, *, tile: ImageTile) -> bool:
        if tile.origin_x == 0 and tile.origin_y == 0:
            return False
        max_x = 0.0
        max_y = 0.0
        for x, y in self._iter_scene_points(scene_graph):
            max_x = max(max_x, x)
            max_y = max(max_y, y)
        return max_x <= tile.width + 24 and max_y <= tile.height + 24

    def _iter_scene_points(self, scene_graph: EngineeringSceneGraph):
        for quad_point in scene_graph.page_quad:
            if len(quad_point) >= 2:
                yield quad_point[0], quad_point[1]
        for obj in scene_graph.objects:
            if obj.bbox:
                yield obj.bbox.x, obj.bbox.y
                yield obj.bbox.x + obj.bbox.width, obj.bbox.y + obj.bbox.height
        for text in scene_graph.texts:
            if text.insert:
                yield text.insert[0], text.insert[1]
            if text.bbox:
                yield text.bbox.x, text.bbox.y
                yield text.bbox.x + text.bbox.width, text.bbox.y + text.bbox.height
        for dimension in scene_graph.dimensions:
            if dimension.start:
                yield dimension.start[0], dimension.start[1]
            if dimension.end:
                yield dimension.end[0], dimension.end[1]
            if dimension.text_position:
                yield dimension.text_position[0], dimension.text_position[1]
            if dimension.bbox:
                yield dimension.bbox.x, dimension.bbox.y
                yield dimension.bbox.x + dimension.bbox.width, dimension.bbox.y + dimension.bbox.height
        for primitive in scene_graph.primitives:
            if primitive.center:
                yield primitive.center[0], primitive.center[1]
            for point in primitive.points:
                if len(point) >= 2:
                    yield point[0], point[1]

    def _translate_scene_graph(self, scene_graph: EngineeringSceneGraph, *, dx: float, dy: float) -> None:
        scene_graph.page_quad = [[point[0] + dx, point[1] + dy] for point in scene_graph.page_quad if len(point) >= 2]
        for obj in scene_graph.objects:
            if obj.bbox:
                obj.bbox = self._translate_bbox(obj.bbox, dx=dx, dy=dy)
        for text in scene_graph.texts:
            if text.bbox:
                text.bbox = self._translate_bbox(text.bbox, dx=dx, dy=dy)
            if text.insert:
                text.insert = [text.insert[0] + dx, text.insert[1] + dy]
        for dimension in scene_graph.dimensions:
            if dimension.bbox:
                dimension.bbox = self._translate_bbox(dimension.bbox, dx=dx, dy=dy)
            if dimension.start:
                dimension.start = [dimension.start[0] + dx, dimension.start[1] + dy]
            if dimension.end:
                dimension.end = [dimension.end[0] + dx, dimension.end[1] + dy]
            if dimension.text_position:
                dimension.text_position = [dimension.text_position[0] + dx, dimension.text_position[1] + dy]
        for primitive in scene_graph.primitives:
            if primitive.center:
                primitive.center = [primitive.center[0] + dx, primitive.center[1] + dy]
            if primitive.points:
                primitive.points = [[point[0] + dx, point[1] + dy] for point in primitive.points]

    def _translate_bbox(self, bbox: BoundingBox, *, dx: float, dy: float) -> BoundingBox:
        return BoundingBox(x=bbox.x + dx, y=bbox.y + dy, width=bbox.width, height=bbox.height)

    def _merge_graphs(
        self,
        *,
        base: EngineeringSceneGraph,
        overlays: list[EngineeringSceneGraph],
        width: int,
        height: int,
    ) -> EngineeringSceneGraph:
        merged = EngineeringSceneGraph(
            domain=base.domain,
            mode=base.mode,
            sheet_name=base.sheet_name,
            page_quad=[[0, 0], [width, 0], [width, height], [0, height]],
            objects=[],
            texts=[],
            dimensions=[],
            primitives=[],
            unresolved_relations=base.unresolved_relations,
            confidence=base.confidence,
            notes=[],
        )

        object_map: dict[tuple, EngineeringObject] = {}
        text_map: dict[tuple, TextElement] = {}
        dimension_map: dict[tuple, DimensionElement] = {}
        primitive_map: dict[tuple, CadPrimitive] = {}

        for graph in [base, *overlays]:
            for note in graph.notes:
                if note not in merged.notes:
                    merged.notes.append(note)
            for obj in graph.objects:
                signature = self._object_signature(obj)
                current = object_map.get(signature)
                if current is None or self._object_score(obj) > self._object_score(current):
                    object_map[signature] = obj
            for text in graph.texts:
                signature = self._text_signature(text)
                current = text_map.get(signature)
                if current is None or self._text_score(text) > self._text_score(current):
                    text_map[signature] = text
            for dimension in graph.dimensions:
                signature = self._dimension_signature(dimension)
                current = dimension_map.get(signature)
                if current is None or self._dimension_score(dimension) > self._dimension_score(current):
                    dimension_map[signature] = dimension
            for primitive in graph.primitives:
                signature = self._primitive_signature(primitive)
                current = primitive_map.get(signature)
                if current is None or self._primitive_score(primitive) > self._primitive_score(current):
                    primitive_map[signature] = primitive

        merged.objects = sorted(object_map.values(), key=self._object_sort_key)
        merged.texts = sorted(text_map.values(), key=self._text_sort_key)
        merged.dimensions = sorted(dimension_map.values(), key=self._dimension_sort_key)
        merged.primitives = sorted(primitive_map.values(), key=self._primitive_sort_key)

        if overlays:
            confidence_values = [base.confidence, *[graph.confidence for graph in overlays]]
            merged.confidence = sum(confidence_values) / len(confidence_values)
        return merged

    def _object_signature(self, obj: EngineeringObject) -> tuple:
        return (
            obj.kind.lower(),
            obj.label.lower(),
            round(obj.bbox.x / 24) if obj.bbox else -1,
            round(obj.bbox.y / 24) if obj.bbox else -1,
            round(obj.bbox.width / 24) if obj.bbox else -1,
            round(obj.bbox.height / 24) if obj.bbox else -1,
        )

    def _text_signature(self, text: TextElement) -> tuple:
        anchor = text.insert or ([text.bbox.x, text.bbox.y] if text.bbox else [0.0, 0.0])
        return (
            text.content.strip().lower(),
            round(anchor[0] / 10),
            round(anchor[1] / 10),
            round(text.rotation / 5),
        )

    def _dimension_signature(self, dimension: DimensionElement) -> tuple:
        if dimension.start and dimension.end:
            return (
                (dimension.text or "").strip().lower(),
                round(dimension.start[0] / 8),
                round(dimension.start[1] / 8),
                round(dimension.end[0] / 8),
                round(dimension.end[1] / 8),
            )
        if not dimension.bbox:
            return ((dimension.text or dimension.value).lower(), dimension.dimension_id)
        return (
            (dimension.text or dimension.value).lower(),
            round(dimension.bbox.x / 12),
            round(dimension.bbox.y / 12),
        )

    def _primitive_signature(self, primitive: CadPrimitive) -> tuple:
        kind = primitive.kind.lower()
        if kind == "line" and len(primitive.points) >= 2:
            p1 = primitive.points[0]
            p2 = primitive.points[1]
            ordered = sorted(
                [
                    (round(p1[0] / 4), round(p1[1] / 4)),
                    (round(p2[0] / 4), round(p2[1] / 4)),
                ]
            )
            return (kind, primitive.layer, *ordered[0], *ordered[1])
        if kind in {"polyline", "lwpolyline"} and primitive.points:
            xs = [point[0] for point in primitive.points]
            ys = [point[1] for point in primitive.points]
            return (
                "polyline",
                primitive.layer,
                round(min(xs) / 6),
                round(min(ys) / 6),
                round(max(xs) / 6),
                round(max(ys) / 6),
                len(primitive.points),
                primitive.closed,
            )
        if kind in {"circle", "arc"} and primitive.center and primitive.radius:
            return (
                kind,
                primitive.layer,
                round(primitive.center[0] / 4),
                round(primitive.center[1] / 4),
                round(primitive.radius / 4),
                round((primitive.start_angle or 0.0) / 5),
                round((primitive.end_angle or 0.0) / 5),
            )
        return (kind, primitive.layer, primitive.primitive_id)

    def _object_score(self, obj: EngineeringObject) -> float:
        area = obj.bbox.width * obj.bbox.height if obj.bbox else 0.0
        return obj.confidence * 10 + min(area / 5000.0, 6.0) + len(obj.attributes) + len(obj.connections)

    def _text_score(self, text: TextElement) -> float:
        return (
            text.confidence * 10
            + len(text.content.strip()) / 8
            + (2 if text.insert else 0)
            + (2 if text.bbox else 0)
        )

    def _dimension_score(self, dimension: DimensionElement) -> float:
        return (
            dimension.confidence * 10
            + len((dimension.text or "").strip()) / 8
            + (3 if dimension.start and dimension.end else 0)
            + (2 if dimension.text_position else 0)
            + (2 if dimension.bbox else 0)
        )

    def _primitive_score(self, primitive: CadPrimitive) -> float:
        kind = primitive.kind.lower()
        if kind == "line":
            return 3.0
        if kind in {"polyline", "lwpolyline"}:
            return 3.0 + len(primitive.points)
        if kind == "circle":
            return 4.0
        if kind == "arc":
            return 5.0
        return 0.0

    def _object_sort_key(self, obj: EngineeringObject) -> tuple:
        if obj.bbox:
            return (round(obj.bbox.y), round(obj.bbox.x), obj.kind.lower(), obj.label.lower())
        return (0, 0, obj.kind.lower(), obj.label.lower())

    def _text_sort_key(self, text: TextElement) -> tuple:
        anchor = text.insert or ([text.bbox.x, text.bbox.y] if text.bbox else [0.0, 0.0])
        return (round(anchor[1]), round(anchor[0]), text.content.lower())

    def _dimension_sort_key(self, dimension: DimensionElement) -> tuple:
        anchor = dimension.text_position or dimension.start or ([dimension.bbox.x, dimension.bbox.y] if dimension.bbox else [0.0, 0.0])
        return (round(anchor[1]), round(anchor[0]), (dimension.text or dimension.value).lower())

    def _primitive_sort_key(self, primitive: CadPrimitive) -> tuple:
        if primitive.points:
            return (primitive.layer, primitive.kind, round(primitive.points[0][1]), round(primitive.points[0][0]))
        if primitive.center:
            return (primitive.layer, primitive.kind, round(primitive.center[1]), round(primitive.center[0]))
        return (primitive.layer, primitive.kind, 0, 0)

    def _primitive_to_entity(self, primitive: CadPrimitive) -> CadEntityCommand | None:
        kind = primitive.kind.lower()
        if kind == "line" and len(primitive.points) >= 2:
            return CadEntityCommand(
                entity_type="line",
                layer=primitive.layer,
                params={"start": primitive.points[0], "end": primitive.points[1]},
            )
        if kind in {"polyline", "lwpolyline"} and len(primitive.points) >= 2:
            return CadEntityCommand(
                entity_type="lwpolyline",
                layer=primitive.layer,
                params={"points": primitive.points, "closed": primitive.closed},
            )
        if kind == "circle" and primitive.center and primitive.radius:
            return CadEntityCommand(
                entity_type="circle",
                layer=primitive.layer,
                params={"center": primitive.center, "radius": primitive.radius},
            )
        if kind == "arc" and primitive.center and primitive.radius is not None:
            return CadEntityCommand(
                entity_type="arc",
                layer=primitive.layer,
                params={
                    "center": primitive.center,
                    "radius": primitive.radius,
                    "start_angle": primitive.start_angle or 0.0,
                    "end_angle": primitive.end_angle or 0.0,
                },
            )
        return None

    def _image_size(self, preview_path: Path) -> tuple[int, int]:
        with Image.open(preview_path) as image:
            return image.size

    def _count_positioned_texts(self, scene_graph: EngineeringSceneGraph) -> int:
        return sum(1 for text in scene_graph.texts if text.content.strip() and (text.insert is not None or text.bbox is not None))

    def _subdivide_tile(self, tile: ImageTile, *, artifact_dir: Path, name_prefix: str) -> list[ImageTile]:
        tiles_dir = artifact_dir / "tiles"
        tiles_dir.mkdir(parents=True, exist_ok=True)
        with Image.open(tile.path).convert("RGB") as source:
            width, height = source.size
            cols = 2
            rows = 2
            overlap = 48
            tile_width = (width + cols - 1) // cols
            tile_height = (height + rows - 1) // rows
            subtiles: list[ImageTile] = []
            for row in range(rows):
                for col in range(cols):
                    local_safe_left = col * tile_width
                    local_safe_top = row * tile_height
                    local_safe_right = min(width, (col + 1) * tile_width)
                    local_safe_bottom = min(height, (row + 1) * tile_height)

                    left = max(0, local_safe_left - overlap)
                    top = max(0, local_safe_top - overlap)
                    right = min(width, local_safe_right + overlap)
                    bottom = min(height, local_safe_bottom + overlap)

                    crop = source.crop((left, top, right, bottom))
                    tile_path = tiles_dir / f"{name_prefix}-{tile.path.stem}-r{row}-c{col}.png"
                    crop.save(tile_path, format="PNG")
                    subtiles.append(
                        ImageTile(
                            path=tile_path,
                            origin_x=tile.origin_x + left,
                            origin_y=tile.origin_y + top,
                            width=right - left,
                            height=bottom - top,
                            safe_left=tile.origin_x + local_safe_left,
                            safe_top=tile.origin_y + local_safe_top,
                            safe_right=tile.origin_x + local_safe_right,
                            safe_bottom=tile.origin_y + local_safe_bottom,
                        )
                    )
            return subtiles

    def _fallback_overview(self, job: JobRecord, *, width: int, height: int, model_id: str, skipped: bool = False) -> EngineeringSceneGraph:
        domain = job.domain if job.domain != DrawingDomain.AUTO else DrawingDomain.GENERAL
        confidence = 0.55 if job.domain != DrawingDomain.AUTO else 0.35
        notes = []
        if skipped:
            notes.append(f"Overview pass skipped because domain was fixed to {job.domain.value}; using tile-only extraction on model {model_id}.")
        else:
            notes.append(f"Overview pass on model {model_id} returned no usable payload; continuing with tile-only extraction.")
        if job.domain == DrawingDomain.AUTO:
            notes.append("Domain was not user-fixed, so fallback overview uses general domain until tile extraction provides stronger evidence.")
        return EngineeringSceneGraph(
            domain=domain,
            mode=job.mode,
            sheet_name=job.filename,
            page_quad=[[0, 0], [width, 0], [width, height], [0, height]],
            objects=[],
            texts=[],
            dimensions=[],
            primitives=[],
            unresolved_relations=[],
            confidence=confidence,
            notes=notes,
        )
