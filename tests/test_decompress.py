"""decompress（步骤 1）与命名规则单元测试。"""
from __future__ import annotations

import sys
from pathlib import Path

import numpy as np
import pydicom
import pytest
from pydicom.uid import ExplicitVRLittleEndian

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))
from mri_dcm.decompress import decompress_file, decompress_tree  # noqa: E402
from mri_dcm.naming import instance_file_name, series_dir_name, study_dir_name  # noqa: E402

from conftest import make_enhanced_mr  # noqa: E402


def test_decompress_uncompressed_passthrough(tmp_path):
    """未压缩输入：元素与像素完全保留，输出为 Explicit VR LE，命名符合参考约定。"""
    src, volume, _ = make_enhanced_mr(tmp_path)
    out = tmp_path / "exported"
    written = decompress_tree(src.parent, out)
    assert len(written) == 1
    dst = out / "TEST_STUDY - RP_ID" / "test05_mm_5" / "IM-0001-0001.dcm"
    assert written[0] == dst

    ds_in, ds_out = pydicom.dcmread(str(src)), pydicom.dcmread(str(dst))
    assert str(ds_out.file_meta.TransferSyntaxUID) == str(ExplicitVRLittleEndian)
    assert ds_out.SOPInstanceUID == ds_in.SOPInstanceUID  # 保留原 UID
    assert np.array_equal(ds_out.pixel_array, volume)
    for elem in ds_in:
        if elem.tag == (0x7FE0, 0x0010):
            continue
        assert ds_out[elem.tag].value == elem.value


def test_naming_rules():
    ds = pydicom.Dataset()
    ds.StudyDescription = "Brain 7T Study"
    ds.RequestedProcedureID = "REQ PROC ID"
    assert study_dir_name(ds) == "Brain_7T_Study - REQ_PROC_ID"
    ds.SeriesDescription = "t1_mprage_0.71mm_cs +C"
    ds.SeriesNumber = 11
    assert series_dir_name(ds) == "t1_mprage_071mm_cs_+C_11"
    assert instance_file_name(5, 1) == "IM-0005-0001.dcm"


def test_missing_input_raises(tmp_path):
    with pytest.raises(FileNotFoundError):
        decompress_tree(tmp_path / "nope", tmp_path / "out")


def test_decompress_single_file_preserves_uid(tmp_path):
    src, _, _ = make_enhanced_mr(tmp_path)
    dst = tmp_path / "single.dcm"
    decompress_file(src, dst)
    assert pydicom.dcmread(str(dst)).SOPInstanceUID == pydicom.dcmread(str(src)).SOPInstanceUID
