# 数据分析结论（数据勘察阶段，已匿名化）

对象：某院 7T MRI（Siemens MAGNETOM Terra.X, syngo MR XA60）科研数据集
（下述序列名等均为协议名称，不含患者标识）。

## 输入 `data/input_compressed/`（原始压缩数据）

5 个序列，每序列 1 个 DICOM 文件（按扫描序号分目录）：

| 目录 | SeriesNumber | SeriesDescription | Rows×Cols | Frames | 体素 (mm) |
|---|---|---|---|---|---|
| 1 | 1 | AAhead_scout | 160×160 | 128 | 1.625×1.625×1.6 |
| 5 | 5 | t1_mprage_0.71mm_cs | 352×360 | 288 | 0.71 iso |
| 6 | 6 | t2_tse_tra_DRB | 1280×1280 | 50 | 0.172×0.172×2.591 |
| 7 | 7 | t2_fs_space_hertz_0.7mm | 320×300 | 256 | 0.7 iso |
| 11 | 11 | t1_mprage_0.71mm_cs +C | 352×360 | 288 | 0.71 iso |

技术特征：

- SOP Class：**Enhanced MR Image Storage** (1.2.840.10008.5.1.4.1.1.4.1) 多帧
- Transfer Syntax：**JPEG Lossless, Process 14 SV1** (1.2.840.10008.1.2.4.70)，封装式像素数据
- 16 bit unsigned，MONOCHROME2
- 几何信息全部位于 Shared/Per-Frame Functional Groups（每帧 PlanePosition / PlaneOrientation / PixelMeasures / FrameVOILUT / PixelValueTransformation），顶层无 ImagePositionPatient / PixelSpacing
- 全部序列单 Stack、单时间点
- 注意：scout 与 MPRAGE 为矢状面采集，帧间推进方向沿层面法向量（z 坐标近似不变），排序必须用位置在法向量上的投影，不能按 z 排序

## 参考输出（临床导出软件产出的解压数据）

结构 `{StudyDescription} - {RequestedProcedureID 空格→下划线}/<series>/IM-XXXX-0001.dcm`
（series 目录名 = SeriesDescription 去掉小数点、空格转下划线 + `_SeriesNumber`；
IM 第一段数字为按 SeriesNumber 排序后的 1 基序号）。

与源文件的差异（对其中 1 个序列全量逐元素对比，共 8012 个元素）：

| 项 | 源 | 参考导出 |
|---|---|---|
| TransferSyntaxUID | 1.2.840.10008.1.2.4.70 | 1.2.840.10008.1.2.1 (Explicit VR LE) |
| PixelData | 封装式 OB（JPEG Lossless） | 原生未压缩 OW |
| ImplementationClassUID | 1.3.12.2.1107.5.8.2 (Siemens) | 1.2.276.0.7230010.3.0.3.7.0 (DCMTK) |
| ImplementationVersionName | SHC_PLAZA_VB30E | OFFIS_DCMTK_370 |

其余全部元素逐一致，像素数据逐位一致（dtype uint16，该序列取值范围 0–372）。
即：**步骤 1 = 纯解压转储**（解码 JPEG Lossless → Explicit VR Little Endian 原生像素），参考工具基于 DCMTK 3.7.0。

## 步骤 2 设计（拆分以获得最大兼容性）

Enhanced MR 多帧文件很多老软件（含 ImageJ 内建 DICOM 阅读器）无法正确打开或丢失几何。
拆分为经典 **MR Image Storage** (1.2.840.10008.5.1.4.1.1.4) 单帧文件、Explicit VR Little Endian：

- 每帧一个文件，SOPInstanceUID 新生成，SeriesInstanceUID 沿用（保证序列归属）
- ImagePositionPatient / ImageOrientationPatient ← 每帧 PlanePosition / PlaneOrientation
- PixelSpacing / SliceThickness / SpacingBetweenSlices ← PixelMeasures（shared 或 per-frame）
- Rescale* ← PixelValueTransformationSequence；WindowCenter/Width ← FrameVOILUTSequence
- EchoTime ← MREchoSequence；InstanceNumber ← 按层面法向量投影排序后的 1..N
- 剔除全部 Enhanced 专属标签（Functional Groups、Pixel Presentation、Volumetric Properties、0018,9xxx 增强模块等）与 NumberOfFrames
