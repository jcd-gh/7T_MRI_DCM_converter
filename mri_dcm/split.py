"""步骤 2：把 Enhanced MR 多帧文件拆分为经典 MR Image Storage 单帧文件。

单帧 + Explicit VR Little Endian + 经典 IOD 是兼容性最好的组合——ImageJ（内建
DICOM 阅读器）、老版本 PACS/viewer、FSL 等均可直接读取并正确堆叠为三维体。

- 每帧一个文件：新的 SOPInstanceUID，SOPClassUID → MR Image Storage
- 几何来自功能性组：ImagePosition/ImageOrientation/PixelSpacing/Rescale/Window
- 层序按层面法向量投影排序（兼容矢状位等非轴向采集），InstanceNumber 随空间序
- 剔除全部 Enhanced 专属属性（Functional Groups、Pixel Presentation 等）
"""
from __future__ import annotations

import copy
from pathlib import Path

import numpy as np
import pydicom
from pydicom.dataset import Dataset
from pydicom.tag import Tag
from pydicom.uid import ExplicitVRLittleEndian, MRImageStorage, PYDICOM_IMPLEMENTATION_UID, generate_uid

from .geometry import FrameGeometry, compute_slice_spacing, extract_frame_geometries, sort_frames_by_normal
from .naming import collect_series_files, instance_file_name, series_dir_name, study_dir_name

# Enhanced MR 专属/多帧专属/经典 IOD 不容纳的标签 → 拆分后移除
_DROP_TAGS = {
    Tag(0x0008, 0x9092),  # Referenced Image Evidence Sequence（Enhanced 专属）
    Tag(0x0008, 0x9205),  # Pixel Presentation
    Tag(0x0008, 0x9206),  # Volumetric Properties
    Tag(0x0008, 0x9207),  # Volume Based Calculation Technique
    Tag(0x0008, 0x9208),  # Complex Image Component
    Tag(0x0008, 0x9209),  # Acquisition Contrast
    Tag(0x0020, 0x0060),  # Laterality（源值 'U' 不在经典 IOD 枚举内）
    Tag(0x0020, 0x0105),  # Number of Temporal Positions
    Tag(0x0020, 0x9221),  # Dimension Organization Sequence
    Tag(0x0020, 0x9222),  # Dimension Index Sequence
    Tag(0x0028, 0x0008),  # Number of Frames
    Tag(0x0028, 0x0009),  # Frame Increment Pointer
    Tag(0x0032, 0x1030),  # Reason for Study
    Tag(0x0032, 0x1032),  # Requesting Physician
    Tag(0x0032, 0x1060),  # Requested Procedure Description
    Tag(0x0032, 0x4000),  # Study Comments
    Tag(0x0038, 0x0300),  # Current Patient Location
    Tag(0x0040, 0x0555),  # Acquisition Context Sequence（Enhanced 专属）
    Tag(0x0040, 0x1001),  # Requested Procedure ID
    Tag(0x0040, 0x1003),  # Requested Procedure Priority
    Tag(0x0040, 0x2004),  # Issue Date of Imaging Service Request
    Tag(0x5200, 0x9229),  # Shared Functional Groups Sequence
    Tag(0x5200, 0x9230),  # Per-frame Functional Groups Sequence
}

# Sequence Variant (0018,0021) 的合法 Defined Terms（PS3.3 C.8-21）
_VALID_SEQUENCE_VARIANTS = {"SCOUT", "SK", "MTC", "SP", "MP", "OSP", "NONE"}

# 从 shared 功能组提升到经典 MR 顶层标签的映射：(源标签, 目标标签)，缺失则跳过
_LIFT_FROM_SHARED = [
    (Tag(0x0018, 0x0080), Tag(0x0018, 0x0080)),  # Repetition Time
    (Tag(0x0018, 0x0091), Tag(0x0018, 0x0091)),  # Echo Train Length
    (Tag(0x0018, 0x1314), Tag(0x0018, 0x1314)),  # Flip Angle
    (Tag(0x0018, 0x0093), Tag(0x0018, 0x0093)),  # Percent Sampling
    (Tag(0x0018, 0x0094), Tag(0x0018, 0x0094)),  # Percent Phase Field of View
    (Tag(0x0018, 0x1312), Tag(0x0018, 0x1312)),  # In-plane Phase Encoding Direction
    (Tag(0x0018, 0x1250), Tag(0x0018, 0x1250)),  # Receive Coil Name
    (Tag(0x0018, 0x0095), Tag(0x0018, 0x0095)),  # Pixel Bandwidth
]

ENHANCED_MR_SOP_CLASS = "1.2.840.10008.5.1.4.1.1.4.1"


