import os
import sys

import openslide.deepzoom

sys.path.insert(0, os.path.abspath(".."))

import base64
from io import BytesIO

import openslide

from cucim_py.deepzoom import DeepZoomGenerator as DeepZoomGeneratorCu
from dz_py.deepzoom import DeepZoomGenerator

dz = DeepZoomGenerator(sys.argv[1])
print(dz)

dzi = dz.get_dzi()
print(dzi)

print(dz.level_count, dz.dzi_level_count, dz.mpp)

tile = dz.get_tile((dz.dzi_level_count - 1) // 2, (0, 0))
# tile = dz.get_tile((dz.level_count - 1) // 2, (0, 0))
buffered = BytesIO()
tile.save(buffered, format="JPEG")
tile_base64 = "data:image/JPEG;base64," + base64.b64encode(
    buffered.getvalue()
).decode("utf-8")
print(tile_base64)

slide1 = openslide.open_slide(sys.argv[1])
dz1 = openslide.deepzoom.DeepZoomGenerator(slide1)
l = dz1.level_count - 1
l //= 2
w, h = dz1.level_dimensions[l]
w //= 256
h //= 256
print(l, w, h)
tile1 = dz1.get_tile(l, (w // 2, h // 2))
buffered1 = BytesIO()
tile1.save(buffered1, format="JPEG")
tile_base64_1 = "data:image/JPEG;base64," + base64.b64encode(
    buffered1.getvalue()
).decode("utf-8")
print(tile_base64_1)

dz_cu = DeepZoomGeneratorCu(sys.argv[1])
print(dz_cu)

dzi2 = dz_cu.get_dzi()
print(dzi2)
print(dz_cu.level_count, dz_cu.dzi_level_count, dz_cu.mpp)
tile_cu = dz_cu.get_tile((dz_cu.dzi_level_count - 1) // 2, (0, 0))
buffered_cu = BytesIO()
tile_cu.save(buffered_cu, format="JPEG")
tile_base64_cu = "data:image/JPEG;base64," + base64.b64encode(
    buffered_cu.getvalue()
).decode("utf-8")
print(tile_base64_cu)
