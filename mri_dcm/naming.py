"""目录与文件命名规则——完全复现参考导出软件（DCMTK 系）的布局。

参考导出结构::

    {StudyDescription} - {RequestedProcedureID 空格→下划线}/
        {SeriesDescription 去小数点}_{SeriesNumber}/
            IM-{序列序号:04d}-0001.dcm     # 序列序号 = 按 SeriesNumber 排序后的 1 基序号
"""
from __future__ import annotations

import re
from pathlib import Path

import pydicom

_INVALID_PATH_CHARS = re.compile(r'[/\\:*?"<>|\x00-\x1f]')


def _sanitize(text: str) -> str:
    """替换文件系统不安全字符。"""
    return _INVALID_PATH_CHARS.sub("_", text.strip())


def study_dir_name(ds: pydicom.dataset.Dataset) -> str:
    # 参考导出：StudyDescription 与 RequestedProcedureID 的空格均转为下划线
    study = _sanitize(str(ds.get("StudyDescription", "") or "STUDY").replace(" ", "_"))
    proc_id = _sanitize(str(ds.get("RequestedProcedureID", "") or "").replace(" ", "_"))
    return f"{study} - {proc_id}" if proc_id else study


def series_dir_name(ds: pydicom.dataset.Dataset) -> str:
    # 参考导出：SeriesDescription 去小数点、空格转下划线（如 "cs +C" → "cs_+C"）
    desc = _sanitize(str(ds.get("SeriesDescription", "") or "").replace(".", "").replace(" ", "_"))
    num = str(ds.get("SeriesNumber", 0) or 0)
    return f"{desc}_{num}" if desc else f"SERIES_{num}"


def instance_file_name(series_ordinal: int, image_number: int) -> str:
    """IM-<序列序号4位>-<图像号4位>.dcm（参考软件第二段恒为 0001，因每序列单文件）。"""
    return f"IM-{series_ordinal:04d}-{image_number:04d}.dcm"


def collect_series_files(input_dir: Path) -> list[Path]:
    """递归收集输入目录下所有 DICOM 文件。"""
    return sorted(p for p in input_dir.rglob("*") if p.is_file() and not p.name.startswith("."))
