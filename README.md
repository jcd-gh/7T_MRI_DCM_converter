# 7T MRI DICOM 转换工具

处理 7T MRI 增强型 DICOM 数据（Siemens MAGNETOM 系列扫描仪），完成两步转换：

1. **decompress（步骤 1）**：把 JPEG Lossless（Process 14 SV1）压缩封装的
   Enhanced MR 多帧文件解压为未压缩 Explicit VR Little Endian，目录/文件命名
   复现临床导出软件（DCMTK 系）的参考布局。
2. **split（步骤 2）**：把 Enhanced MR 多帧文件拆分为**经典 MR Image Storage
   单帧文件**，ImageJ/Fiji（内建 DICOM 阅读器）等各类软件均可直接识别并正确
   堆叠为三维体。

## 支持的数据与设备

| 项 | 说明 |
|---|---|
| 已实测 | Siemens MAGNETOM Terra.X 7T（syngo MR XA60）脑 MRI；Enhanced MR Image Storage 多帧；JPEG Lossless Process 14 SV1 压缩与未压缩输入 |
| 输入 SOP Class | Enhanced MR Image Storage（1.2.840.10008.5.1.4.1.1.4.1）多帧 |
| 输入传输语法 | 任何 pydicom/pylibjpeg 可解码的压缩语法（JPEG Lossless 14 / 14 SV1、JPEG Baseline / Extended；JPEG-LS；JPEG 2000 需另装 `pylibjpeg-openjpeg`），或原生未压缩 |
| 扫描仪厂商 | 基于 DICOM 标准功能性组序列提取几何，不依赖厂商；Siemens CSA 私有标签仅用于合成经典枚举标签且带回退，GE / Philips 等其他厂商的 Enhanced MR 预期同样适用（未实测） |
| 扫描方位 | 任意（轴向 / 矢状 / 冠状 / 斜面），按层面法向量投影排序 |
| 输出 | 经典 MR Image Storage（1.2.840.10008.5.1.4.1.1.4）单帧、Explicit VR Little Endian |

## 使用

```bash
# 准备环境（虚拟环境位于项目目录内，不污染系统 Python）
python3 -m venv .venv
.venv/bin/pip install -r requirements.txt

# 建议把数据放到 data/ 目录（已被 .gitignore 排除，不会入库）
# 步骤 1：压缩 DICOM → 未压缩 Explicit VR Little Endian
.venv/bin/python -m mri_dcm decompress data/input_compressed out_decompressed

# 步骤 2：单文件三维 DICOM → 拆分为多张单帧文件（输入用压缩或解压目录均可）
.venv/bin/python -m mri_dcm split out_decompressed out_split

# 或两步连做
.venv/bin/python -m mri_dcm convert data/input_compressed out_decompressed out_split
```

## 输出布局（复现参考导出软件）

```
{StudyDescription 空格→下划线} - {RequestedProcedureID 空格→下划线}/
    {SeriesDescription 去小数点空格→下划线}_{SeriesNumber}/
        IM-{序列序号4位}-{图像号4位}.dcm     # 步骤 2 中图像号 = 1..层数
```

## 步骤 2 的兼容性设计

| 项 | 处理 |
|---|---|
| SOP Class | Enhanced MR (1.2.840.10008.5.1.4.1.1.4.1) → 经典 MR Image Storage (…1.1.4) |
| 传输语法 | 一律 Explicit VR Little Endian（未压缩，兼容性最好） |
| 几何 | 每帧 ImagePosition/ImageOrientation 从 Plane Position/Orientation Sequence 提取 |
| 层序 | 按层面法向量（行×列方向余弦的叉乘）投影排序——正确处理矢状位等任意方位 |
| 层距 | 用相邻帧投影差的中位数计算（比 SpacingBetweenSlices 标签更精确） |
| 必需枚举 | ScanningSequence/SequenceVariant 由增强属性合成（GRADIENT→GR、SPIN→SE、InversionRecovery→IR；Siemens CSA 私有标签可用时取经典值） |
| 冗余剔除 | Functional Groups、Pixel Presentation、Dimension Organization 等增强专属标签全部移除；恒等 Rescale（0/1）不写 |
| 标识 | 每层新 SOPInstanceUID；SeriesInstanceUID 沿用以保持序列归属 |

## 验证结论（详见 reports/，已去除数据集标识）

- **步骤 1**：5 个序列与参考导出逐元素一致（8012+ 元素）、像素逐位一致、目录
  命名逐字一致。唯一有意差异：file_meta 的 Implementation* 标识——参考工具写
  DCMTK 身份，本工具如实写 pydicom 身份。
- **步骤 2**：1010 个单帧文件；每层像素与源体逐位一致；层距均匀（scout 1.6 /
  MPRAGE 0.71 / T2 2.6 / SPACE 0.7 mm）；dicom-validator（DICOM 2026d 版）
  校验 MR Image IOD **零错误**；压缩目录与解压目录两种输入拆分结果完全一致。
- 单元测试：`​.venv/bin/python -m pytest tests/ -q`（合成数据，不含任何真实患者数据）。

## 目录结构

```
mri_dcm/            转换包（decompress 步骤1 / split 步骤2 / naming / geometry / cli）
tools/              勘察与端到端验证脚本（inspect/compare/verify_step1/verify_step2）
tests/              pytest 单元测试（合成数据）
reports/            端到端验证报告
ANALYSIS.md         数据勘察结论（已匿名化）
```

## 隐私与安全

- 患者数据（`data/`、`out_*/` 生成结果）已在 `.gitignore` 中排除，绝不入库。
- 仓库内文档、代码、测试、报告均已去除数据集的患者/机构标识。
- 所有转换仅在指定输入/输出目录内进行。

## 依赖

见 `requirements.txt`：pydicom、numpy、pylibjpeg(+libjpeg 插件，JPEG Lossless 解码)；
开发/验证另用 pytest、dicom-validator。
