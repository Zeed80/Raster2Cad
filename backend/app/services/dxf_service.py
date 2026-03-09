from __future__ import annotations

import json
import shutil
import subprocess
from pathlib import Path

from app.schemas.models import CadDsl, CadEntityCommand, IsoScene


class DxfService:
    def __init__(self) -> None:
        try:
            import ezdxf  # type: ignore
        except Exception:
            ezdxf = None
        self._ezdxf = ezdxf

    def write_dxf(self, dsl: CadDsl, destination: Path) -> Path:
        if self._ezdxf is None:
            destination.write_text(json.dumps(dsl.model_dump(mode="json"), indent=2), encoding="utf-8")
            return destination

        doc = self._ezdxf.new("R2018")
        msp = doc.modelspace()
        for layer in {*(dsl.layers or []), *[entity.layer for entity in dsl.entities]}:
            if layer not in doc.layers:
                doc.layers.new(name=layer)

        for entity in dsl.entities:
            self._apply_entity(msp, entity)

        doc.saveas(destination)
        return destination

    def write_iso_svg(self, scene: IsoScene, destination: Path) -> Path:
        lines = [
            '<svg xmlns="http://www.w3.org/2000/svg" viewBox="0 0 1200 900">',
            '<rect width="1200" height="900" fill="#081319" />',
        ]
        for entity in scene.entities:
            params = entity.params
            if entity.entity_type == "line":
                lines.append(
                    (
                        f'<line x1="{params["start"][0]}" y1="{params["start"][1]}" '
                        f'x2="{params["end"][0]}" y2="{params["end"][1]}" '
                        'stroke="#76f7d0" stroke-width="3" />'
                    )
                )
            elif entity.entity_type == "text":
                lines.append(
                    f'<text x="{params["insert"][0]}" y="{params["insert"][1]}" fill="#eef4f2" '
                    'font-size="22" font-family="Bahnschrift, Segoe UI, sans-serif">'
                    f'{params["text"]}</text>'
                )
        lines.append("</svg>")
        destination.write_text("\n".join(lines), encoding="utf-8")
        return destination

    def convert_to_dwg(self, dxf_path: Path, destination: Path, converter_path: str | None) -> Path | None:
        if not converter_path:
            return None
        converter = Path(converter_path)
        if not converter.exists():
            return None

        input_dir = dxf_path.parent / "_oda_in"
        output_dir = dxf_path.parent / "_oda_out"
        input_dir.mkdir(exist_ok=True)
        output_dir.mkdir(exist_ok=True)
        staged = input_dir / dxf_path.name
        shutil.copy2(dxf_path, staged)

        command = [
            str(converter),
            str(input_dir),
            str(output_dir),
            "ACAD2018",
            "DWG",
            "0",
            "1",
            dxf_path.name,
        ]
        try:
            subprocess.run(command, check=True, capture_output=True, text=True)
        except Exception:
            return None

        produced = output_dir / dxf_path.with_suffix(".dwg").name
        if not produced.exists():
            return None
        shutil.copy2(produced, destination)
        return destination

    def _apply_entity(self, msp, entity: CadEntityCommand) -> None:
        params = entity.params
        dxfattribs = {"layer": entity.layer}
        kind = entity.entity_type.lower()
        if kind == "line":
            msp.add_line(params["start"], params["end"], dxfattribs=dxfattribs)
        elif kind == "circle":
            msp.add_circle(params["center"], params["radius"], dxfattribs=dxfattribs)
        elif kind == "arc":
            msp.add_arc(
                params["center"],
                params["radius"],
                params.get("start_angle", 0.0),
                params.get("end_angle", 0.0),
                dxfattribs=dxfattribs,
            )
        elif kind == "lwpolyline":
            msp.add_lwpolyline(params["points"], dxfattribs=dxfattribs, close=params.get("closed", False))
        elif kind == "text":
            text = msp.add_text(
                params["text"],
                dxfattribs={
                    **dxfattribs,
                    "height": params.get("height", 2.5),
                    "rotation": params.get("rotation", 0.0),
                },
            )
            text.set_placement(params["insert"])
        elif kind == "mtext":
            mtext = msp.add_mtext(
                params["text"],
                dxfattribs={
                    **dxfattribs,
                    "char_height": params.get("height", 2.5),
                    "rotation": params.get("rotation", 0.0),
                },
            )
            mtext.set_location(params["insert"])
