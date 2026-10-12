#!/usr/bin/env python3
"""Deep-compare a compressed source file and its exported reference counterpart."""
import sys

import pydicom
from pydicom.dataset import Dataset


def flat(ds: Dataset, prefix: str = ""):
    """Yield (tag_path, value_repr) for every element recursively."""
    out = {}
    for elem in ds:
        if elem.tag == (0x7FE0, 0x0010):  # pixel data
            out[prefix + str(elem.tag)] = f"<PixelData VR={elem.VR}>"
            continue
        key = f"{prefix}{elem.tag} {elem.name}"
        if elem.VR == "SQ":
            for i, item in enumerate(elem.value):
                out.update(flat(item, prefix=f"{key}[{i}]/"))
        else:
            out[key] = repr(elem.value)
    return out


def main():
    src_path, ref_path = sys.argv[1], sys.argv[2]
    src = pydicom.dcmread(src_path)
    ref = pydicom.dcmread(ref_path)

    print("--- file_meta ---")
    for name in ("TransferSyntaxUID", "ImplementationClassUID", "ImplementationVersionName"):
        s = getattr(src.file_meta, name, None) if hasattr(src.file_meta, name) else None
        # pydicom 3: ImplementationVersionName may be absent
        s_v = src.file_meta.get(name)
        r_v = ref.file_meta.get(name)
        if str(s_v) != str(r_v):
            print(f"  DIFF {name}: src={s_v} ref={r_v}")
        else:
            print(f"  same {name}: {s_v}")

    fs, fr = flat(src), flat(ref)
    keys = sorted(set(fs) | set(fr))
    n_diff = n_same = 0
    for k in keys:
        if k not in fr:
            print(f"  ONLY-IN-SRC {k} = {fs[k][:80]}")
            n_diff += 1
        elif k not in fs:
            print(f"  ONLY-IN-REF {k} = {fr[k][:80]}")
            n_diff += 1
        elif fs[k] != fr[k]:
            print(f"  CHANGED {k}: src={fs[k][:60]} ref={fr[k][:60]}")
            n_diff += 1
        else:
            n_same += 1
    print(f"\nsummary: {n_same} identical, {n_diff} differing/unique elements")

    # pixel data identity check
    import numpy as np
    a, b = src.pixel_array, ref.pixel_array
    if a.shape == b.shape:
        print("pixel identical:", np.array_equal(a, b),
              "| src range:", (int(a.min()), int(a.max())),
              "| ref range:", (int(b.min()), int(b.max())))
    else:
        print("pixel shape mismatch:", a.shape, b.shape)


if __name__ == "__main__":
    main()
