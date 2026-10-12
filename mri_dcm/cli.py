"""命令行入口：decompress / split / convert（两步连做）。"""
from __future__ import annotations

import argparse
import sys
from pathlib import Path


def _build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(
        prog="mri_dcm",
        description="7T MRI DICOM 转换工具：(1) 解压 JPEG Lossless 增强 MR；(2) 拆分为经典单帧 MR 以获得最大兼容性",
    )
    sub = parser.add_subparsers(dest="command", required=True)

    p1 = sub.add_parser("decompress", help="步骤 1：压缩 DICOM → 未压缩 Explicit VR Little Endian")
    p1.add_argument("input", type=Path, help="输入目录（含压缩 DICOM）")
    p1.add_argument("output", type=Path, help="输出目录")

    p2 = sub.add_parser("split", help="步骤 2：Enhanced MR 多帧 → 经典 MR 单帧（ImageJ 等兼容）")
    p2.add_argument("input", type=Path, help="输入目录（压缩或已解压均可）")
    p2.add_argument("output", type=Path, help="输出目录")

    p3 = sub.add_parser("convert", help="两步连做：decompress + split")
    p3.add_argument("input", type=Path, help="输入目录（含压缩 DICOM）")
    p3.add_argument("output_decompressed", type=Path, help="步骤 1 输出目录")
    p3.add_argument("output_split", type=Path, help="步骤 2 输出目录")
    return parser


def main(argv: list[str] | None = None) -> int:
    args = _build_parser().parse_args(argv)
    from .decompress import decompress_tree
    from .split import split_tree

    try:
        if args.command == "decompress":
            files = decompress_tree(args.input, args.output)
            print(f"[decompress] 完成：{len(files)} 个序列 → {args.output}")
        elif args.command == "split":
            files = split_tree(args.input, args.output)
            print(f"[split] 完成：{len(files)} 个单帧文件 → {args.output}")
        elif args.command == "convert":
            files1 = decompress_tree(args.input, args.output_decompressed)
            files2 = split_tree(args.output_decompressed, args.output_split)
            print(f"[convert] 步骤 1：{len(files1)} 个序列 → {args.output_decompressed}")
            print(f"[convert] 步骤 2：{len(files2)} 个单帧文件 → {args.output_split}")
    except Exception as e:  # noqa: BLE001
        print(f"错误: {e}", file=sys.stderr)
        return 1
    return 0


if __name__ == "__main__":
    sys.exit(main())
