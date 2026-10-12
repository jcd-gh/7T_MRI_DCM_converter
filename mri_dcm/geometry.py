"""从 Enhanced MR 功能性组序列提取帧几何的工具。"""
from __future__ import annotations

from dataclasses import dataclass, field

import numpy as np
import pydicom
from pydicom.dataset import Dataset


def _first_item(ds: Dataset | None, seq_name: str) -> Dataset | None:
    """取序列首个 item；兼容 shared / per-frame 两种位置，不存在返回 None。"""
    if ds is None:
        return None
    seq = ds.get(seq_name)
    if seq is None:
        return None
    seq = seq.value if hasattr(seq, "value") else seq
    return seq[0] if len(seq) else None


@dataclass
class FrameGeometry:
    """单帧几何 + 像素变换信息（供经典 MR 单帧文件使用）。"""

    position: list[float]        # ImagePositionPatient
    orientation: list[float]     # ImageOrientationPatient（行、列方向余弦）
    pixel_spacing: list[float] | None = None
    slice_thickness: float | None = None
    spacing_between_slices: float | None = None
    rescale_intercept: str | None = None
    rescale_slope: str | None = None
    rescale_type: str | None = None
    window_center: str | None = None
    window_width: str | None = None
    echo_time: str | None = None
    stack_id: str = "1"
    in_stack_position: int | None = None
    temporal_index: int = 1
    frame_acquisition_datetime: str | None = None

    @property
    def normal(self) -> np.ndarray:
        r = np.asarray(self.orientation[:3], dtype=float)
        c = np.asarray(self.orientation[3:], dtype=float)
        return np.cross(r, c)


def extract_frame_geometries(ds: Dataset) -> list[FrameGeometry]:
    """按帧顺序提取几何信息（shared 组作为缺省，per-frame 组覆盖）。"""
    shared = _first_item(ds, "SharedFunctionalGroupsSequence")
    per_frame = ds.PerFrameFunctionalGroupsSequence if "PerFrameFunctionalGroupsSequence" in ds else []

    def merge(shared_item: Dataset | None, frame_item: Dataset | None) -> FrameGeometry:
        geom = FrameGeometry(position=[0.0, 0.0, 0.0], orientation=[1, 0, 0, 0, 1, 0])
        # shared 提供缺省值
        for item in (shared_item, frame_item):
            if item is None:
                continue
            pm = _first_item(item, "PixelMeasuresSequence")
            if pm is not None:
                if "PixelSpacing" in pm:
                    geom.pixel_spacing = list(pm.PixelSpacing)
                if "SliceThickness" in pm:
                    geom.slice_thickness = float(pm.SliceThickness)
                if "SpacingBetweenSlices" in pm:
                    geom.spacing_between_slices = float(pm.SpacingBetweenSlices)
            pvt = _first_item(item, "PixelValueTransformationSequence")
            if pvt is not None:
                geom.rescale_intercept = str(pvt.get("RescaleIntercept", geom.rescale_intercept))
                geom.rescale_slope = str(pvt.get("RescaleSlope", geom.rescale_slope))
                geom.rescale_type = str(pvt.get("RescaleType", geom.rescale_type or "US"))
            voi = _first_item(item, "FrameVOILUTSequence")
            if voi is not None:
                geom.window_center = str(voi.get("WindowCenter", geom.window_center))
                geom.window_width = str(voi.get("WindowWidth", geom.window_width))
            echo = _first_item(item, "MREchoSequence")
            if echo is not None and "EffectiveEchoTime" in echo:
                geom.echo_time = str(echo.EffectiveEchoTime)
        # 位置与方向只存在于 per-frame
        pp = _first_item(frame_item, "PlanePositionSequence")
        if pp is not None and "ImagePositionPatient" in pp:
            geom.position = [float(v) for v in pp.ImagePositionPatient]
        po = _first_item(frame_item, "PlaneOrientationSequence")
        if po is not None and "ImageOrientationPatient" in po:
            geom.orientation = [float(v) for v in po.ImageOrientationPatient]
        fc = _first_item(frame_item, "FrameContentSequence")
        if fc is not None:
            geom.stack_id = str(fc.get("StackID", "1"))
            geom.in_stack_position = int(fc.get("InStackPositionNumber", 0) or 0) or None
            geom.temporal_index = int(fc.get("TemporalPositionIndex", 1) or 1)
            geom.frame_acquisition_datetime = str(fc.get("FrameAcquisitionDateTime", "")) or None
        return geom

    out = [merge(shared, item) for item in per_frame]
    if not out:  # 单帧或无 FG 的退化情形
        out = [merge(shared, None)]
    return out


def sort_frames_by_normal(geoms: list[FrameGeometry]) -> list[int]:
    """返回按层面法向量投影升序的帧下标（空间排序，兼容任意斜面方位）。"""
    normal = geoms[0].normal
    projections = [float(np.dot(np.asarray(g.position, dtype=float), normal)) for g in geoms]
    order = sorted(range(len(geoms)), key=lambda i: projections[i])
    diffs = np.diff([projections[i] for i in order])
    return order, projections, diffs


def compute_slice_spacing(geoms: list[FrameGeometry], order: list[int], projections: list[float]) -> float | None:
    """层间距：优先用相邻帧投影差的中位数（比 SpacingBetweenSlices 标签更精确）。"""
    if len(order) < 2:
        return geoms[0].spacing_between_slices
    proj = np.asarray([projections[i] for i in order])
    step = float(np.median(np.diff(proj)))
    return round(step, 4)
