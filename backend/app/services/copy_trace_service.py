from __future__ import annotations

from dataclasses import dataclass
from pathlib import Path

from app.schemas.models import CadDsl, CadEntityCommand


@dataclass(slots=True)
class CopyTraceResult:
    dsl: CadDsl
    line_entities: int
    shape_entities: int
    width: int
    height: int


class CopyTraceService:
    def __init__(
        self,
        *,
        min_component_area: int = 8,
        hough_threshold: int = 40,
        min_line_length: int = 28,
        max_line_gap: int = 8,
    ) -> None:
        try:
            import cv2  # type: ignore
            import numpy as np  # type: ignore
        except Exception as exc:
            raise RuntimeError("OpenCV and NumPy are required for clean copy-mode geometry fitting.") from exc

        self._cv2 = cv2
        self._np = np
        self.min_component_area = min_component_area
        self.hough_threshold = hough_threshold
        self.min_line_length = min_line_length
        self.max_line_gap = max_line_gap

    def trace_to_dsl(self, source_path: Path) -> CopyTraceResult:
        gray = self._cv2.imread(str(source_path), self._cv2.IMREAD_GRAYSCALE)
        if gray is None:
            raise RuntimeError(f"Unable to open image for geometry fitting: {source_path}")

        binary = self._prepare_binary(gray)
        line_entities = self._extract_line_entities(binary)
        shape_entities = self._extract_rectangle_entities(binary)
        dsl = CadDsl(
            layers=["TRACE_MAIN", "TRACE_SYMBOL", "TEXT", "DIM", "ISO"],
            entities=[*line_entities, *shape_entities],
        )
        return CopyTraceResult(
            dsl=dsl,
            line_entities=len(line_entities),
            shape_entities=len(shape_entities),
            width=int(gray.shape[1]),
            height=int(gray.shape[0]),
        )

    def _prepare_binary(self, gray):
        blur = self._cv2.GaussianBlur(gray, (3, 3), 0)
        threshold_mode = self._cv2.THRESH_BINARY_INV + self._cv2.THRESH_OTSU
        if float(gray.mean()) < 127:
            threshold_mode = self._cv2.THRESH_BINARY + self._cv2.THRESH_OTSU
        _, binary = self._cv2.threshold(blur, 0, 255, threshold_mode)
        if self._np.count_nonzero(binary) > binary.size * 0.6:
            binary = self._cv2.bitwise_not(binary)

        num_labels, labels, stats, _ = self._cv2.connectedComponentsWithStats(binary, 8)
        clean = self._np.zeros_like(binary)
        for index in range(1, num_labels):
            area = int(stats[index, self._cv2.CC_STAT_AREA])
            if area >= self.min_component_area:
                clean[labels == index] = 255
        return clean

    def _extract_line_entities(self, binary) -> list[CadEntityCommand]:
        lines = self._cv2.HoughLinesP(
            binary,
            1,
            self._np.pi / 180,
            threshold=self.hough_threshold,
            minLineLength=self.min_line_length,
            maxLineGap=self.max_line_gap,
        )
        if lines is None:
            return []

        normalized = [self._normalize_line(line[0]) for line in lines]
        merged = self._merge_axis_aligned_lines(normalized)

        entities: list[CadEntityCommand] = []
        seen: set[tuple[int, int, int, int]] = set()
        for x1, y1, x2, y2 in merged:
            key = tuple(int(round(value / 3.0)) for value in (x1, y1, x2, y2))
            if key in seen:
                continue
            seen.add(key)
            entities.append(
                CadEntityCommand(
                    entity_type="line",
                    layer="TRACE_MAIN",
                    params={"start": [x1, y1], "end": [x2, y2]},
                )
            )
        return entities

    def _extract_rectangle_entities(self, binary) -> list[CadEntityCommand]:
        contours, _ = self._cv2.findContours(binary, self._cv2.RETR_LIST, self._cv2.CHAIN_APPROX_SIMPLE)
        entities: list[CadEntityCommand] = []
        seen: set[tuple[int, int, int, int]] = set()
        for contour in contours:
            area = float(self._cv2.contourArea(contour))
            if area < 80:
                continue
            perimeter = self._cv2.arcLength(contour, True)
            approx = self._cv2.approxPolyDP(contour, 0.02 * perimeter, True)
            if len(approx) != 4 or not self._cv2.isContourConvex(approx):
                continue
            points = [[float(point[0][0]), float(point[0][1])] for point in approx]
            if not self._is_rectangular(points):
                continue
            xs = [point[0] for point in points]
            ys = [point[1] for point in points]
            if max(xs) - min(xs) < 14 or max(ys) - min(ys) < 14:
                continue
            key = (
                round(min(xs) / 6),
                round(min(ys) / 6),
                round(max(xs) / 6),
                round(max(ys) / 6),
            )
            if key in seen:
                continue
            seen.add(key)
            ordered = self._order_rectangle(points)
            entities.append(
                CadEntityCommand(
                    entity_type="lwpolyline",
                    layer="TRACE_SYMBOL",
                    params={"points": ordered, "closed": True},
                )
            )
        return entities

    def _extract_circle_entities(self, gray) -> list[CadEntityCommand]:
        circles = self._cv2.HoughCircles(
            gray,
            self._cv2.HOUGH_GRADIENT,
            dp=1.2,
            minDist=18,
            param1=80,
            param2=15,
            minRadius=4,
            maxRadius=28,
        )
        if circles is None:
            return []
        entities: list[CadEntityCommand] = []
        seen: set[tuple[int, int, int]] = set()
        for circle in circles[0]:
            x, y, radius = [float(value) for value in circle]
            key = (round(x / 4), round(y / 4), round(radius / 3))
            if key in seen:
                continue
            seen.add(key)
            entities.append(
                CadEntityCommand(
                    entity_type="circle",
                    layer="TRACE_SYMBOL",
                    params={"center": [x, y], "radius": radius},
                )
            )
        return entities

    def _normalize_line(self, raw_line) -> tuple[float, float, float, float]:
        x1, y1, x2, y2 = [float(value) for value in raw_line]
        if abs(y1 - y2) <= 3:
            y = round((y1 + y2) / 2, 1)
            x1, x2 = sorted([x1, x2])
            return (x1, y, x2, y)
        if abs(x1 - x2) <= 3:
            x = round((x1 + x2) / 2, 1)
            y1, y2 = sorted([y1, y2])
            return (x, y1, x, y2)
        if x1 > x2:
            return (x2, y2, x1, y1)
        return (x1, y1, x2, y2)

    def _merge_axis_aligned_lines(self, lines: list[tuple[float, float, float, float]]) -> list[tuple[float, float, float, float]]:
        horizontals: dict[int, list[tuple[float, float]]] = {}
        verticals: dict[int, list[tuple[float, float]]] = {}
        angled: list[tuple[float, float, float, float]] = []

        for x1, y1, x2, y2 in lines:
            if abs(y1 - y2) <= 0.1:
                bucket = round(y1 / 4)
                horizontals.setdefault(bucket, []).append((x1, x2))
                continue
            if abs(x1 - x2) <= 0.1:
                bucket = round(x1 / 4)
                verticals.setdefault(bucket, []).append((y1, y2))
                continue
            angled.append((x1, y1, x2, y2))

        merged: list[tuple[float, float, float, float]] = []
        for bucket, segments in horizontals.items():
            y = bucket * 4.0
            for start, end in self._merge_1d_segments(segments):
                if end - start >= self.min_line_length:
                    merged.append((start, y, end, y))

        for bucket, segments in verticals.items():
            x = bucket * 4.0
            for start, end in self._merge_1d_segments(segments):
                if end - start >= self.min_line_length:
                    merged.append((x, start, x, end))

        merged.extend(angled)
        return merged

    def _merge_1d_segments(self, segments: list[tuple[float, float]]) -> list[tuple[float, float]]:
        ordered = sorted((min(start, end), max(start, end)) for start, end in segments)
        if not ordered:
            return []
        merged: list[list[float]] = [[ordered[0][0], ordered[0][1]]]
        for start, end in ordered[1:]:
            current = merged[-1]
            if start <= current[1] + 8:
                current[1] = max(current[1], end)
            else:
                merged.append([start, end])
        return [(item[0], item[1]) for item in merged]

    def _is_rectangular(self, points: list[list[float]]) -> bool:
        if len(points) != 4:
            return False
        ordered = self._order_rectangle(points)
        vectors = []
        for index in range(4):
            x1, y1 = ordered[index]
            x2, y2 = ordered[(index + 1) % 4]
            vectors.append((x2 - x1, y2 - y1))
        for index in range(4):
            ax, ay = vectors[index]
            bx, by = vectors[(index + 1) % 4]
            dot = abs(ax * bx + ay * by)
            if dot > max(40.0, 0.15 * ((ax * ax + ay * ay) ** 0.5) * ((bx * bx + by * by) ** 0.5)):
                return False
        return True

    def _order_rectangle(self, points: list[list[float]]) -> list[list[float]]:
        cx = sum(point[0] for point in points) / 4.0
        cy = sum(point[1] for point in points) / 4.0
        return sorted(points, key=lambda point: (self._np.arctan2(point[1] - cy, point[0] - cx), point[0], point[1]))
