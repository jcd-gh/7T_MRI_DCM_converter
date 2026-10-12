#!/usr/bin/env python3
"""验证步骤 1 输出与参考导出目录的一致性。

对每个序列：目录/文件命名一致、全部 DICOM 元素一致（file_meta 的 Implementation*
除外——参考工具伪装为 DCMTK，本工具如实写 pydicom 身份）、像素逐位一致。

用法：verify_step1.py <我们的输出目录> <参考导出目录>
"""
from __future__ import annotations

import sys
from pathlib import Path

import numpy as np
import pydicom

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))
from tools.compare_tags import flat  # noqa: E402

IGNORED_META = {"ImplementationClassUID", "ImplementationVersionName", "FileMetaInformationVersion"}


def verify_pair(ours: Path, ref: Path) -> list[str]:
    problems: list[str] = []
    ds_a, ds_b = pydicom.dcmread(str(ours)), pydicom.dcmread(str(ref))

    if str(ds_a.file_meta.TransferSyntaxUID) != str(ds_b.file_meta.TransferSyntaxUID):
        problems.append(f"TransferSyntax 不一致: {ds_a.file_meta.TransferSyntaxUID} vs {ds_b.file_meta.TransferSyntaxUID}")
    # file_meta 的 Implementation* 有意不同：参考工具伪装 DCMTK 身份，本工具如实写 pydicom 身份

    fa, fb = flat(ds_a), flat(ds_b)
    for k in sorted(set(fa) | set(fb)):
        if fa.get(k) != fb.get(k):
            problems.append(f"元素差异 {k}: ours={str(fa.get(k))[:60]} ref={str(fb.get(k))[:60]}")

    pa, pb = ds_a.pixel_array, ds_b.pixel_array
    if pa.shape != pb.shape:
        problems.append(f"像素形状不一致: {pa.shape} vs {pb.shape}")
    elif not np.array_equal(pa, pb):
        problems.append("像素数据存在差异")
    return problems


def main() -> int:
    ours_root, ref_root = Path(sys.argv[1]), Path(sys.argv[2])
    ours_files = sorted(ours_root.rglob("*.dcm"))
    ref_files = sorted(ref_root.rglob("*.dcm"))
    ours_rel = {str(p.relative_to(ours_root)) for p in ours_files}
    ref_rel = {str(p.relative_to(ref_root)) for p in ref_files}
    failed = 0
    if ours_rel != ref_rel:
        print(f"[FAIL] 目录结构不一致\n  仅我方有: {sorted(ours_rel - ref_rel)}\n  仅参考有: {sorted(ref_rel - ours_rel)}")
        failed += 1
    for rel in sorted(ours_rel & ref_rel):
        problems = verify_pair(ours_root / rel, ref_root / rel)
        if problems:
            failed += 1
            print(f"[FAIL] {rel}")
            for p in problems[:20]:
                print(f"    {p}")
            if len(problems) > 20:
                print(f"    ... 共 {len(problems)} 项")
        else:
            print(f"[OK]   {rel}")
    print(f"\n{'全部通过' if failed == 0 else f'{failed} 个文件未通过'}")
    return 1 if failed else 0


if __name__ == "__main__":
    sys.exit(main())
