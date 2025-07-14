import sys, os

import openslide.deepzoom

sys.path.insert(0, os.path.abspath(".."))

from dz_py.deepzoom import DeepZoomGenerator

import base64
from io import BytesIO

import openslide

dz = DeepZoomGenerator(sys.argv[1])
print(dz)

dzi = dz.get_dzi("jpg")
print(dzi)

print(dz.level_count, dz.dzi_level_count)

tile = dz.get_dzi_tile((dz.dzi_level_count - 1) // 2, (0, 0))
#tile = dz.get_tile((dz.level_count - 1) // 2, (0, 0))
buffered = BytesIO()
tile.save(buffered, format="JPEG")
tile_base64 = "data:image/JPEG;base64," + base64.b64encode(buffered.getvalue()).decode(
    "utf-8"
)
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
tile_base64_1 = "data:image/JPEG;base64," + base64.b64encode(buffered1.getvalue()).decode(
    "utf-8"
)
print(tile_base64_1)
