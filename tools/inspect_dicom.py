#!/usr/bin/env python3
"""Inspect DICOM files: transfer syntax, dimensions, compression info."""
import sys
from pathlib import Path

import pydicom
from pydicom.uid import UID


def inspect(path: Path) -> dict:
    ds = pydicom.dcmread(str(path), stop_before_pixels=True)
    tsyntax = ds.file_meta.TransferSyntaxUID
    info = {
        "path": str(path),
        "TransferSyntax": f"{tsyntax} ({tsyntax.name})",
        "SOPClassUID": UID(ds.SOPClassUID).name,
        "Rows": ds.get("Rows"),
        "Columns": ds.get("Columns"),
        "NumberOfFrames": ds.get("NumberOfFrames", 1),
        "PixelSpacing": str(ds.get("PixelSpacing")),
        "SliceThickness": str(ds.get("SliceThickness")),
        "SpacingBetweenSlices": str(ds.get("SpacingBetweenSlices")),
        "SeriesDescription": str(ds.get("SeriesDescription", "")),
        "SeriesNumber": str(ds.get("SeriesNumber", "")),
        "Modality": str(ds.get("Modality", "")),
        "Manufacturer": str(ds.get("Manufacturer", "")),
        "BitsAllocated": ds.get("BitsAllocated"),
        "PixelRepresentation": ds.get("PixelRepresentation"),
        "PhotometricInterpretation": str(ds.get("PhotometricInterpretation", "")),
        "PatientName": str(ds.get("PatientName", "")),
        "StudyDescription": str(ds.get("StudyDescription", "")),
    }
    return info


def main():
    paths = [Path(p) for p in sys.argv[1:]]
    for p in paths:
        try:
            info = inspect(p)
            print(f"=== {p}")
            for k, v in info.items():
                if k != "path":
                    print(f"  {k}: {v}")
        except Exception as e:
            print(f"=== {p}\n  ERROR: {e}")
        print()


if __name__ == "__main__":
    main()
