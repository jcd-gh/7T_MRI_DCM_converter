#!/usr/bin/env python3
"""验证步骤 2 输出（单帧经典 MR）的正确性与兼容性。

对每个序列检查：
1. 结构：SOP Class = MR Image Storage、Explicit VR LE、无 NumberOfFrames、无 Functional Groups
2. 数量：文件数 == 源 NumberOfFrames
3. 像素：按几何排序重建体数据，与源解码像素逐位一致
4. 几何：位置沿层面法向量单调、方向余弦与源一致、PixelSpacing/SliceThickness 与源一致、层距均匀
5. 编号：InstanceNumber 连续 1..N，与空间序一致
6. 关键兼容标签：ImagePosition/ImageOrientation/SliceLocation/Rescale/Window 等存在
"""
from __future__ import annotations

import sys
from pathlib import Path

import numpy as np
import pydicom
from pydicom.uid import ExplicitVRLittleEndian, MRImageStorage

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))
from mri_dcm.geometry import extract_frame_geometries, sort_frames_by_normal  # noqa: E402

COMPAT_REQUIRED = [
    "ImagePositionPatient", "ImageOrientationPatient", "PixelSpacing", "SliceThickness",
    "SpacingBetweenSlices", "SliceLocation", "InstanceNumber", "ScanningSequence",
    "SequenceVariant", "ScanOptions", "WindowCenter", "WindowWidth",
    "SeriesInstanceUID", "StudyInstanceUID", "FrameOfReferenceUID",
    "BitsAllocated", "BitsStored", "PixelRepresentation",
    "PhotometricInterpretation", "SOPInstanceUID",
]


def verify_series(src: Path, slice_files: list[Path]) -> list[str]:
    problems: list[str] = []
    src_ds = pydicom.dcmread(str(src))
    src_pixels = src_ds.pixel_array
    geoms = extract_frame_geometries(src_ds)
    order, projections, _ = sort_frames_by_normal(geoms)

    slices = [pydicom.dcmread(str(f)) for f in slice_files]

    # 1. 结构
    for i, ds in enumerate(slices):
        tag_problems = []
        if str(ds.SOPClassUID) != str(MRImageStorage):
            tag_problems.append(f"SOPClass={ds.SOPClassUID}")
        if str(ds.file_meta.TransferSyntaxUID) != str(ExplicitVRLittleEndian):
            tag_problems.append(f"TS={ds.file_meta.TransferSyntaxUID}")
        if "NumberOfFrames" in ds:
            tag_problems.append("含 NumberOfFrames")
        if "SharedFunctionalGroupsSequence" in ds or "PerFrameFunctionalGroupsSequence" in ds:
            tag_problems.append("含 Functional Groups")
        for kw in COMPAT_REQUIRED:
            if kw not in ds:
                tag_problems.append(f"缺 {kw}")
        if tag_problems:
            problems.append(f"第 {i + 1} 个文件结构问题: {'; '.join(tag_problems)}")
            if len(problems) > 5:
                return problems

    # 2. 数量
    if len(slices) != int(src_ds.NumberOfFrames):
        problems.append(f"文件数 {len(slices)} != 源帧数 {src_ds.NumberOfFrames}")

    # 5. 编号（按文件名 IM-XXXX-YYYY 的 YYYY 排序后应为 1..N）
    instance_numbers = [int(ds.InstanceNumber) for ds in slices]
    if sorted(instance_numbers) != list(range(1, len(slices) + 1)):
        problems.append(f"InstanceNumber 不连续: min={min(instance_numbers)} max={max(instance_numbers)} n={len(slices)}")

    # 4. 几何
    normal = np.cross(np.asarray(geoms[0].orientation[:3]), np.asarray(geoms[0].orientation[3:]))
    proj = np.array([float(np.dot(np.asarray(ds.ImagePositionPatient, dtype=float), normal)) for ds in slices])
    if not np.all(np.diff(proj) > 0):
        problems.append("切片位置沿法向量非严格单调递增")
    spacing = np.diff(proj)
    if len(spacing) and (np.max(np.abs(spacing - spacing.mean())) > 0.05):
        problems.append(f"层距不均匀: mean={spacing.mean():.4f} maxdev={np.max(np.abs(spacing - spacing.mean())):.4f}")
    for i, ds in enumerate(slices):
        if not np.allclose([float(v) for v in ds.ImageOrientationPatient], geoms[0].orientation, atol=1e-6):
            problems.append(f"第 {i + 1} 层方向余弦与源不一致")
            break
    src_pm = None
    for g in geoms:
        if g.pixel_spacing:
            src_pm = g
            break
    if src_pm is not None and slices:
        if not np.allclose([float(v) for v in slices[0].PixelSpacing], src_pm.pixel_spacing, atol=1e-6):
            problems.append(f"PixelSpacing 不一致: {list(slices[0].PixelSpacing)} vs {src_pm.pixel_spacing}")
        if abs(float(slices[0].SliceThickness) - float(src_pm.slice_thickness)) > 1e-6:
            problems.append(f"SliceThickness 不一致: {slices[0].SliceThickness} vs {src_pm.slice_thickness}")

    # 每层位置应与源帧位置一一对应（按空间序）
    for i, ds in enumerate(slices):
        src_pos = np.asarray(geoms[order[i]].position)
        if not np.allclose(np.asarray(ds.ImagePositionPatient, dtype=float), src_pos, atol=1e-4):
            problems.append(f"第 {i + 1} 层位置与源帧不匹配: {list(ds.ImagePositionPatient)} vs {src_pos.tolist()}")
            break

    # 3. 像素逐位一致（文件 InstanceNumber → 源空间序帧）
    try:
        for i, ds in enumerate(slices):
            if not np.array_equal(ds.pixel_array, src_pixels[order[i]]):
                diff = int(np.sum(ds.pixel_array != src_pixels[order[i]]))
                problems.append(f"第 {i + 1} 层像素与源帧 {order[i]} 不一致（{diff} 个体素不同）")
                break
    except Exception as e:  # noqa: BLE001
        problems.append(f"像素读取失败: {e}")

    return problems


def main() -> int:
    src_root, out_root = Path(sys.argv[1]), Path(sys.argv[2])
    src_files = sorted(src_root.rglob("*.dcm"))

    series_dirs: dict[str, list[Path]] = {}
    for f in sorted(out_root.rglob("*.dcm")):
        series_dirs.setdefault(str(f.parent), []).append(f)

    failed = 0
    for src in src_files:
        head = pydicom.dcmread(str(src), stop_before_pixels=True)
        key = f"{str(head.SeriesDescription).replace('.', '').replace(' ', '_')}_{head.SeriesNumber}"
        matches = [d for d in series_dirs if d.endswith(key)]
        if len(matches) != 1:
            print(f"[FAIL] 序列 {key} 在输出中匹配到 {len(matches)} 个目录")
            failed += 1
            continue
        slice_files = sorted(series_dirs[matches[0]])
        problems = verify_series(src, slice_files)
        if problems:
            failed += 1
            print(f"[FAIL] {key}")
            for p in problems:
                print(f"    {p}")
        else:
            n = len(slice_files)
            positions = [pydicom.dcmread(str(f), stop_before_pixels=True) for f in slice_files]
            spacing = np.diff([float(p.SliceLocation) for p in positions]).mean()
            print(f"[OK]   {key}: {n} 层, 平均层距 {abs(spacing):.4f} mm, 像素逐位一致")
    print(f"\n{'全部通过' if failed == 0 else f'{failed} 个序列未通过'}")
    return 1 if failed else 0


if __name__ == "__main__":
    sys.exit(main())
