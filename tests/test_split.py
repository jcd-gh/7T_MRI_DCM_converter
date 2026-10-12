"""split（步骤 2）单元测试：合成数据全流程。"""
from __future__ import annotations

import sys
from pathlib import Path

import numpy as np
import pydicom
import pytest
from pydicom.uid import ExplicitVRLittleEndian, MRImageStorage

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))
from mri_dcm.split import split_file  # noqa: E402

from conftest import FRAMES, make_enhanced_mr  # noqa: E402


@pytest.fixture()
def split_result(tmp_path):
    src, volume, spatial_order = make_enhanced_mr(tmp_path)
    out_dir = tmp_path / "out"
    files = split_file(src, out_dir, series_ordinal=1)
    return src, volume, spatial_order, out_dir, files


def _slices(files):
    return [pydicom.dcmread(str(f)) for f in sorted(files)]


def test_file_count_and_naming(split_result):
    _, _, _, out_dir, files = split_result
    assert len(files) == FRAMES
    series_dir = out_dir / "TEST_STUDY - RP_ID" / "test05_mm_5"
    assert all(f.parent == series_dir for f in files)
    assert sorted(f.name for f in files) == [f"IM-0001-000{i}.dcm" for i in range(1, FRAMES + 1)]


def test_classic_sop_structure(split_result):
    _, _, _, _, files = split_result
    for ds in _slices(files):
        assert str(ds.SOPClassUID) == str(MRImageStorage)
        assert str(ds.file_meta.TransferSyntaxUID) == str(ExplicitVRLittleEndian)
        assert "NumberOfFrames" not in ds
        assert "SharedFunctionalGroupsSequence" not in ds
        assert "PerFrameFunctionalGroupsSequence" not in ds
        assert "DimensionOrganizationSequence" not in ds
        assert "Laterality" not in ds
        assert "PixelPresentation" not in ds


def test_spatial_sorting_and_pixels(split_result):
    _, volume, spatial_order, _, files = split_result
    for i, ds in enumerate(_slices(files)):
        assert int(ds.InstanceNumber) == i + 1
        assert np.array_equal(ds.pixel_array, volume[spatial_order[i]])
        assert float(ds.SliceLocation) == pytest.approx([6.0, 8.0, 10.0][i])


def test_geometry_tags(split_result):
    _, _, _, _, files = split_result
    slices = _slices(files)
    assert [float(v) for v in slices[0].ImageOrientationPatient] == [0, 1, 0, 0, 0, -1]
    assert [float(v) for v in slices[0].PixelSpacing] == [0.5, 0.5]
    assert float(slices[0].SliceThickness) == 1.0
    assert float(slices[0].SpacingBetweenSlices) == 2.0
    assert list(slices[0].ImagePositionPatient) == ["-6.0", "-5.0", "7.0"]


def test_synthesized_mr_module_tags(split_result):
    _, _, _, _, files = split_result
    ds = _slices(files)[0]
    assert list(ds.ScanningSequence) == ["GR", "IR"]  # GRADIENT + InversionRecovery=YES
    assert list(ds.SequenceVariant)
    assert "ScanOptions" in ds
    assert float(ds.RepetitionTime) == 2500.0  # 从 shared 组提升


def test_window_copied_identity_rescale_dropped(split_result):
    _, _, _, _, files = split_result
    ds = _slices(files)[0]
    assert float(ds.WindowCenter) == 200
    assert float(ds.WindowWidth) == 400
    assert "RescaleIntercept" not in ds  # 恒等 Rescale 不写


def test_unique_sop_instance_uids(split_result):
    _, _, _, _, files = split_result
    uids = {str(ds.SOPInstanceUID) for ds in _slices(files)}
    assert len(uids) == FRAMES
