"""步骤 1：把压缩封装的 DICOM 解压为 Explicit VR Little Endian 原生像素。

变换与参考导出（DCMTK 系软件）逐元素一致：

- 解码封装式像素数据（如 JPEG Lossless Process 14 SV1），写回未压缩 OW；
- TransferSyntaxUID → 1.2.840.10008.1.2.1；
- 其余全部元素（含 Functional Groups、私有标签、MediaStorage UIDs）原样保留。
"""
from __future__ import annotations

from pathlib import Path

import pydicom
from pydicom.uid import ExplicitVRLittleEndian, PYDICOM_IMPLEMENTATION_UID

from .naming import collect_series_files, instance_file_name, series_dir_name, study_dir_name


def decompress_file(src: Path, dst: Path) -> None:
    """读取单个 DICOM，解码像素并写出为未压缩 Explicit VR LE。"""
    ds = pydicom.dcmread(str(src))
    # pydicom 的 decompress() 会重新生成 SOPInstanceUID；参考导出保留原值，故先存后还原
    sop_instance_uid = ds.SOPInstanceUID
    sop_class_uid = ds.SOPClassUID
    tsyntax = ds.file_meta.TransferSyntaxUID
    if tsyntax.is_compressed:
        ds.decompress()  # 原地解码像素并切换 TransferSyntaxUID
        ds.SOPInstanceUID = sop_instance_uid
        ds.SOPClassUID = sop_class_uid
    if str(ds.file_meta.TransferSyntaxUID) != str(ExplicitVRLittleEndian):
        ds.file_meta.TransferSyntaxUID = ExplicitVRLittleEndian
    # 解压后 16bit 像素按 DICOM 规范应为 OW
    if "PixelData" in ds and ds.BitsAllocated > 8:
        ds["PixelData"].VR = "OW"
    # 文件由本工具写出：如实标注实现身份，不沿用厂商/参考工具的标识
    ds.file_meta.ImplementationClassUID = PYDICOM_IMPLEMENTATION_UID
    ds.file_meta.ImplementationVersionName = f"PYDICOM {pydicom.__version__}"
    dst.parent.mkdir(parents=True, exist_ok=True)
    ds.save_as(str(dst), enforce_file_format=True)


def decompress_tree(input_dir: Path, output_dir: Path) -> list[Path]:
    """把 input_dir 下全部序列转换到 output_dir，命名复现参考导出。"""
    files = collect_series_files(input_dir)
    if not files:
        raise FileNotFoundError(f"输入目录中没有 DICOM 文件: {input_dir}")

    datasets = [pydicom.dcmread(str(f), stop_before_pixels=True) for f in files]
    # 与参考软件一致：按 SeriesNumber 升序赋予 IM-XXXX 序号
    order = sorted(range(len(datasets)), key=lambda i: (int(datasets[i].get("SeriesNumber", 0) or 0), files[i].name))

    written: list[Path] = []
    for ordinal, i in enumerate(order, start=1):
        ds_head = datasets[i]
        rel = Path(study_dir_name(ds_head)) / series_dir_name(ds_head) / instance_file_name(ordinal, 1)
        dst = output_dir / rel
        decompress_file(files[i], dst)
        written.append(dst)
    return written