def _synthesize_mr_sequence_attrs(out: Dataset, src: Dataset, shared: Dataset | None) -> None:
    """补齐经典 MR Image 模块的 Type 1/2 必需标签（Scanning Sequence 等）。

    增强版用 (0018,9008) Echo Pulse Sequence 等属性编码同等信息；经典版必须
    用旧枚举合成。序列变体/扫描选项优先取 Siemens CSA 私有标签中保存的经典值。
    """
    if "ScanningSequence" in out:
        return
    tokens = []
    echo_pulse = str(src.get("EchoPulseSequence", "") or "")
    if echo_pulse == "SPIN":
        tokens.append("SE")
    elif echo_pulse == "GRADIENT":
        tokens.append("GR")
    inversion = None
    for item in filter(None, [shared]):
        for el in item:
            if el.VR == "SQ" and el.value and "InversionRecovery" in el.value[0]:
                inversion = str(el.value[0].InversionRecovery)
    if inversion == "YES":
        tokens.append("IR")
    out.ScanningSequence = tokens or ["SE"]

    csa_variant: list[str] = []
    csa_options = None
    for item in filter(None, [shared]):
        for el in item:
            if el.VR != "SQ" or not el.value:
                continue
            inner = el.value[0]
            if (0x0021, 0x105B) in inner:
                val = inner[(0x0021, 0x105B)].value
                csa_variant = [str(v) for v in (val if isinstance(val, (list, tuple)) else [val])]
            if (0x0021, 0x105C) in inner:
                csa_options = str(inner[(0x0021, 0x105C)].value)
    valid_variants = [v for v in csa_variant if v in _VALID_SEQUENCE_VARIANTS]
    out.SequenceVariant = valid_variants or ["NONE"]
    out.ScanOptions = csa_options if csa_options else ""


def _clean_request_attributes(out: Dataset) -> None:
    """移除 Request Attributes Sequence 内的空元素（空 Type 1 元素不合规范）。"""
    if "RequestAttributesSequence" not in out:
        return
    for item in out.RequestAttributesSequence:
        for elem in list(item):
            if elem.VR != "SQ" and (elem.value is None or str(elem.value) == ""):
                del item[elem.tag]


def _base_dataset(src: Dataset) -> Dataset:
    """从源文件构建单帧经典 MR 的顶层标签集：拷贝全部、剔除增强专属、提升 shared 组参数。"""
    out = Dataset()
    for elem in src:
        tag = elem.tag
        if tag.group == 0x0018 and tag.element >= 0x9000:
            continue  # 增强 MR 模块专属（Pulse Sequence Name、安全模块等 0018,9xxx）
        if tag in _DROP_TAGS:
            continue
        out[tag] = elem

    shared = src.SharedFunctionalGroupsSequence[0] if "SharedFunctionalGroupsSequence" in src else None
    if shared is not None:
        for item in shared:
            if item.VR != "SQ" or not item.value:
                continue  # shared 组内的私有标量/二进制标签不参与提升
            inner = item.value[0]
            for src_tag, dst_tag in _LIFT_FROM_SHARED:
                if src_tag in inner and dst_tag not in out:
                    out[dst_tag] = inner[src_tag]
    _synthesize_mr_sequence_attrs(out, src, shared)
    _clean_request_attributes(out)
    return out


def _make_file_meta(sop_instance_uid: str) -> Dataset:
    meta = Dataset()
    meta.MediaStorageSOPClassUID = MRImageStorage
    meta.MediaStorageSOPInstanceUID = sop_instance_uid
    meta.TransferSyntaxUID = ExplicitVRLittleEndian
    meta.ImplementationClassUID = PYDICOM_IMPLEMENTATION_UID
    meta.ImplementationVersionName = f"PYDICOM {pydicom.__version__}"
    return meta


