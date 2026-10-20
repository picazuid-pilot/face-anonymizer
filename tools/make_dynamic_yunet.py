#!/usr/bin/env python3
"""Maakt browser-extension/models/yunet.onnx uit het officiële YuNet-model van OpenCV.

Het origineel (face_detection_yunet_2023mar.onnx, MIT-licentie, van
https://github.com/opencv/opencv_zoo/tree/main/models/face_detection_yunet) heeft een
vaste invoer van 640×640. De gewichten en bewerkingen blijven precies gelijk; alleen de
vormen van in- en uitvoer worden variabel (H×W, veelvouden van 32), zodat de browser en
de telefoon-app het echte beeldformaat kunnen gebruiken in plaats van een opgevuld vierkant.

Gebruik:  pip install onnx
          python tools/make_dynamic_yunet.py face_detection_yunet_2023mar.onnx browser-extension/models/yunet.onnx
"""
import sys

import onnx


def make_dynamic(src, dst):
    m = onnx.load(src)
    dims = m.graph.input[0].type.tensor_type.shape.dim
    dims[2].dim_param, dims[3].dim_param = "H", "W"
    for out in m.graph.output:
        out.type.tensor_type.shape.dim[1].dim_param = "N"
    # Tussenvormen gelden voor 640×640; laat ONNX Runtime ze zelf afleiden
    del m.graph.value_info[:]
    onnx.checker.check_model(m)
    onnx.save(m, dst)


if __name__ == "__main__":
    if len(sys.argv) != 3:
        sys.exit(__doc__)
    make_dynamic(sys.argv[1], sys.argv[2])
