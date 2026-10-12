"""构造合成 Enhanced MR 测试数据（内存中生成，不依赖患者数据）。"""
from __future__ import annotations

import numpy as np
import pytest
import pydicom
from pydicom.dataset import Dataset, FileMetaDataset
from pydicom.sequence import Sequence
from pydicom.uid import ExplicitVRLittleEndian, EnhancedMRImageStorage, generate_uid

ROWS, COLS, FRAMES = 4, 6, 3


def make_enhanced_mr(tmp_path, *, shuffle_in_stack: bool = True) -> tuple:
    """生成一个矢状位小体（位置沿 -x 推进），返回 (文件路径, 体数据, 空间帧序)。"""
    orientation = [0, 1, 0, 0, 0, -1]  # 法向量 n = r×c = (-1, 0, 0)
    # 帧按空间序：x = -10, -8, -6（投影到 n 上：10, 8, 6 → 递减；拆分后按投影升序重排）
    xs = [-10.0, -8.0, -6.0]
    volume = np.stack([np.full((ROWS, COLS), f * 100, dtype=np.uint16) + np.arange(COLS, dtype=np.uint16)
                       for f in range(FRAMES)])

    ds = Dataset()
    ds.file_meta = FileMetaDataset()
    ds.file_meta.MediaStorageSOPClassUID = EnhancedMRImageStorage
    ds.file_meta.MediaStorageSOPInstanceUID = generate_uid()
    ds.file_meta.TransferSyntaxUID = ExplicitVRLittleEndian
    ds.SOPClassUID = EnhancedMRImageStorage
    ds.SOPInstanceUID = ds.file_meta.MediaStorageSOPInstanceUID
    ds.StudyDescription = "TEST STUDY"
    ds.RequestedProcedureID = "RP ID"
    ds.SeriesDescription = "test.0.5 mm"
    ds.SeriesNumber = 5
    ds.PatientName = "Test^Patient"
    ds.PatientID = "T1"
    ds.StudyInstanceUID = generate_uid()
    ds.SeriesInstanceUID = generate_uid()
    ds.FrameOfReferenceUID = generate_uid()
    ds.StudyDate = "20260101"
    ds.Modality = "MR"
    ds.Manufacturer = "TestVendor"
    ds.NumberOfFrames = FRAMES
    ds.Rows = ROWS
    ds.Columns = COLS
    ds.SamplesPerPixel = 1
    ds.PhotometricInterpretation = "MONOCHROME2"
    ds.BitsAllocated = 16
    ds.BitsStored = 12
    ds.HighBit = 11
    ds.PixelRepresentation = 0
    ds.ImageType = ["ORIGINAL", "PRIMARY", "M", "NONE"]
    # 经典 MR 合成源
    ds.EchoPulseSequence = "GRADIENT"
    # 应被剔除的增强专属标签
    ds.DimensionOrganizationSequence = Sequence([Dataset()])
    ds.Laterality = "U"
    ds.NumberOfTemporalPositions = 1

    shared = Dataset()
    modifier = Dataset()
    modifier.InversionRecovery = "YES"
    shared.MRModifierSequence = Sequence([modifier])
    timing = Dataset()
    timing.RepetitionTime = 2500.0
    shared.MRTimingAndRelatedParametersSequence = Sequence([timing])
    ds.SharedFunctionalGroupsSequence = Sequence([shared])

    # In-Stack 故意与空间序不同（验证按法向量投影排序）
    in_stack_orders = [2, 3, 1] if shuffle_in_stack else [1, 2, 3]
    pf = []
    for i in range(FRAMES):
        item = Dataset()
        pm = Dataset()
        pm.PixelSpacing = [0.5, 0.5]
        pm.SliceThickness = 1.0
        item.PixelMeasuresSequence = Sequence([pm])
        pp = Dataset()
        pp.ImagePositionPatient = [xs[i], -5.0, 7.0]
        item.PlanePositionSequence = Sequence([pp])
        po = Dataset()
        po.ImageOrientationPatient = orientation
        item.PlaneOrientationSequence = Sequence([po])
        pvt = Dataset()
        pvt.RescaleIntercept = 0
        pvt.RescaleSlope = 1
        pvt.RescaleType = "US"
        item.PixelValueTransformationSequence = Sequence([pvt])
        voi = Dataset()
        voi.WindowCenter = 200
        voi.WindowWidth = 400
        item.FrameVOILUTSequence = Sequence([voi])
        fc = Dataset()
        fc.StackID = "1"
        fc.InStackPositionNumber = in_stack_orders[i]
        fc.TemporalPositionIndex = 1
        item.FrameContentSequence = Sequence([fc])
        pf.append(item)
    ds.PerFrameFunctionalGroupsSequence = Sequence(pf)
    ds.PixelData = volume.tobytes()
    ds["PixelData"].VR = "OW"

    path = tmp_path / "5" / "test.dcm"
    path.parent.mkdir(parents=True)
    ds.save_as(str(path), enforce_file_format=True)
    # 空间序（按法向量投影升序）下的帧下标：x=-6 → 帧2, x=-8 → 帧1, x=-10 → 帧0
    spatial_order = [2, 1, 0]
    return path, volume, spatial_order