def _write_single_frame(
    base: Dataset,
    pixels: np.ndarray,
    geom: FrameGeometry,
    instance_number: int,
    slice_location: float,
    slice_spacing: float | None,
    dst: Path,
) -> None:
    # 深拷贝：pydicom 的浅拷贝共享 DataElement，逐层赋值会互相污染
    ds = copy.deepcopy(base)
    ds.SOPClassUID = MRImageStorage
    ds.SOPInstanceUID = str(generate_uid())
    ds.InstanceNumber = instance_number
    ds.file_meta = _make_file_meta(ds.SOPInstanceUID)

    # 几何
    ds.ImagePositionPatient = [str(v) for v in geom.position]
    ds.ImageOrientationPatient = [str(v) for v in geom.orientation]
    if geom.pixel_spacing is not None:
        ds.PixelSpacing = [str(v) for v in geom.pixel_spacing]
    if geom.slice_thickness is not None:
        ds.SliceThickness = str(geom.slice_thickness)
    if slice_spacing is not None:
        ds.SpacingBetweenSlices = str(slice_spacing)
    ds.SliceLocation = str(round(slice_location, 4))

    # 像素值变换 / 窗：恒等 Rescale（截距 0、斜率 1）不写——MR Image IOD 不含
    # Modality LUT 模块，写入会被严格校验器判为冗余；窗宽窗照抄源帧
    if geom.rescale_intercept is not None and not (
        float(geom.rescale_intercept or 0) == 0 and float(geom.rescale_slope or 1) == 1
    ):
        ds.RescaleIntercept = geom.rescale_intercept
        ds.RescaleSlope = geom.rescale_slope or "1"
        ds.RescaleType = geom.rescale_type or "US"
    if geom.window_center is not None:
        ds.WindowCenter = geom.window_center
        ds.WindowWidth = geom.window_width
    if geom.echo_time is not None:
        ds.EchoTime = geom.echo_time

    # 每层采集时间
    if geom.frame_acquisition_datetime:
        dt = geom.frame_acquisition_datetime
        ds.AcquisitionDateTime = dt
        ds.ContentDate = dt[:8]
        ds.ContentTime = dt[8:]

    # 像素数据（原生、未压缩；显式小端字节序）
    dtype = "<u2" if ds.BitsAllocated > 8 else "u1"
    ds.PixelData = np.ascontiguousarray(pixels.astype(dtype)).tobytes()
    elem = ds["PixelData"]
    elem.VR = "OW" if ds.BitsAllocated > 8 else "OB"

    dst.parent.mkdir(parents=True, exist_ok=True)
    ds.save_as(str(dst), enforce_file_format=True)


def split_file(src: Path, output_dir: Path, series_ordinal: int) -> list[Path]:
    """把一个多帧文件拆为 output_dir 下的单帧序列目录，返回写出的文件列表。"""
    ds = pydicom.dcmread(str(src))
    if str(ds.SOPClassUID) != ENHANCED_MR_SOP_CLASS:
        raise ValueError(f"{src}: 非 Enhanced MR Image Storage（{ds.SOPClassUID}），无需拆分")

    pixels = ds.pixel_array  # 解码后的体数据 (frames, rows, cols)
    geoms = extract_frame_geometries(ds)
    if len(geoms) != pixels.shape[0]:
        raise ValueError(f"{src}: 帧几何数 {len(geoms)} 与像素帧数 {pixels.shape[0]} 不一致")

    # 多 Stack / 多时间点 → 各自独立子序列（当前数据不会触发，防御性处理）
    groups: dict[tuple[str, int], list[int]] = {}
    for i, g in enumerate(geoms):
        groups.setdefault((g.stack_id, g.temporal_index), []).append(i)

    base = _base_dataset(ds)
    study_dir = study_dir_name(ds)
    written: list[Path] = []

    for group_idx, ((stack_id, temporal), frame_ids) in enumerate(sorted(groups.items())):
        order, projections, _ = sort_frames_by_normal([geoms[i] for i in frame_ids])
        slice_spacing = compute_slice_spacing(geoms, order, projections)
        group_base = base
        if group_idx > 0 or len(groups) > 1:
            group_base = copy.deepcopy(base)
            group_base.SeriesInstanceUID = str(generate_uid())
            group_base.SeriesNumber = int(ds.SeriesNumber) * 100 + group_idx
            group_base.SeriesDescription = f"{ds.SeriesDescription} [stack {stack_id} t{temporal}]"
        series_dir = series_dir_name(group_base)

        for instance_number, frame_idx in enumerate(order, start=1):
            geom = geoms[frame_idx]
            normal = geom.normal
            slice_location = float(np.dot(np.asarray(geom.position), normal))
            dst = output_dir / study_dir / series_dir / instance_file_name(series_ordinal, instance_number)
            _write_single_frame(
                group_base, pixels[frame_idx], geom,
                instance_number=instance_number,
                slice_location=slice_location,
                slice_spacing=slice_spacing,
                dst=dst,
            )
            written.append(dst)
    return written


def split_tree(input_dir: Path, output_dir: Path) -> list[Path]:
    """把 input_dir 下全部多帧文件拆分为单帧文件（输入可为压缩或已解压）。"""
    files = collect_series_files(input_dir)
    if not files:
        raise FileNotFoundError(f"输入目录中没有 DICOM 文件: {input_dir}")

    datasets = [pydicom.dcmread(str(f), stop_before_pixels=True) for f in files]
    order = sorted(range(len(datasets)), key=lambda i: (int(datasets[i].get("SeriesNumber", 0) or 0), files[i].name))

    written: list[Path] = []
    for ordinal, i in enumerate(order, start=1):
        written.extend(split_file(files[i], output_dir, ordinal))
    return written
