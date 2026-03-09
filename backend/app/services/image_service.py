from __future__ import annotations

from dataclasses import dataclass
from pathlib import Path

import fitz
from PIL import Image, ImageDraw, ImageFont, ImageOps

from app.schemas.models import CadDsl, EngineeringSceneGraph


@dataclass(slots=True)
class ImageTile:
    path: Path
    origin_x: int
    origin_y: int
    width: int
    height: int
    safe_left: int
    safe_top: int
    safe_right: int
    safe_bottom: int


class ImageService:
    def __init__(self, *, max_side: int = 2048) -> None:
        self.max_side = max_side

    def normalize_source(self, source_path: Path, artifact_dir: Path) -> Path:
        suffix = source_path.suffix.lower()
        preview_path = artifact_dir / "source-preview.png"

        if suffix == ".pdf":
            doc = fitz.open(source_path)
            try:
                page = doc.load_page(0)
                pix = page.get_pixmap(matrix=fitz.Matrix(2, 2), alpha=False)
                pix.save(preview_path)
            finally:
                doc.close()
            return self._normalize_png(preview_path)

        image = Image.open(source_path)
        image = ImageOps.exif_transpose(image).convert("RGB")
        image.thumbnail((self.max_side, self.max_side))
        image.save(preview_path, format="PNG")
        return preview_path

    def draw_overlay(self, preview_path: Path, scene_graph: EngineeringSceneGraph, artifact_dir: Path) -> tuple[Path, Path]:
        source = Image.open(preview_path).convert("RGB")
        overlay = source.copy()
        draw = ImageDraw.Draw(overlay)
        font = ImageFont.load_default()

        for obj in scene_graph.objects:
            if not obj.bbox:
                continue
            bbox = obj.bbox
            rect = [bbox.x, bbox.y, bbox.x + bbox.width, bbox.y + bbox.height]
            draw.rectangle(rect, outline="#00ffd5", width=3)
            draw.text((bbox.x + 4, max(0, bbox.y - 14)), f"{obj.kind}: {obj.label}", fill="#fff59d", font=font)

        for text in scene_graph.texts:
            if text.bbox:
                draw.rectangle(
                    [text.bbox.x, text.bbox.y, text.bbox.x + text.bbox.width, text.bbox.y + text.bbox.height],
                    outline="#ffb86c",
                    width=2,
                )
            if text.bbox:
                draw.text((text.bbox.x, text.bbox.y), text.content, fill="#ffb86c", font=font)

        for dim in scene_graph.dimensions:
            if dim.bbox:
                draw.rectangle(
                    [dim.bbox.x, dim.bbox.y, dim.bbox.x + dim.bbox.width, dim.bbox.y + dim.bbox.height],
                    outline="#ff79c6",
                    width=2,
                )
                draw.text((dim.bbox.x, max(0, dim.bbox.y - 12)), f"{dim.label}={dim.value}", fill="#ff79c6", font=font)

        overlay_path = artifact_dir / "overlay-preview.png"
        overlay.save(overlay_path, format="PNG")

        diff = Image.new("RGB", (source.width * 2, source.height + 60), "#091319")
        diff.paste(source, (0, 60))
        diff.paste(overlay, (source.width, 60))
        diff_draw = ImageDraw.Draw(diff)
        diff_draw.text((20, 18), "Source Preview", fill="#edf4f3", font=font)
        diff_draw.text((source.width + 20, 18), "Scene Overlay", fill="#edf4f3", font=font)
        diff_path = artifact_dir / "diff.png"
        diff.save(diff_path, format="PNG")
        return overlay_path, diff_path

    def render_cad_preview(self, preview_path: Path, cad_dsl: CadDsl, artifact_dir: Path) -> tuple[Path, Path]:
        source = Image.open(preview_path).convert("RGB")
        render = Image.new("RGB", source.size, "white")
        draw = ImageDraw.Draw(render)
        font = ImageFont.load_default()

        for entity in cad_dsl.entities:
            params = entity.params
            kind = entity.entity_type.lower()
            if kind == "line":
                draw.line([tuple(params["start"]), tuple(params["end"])], fill="black", width=1)
                continue

            if kind == "circle":
                center = params["center"]
                radius = params["radius"]
                draw.ellipse(
                    [
                        center[0] - radius,
                        center[1] - radius,
                        center[0] + radius,
                        center[1] + radius,
                    ],
                    outline="black",
                    width=1,
                )
                continue

            if kind == "lwpolyline":
                points = [tuple(point) for point in params.get("points", [])]
                if len(points) >= 2:
                    if params.get("closed"):
                        points = points + [points[0]]
                    draw.line(points, fill="black", width=1)
                continue

            if kind == "arc":
                center = params["center"]
                radius = params["radius"]
                draw.arc(
                    [
                        center[0] - radius,
                        center[1] - radius,
                        center[0] + radius,
                        center[1] + radius,
                    ],
                    start=params.get("start_angle", 0.0),
                    end=params.get("end_angle", 0.0),
                    fill="black",
                    width=1,
                )
                continue

            if kind in {"text", "mtext"}:
                draw.text(tuple(params.get("insert", [0, 0])), params.get("text", ""), fill="black", font=font)

        overlay_path = artifact_dir / "overlay-preview.png"
        render.save(overlay_path, format="PNG")

        diff = Image.new("RGB", (source.width * 2, source.height + 60), "#091319")
        diff.paste(source, (0, 60))
        diff.paste(render, (source.width, 60))
        diff_draw = ImageDraw.Draw(diff)
        diff_draw.text((20, 18), "Source Preview", fill="#edf4f3", font=font)
        diff_draw.text((source.width + 20, 18), "Vector Render", fill="#edf4f3", font=font)
        diff_path = artifact_dir / "diff.png"
        diff.save(diff_path, format="PNG")
        return overlay_path, diff_path

    def split_into_tiles(
        self,
        preview_path: Path,
        artifact_dir: Path,
        *,
        cols: int = 2,
        rows: int = 2,
        overlap: int = 160,
        name_prefix: str = "tile",
    ) -> list[ImageTile]:
        source = Image.open(preview_path).convert("RGB")
        width, height = source.size
        tiles_dir = artifact_dir / "tiles"
        tiles_dir.mkdir(parents=True, exist_ok=True)

        tile_width = (width + cols - 1) // cols
        tile_height = (height + rows - 1) // rows
        tiles: list[ImageTile] = []

        for row in range(rows):
            for col in range(cols):
                safe_left = col * tile_width
                safe_top = row * tile_height
                safe_right = min(width, (col + 1) * tile_width)
                safe_bottom = min(height, (row + 1) * tile_height)

                left = max(0, safe_left - overlap)
                top = max(0, safe_top - overlap)
                right = min(width, safe_right + overlap)
                bottom = min(height, safe_bottom + overlap)

                crop = source.crop((left, top, right, bottom))
                tile_path = tiles_dir / f"{name_prefix}-r{row}-c{col}.png"
                crop.save(tile_path, format="PNG")
                tiles.append(
                    ImageTile(
                        path=tile_path,
                        origin_x=left,
                        origin_y=top,
                        width=right - left,
                        height=bottom - top,
                        safe_left=safe_left,
                        safe_top=safe_top,
                        safe_right=safe_right,
                        safe_bottom=safe_bottom,
                    )
                )
        return tiles

    def _normalize_png(self, image_path: Path) -> Path:
        image = Image.open(image_path).convert("RGB")
        image.thumbnail((self.max_side, self.max_side))
        image.save(image_path, format="PNG")
        return image_path
