import large_image
import pathlib
from PIL import Image
from io import BytesIO
import math
from xml.etree.ElementTree import Element, ElementTree, SubElement

from typing import List, Tuple, Union, Optional
from .util import lazyproperty

class DeepZoomGenerator:
    def __init__(self, path: Union[str, pathlib.Path], tile_size: int = 254, overlap: int = 1):
        self._path = path
        self._tile_size = tile_size
        self._tile_overlap = overlap
    @lazyproperty
    def _tile_source(self) -> large_image.tilesource.TileSource:
        # https://github.com/girder/large_image/blob/master/large_image/tilesource/base.py#L37
        return large_image.getTileSource(self._path, edge='crop') # crop edge means limit bound to non-empty region
    
    @lazyproperty
    def _metadata(self) -> dict:
        return self._tile_source.getMetadata()
        

    def __repr__(self) -> str:
        return "{}({!r}, tile_size={!r}, overlap={!r})".format(
            self.__class__.__name__, self._metadata, self._tile_size, self._tile_overlap
        )

    @lazyproperty
    def level_count(self) -> int:
        return self._metadata["levels"]
    
    @lazyproperty
    def dzi_level_count(self) -> int:
        return int(math.ceil(math.log(max(self._metadata['sizeX'], self._metadata['sizeY'])) / math.log(2)))


    def get_tile(self, z: int, xy: tuple[int, int]) -> Image.Image:
        """Return an RGB PIL.Image for a tile.

        z:     the pyramidal level.
        xy:    the address of the tile within the level as a (col, row)
               tuple."""
        return self._tile_source.getTile(xy[0], xy[1], z, True).convert("RGB")
    

    def get_dzi_tile(self, level: int, address: tuple[int, int]) -> Image.Image:
        """Return an RGB PIL.Image for a tile.

        level:     the Deep Zoom level.
        address:   the address of the tile within the level as a (col, row)
                   tuple."""
        # https://github.com/girder/large_image/blob/master/girder/girder_large_image/rest/tiles.py#L645
        maxlevel = int(math.ceil(math.log(max(self._metadata['sizeX'], self._metadata['sizeY'])) / math.log(2)))
        print(level, maxlevel)
        if level < 1 or level > maxlevel:
            raise 'level must be between 1 and the image scale'
        lfactor = 2 ** (maxlevel - level)
        x, y = address
        region = {
            'left': (x * self._tile_size - self._tile_overlap) * lfactor,
            'top': (y * self._tile_size - self._tile_overlap) * lfactor,
            'right': ((x + 1) * self._tile_size + self._tile_overlap) * lfactor,
            'bottom': ((y + 1) * self._tile_size + self._tile_overlap) * lfactor,
        }
        width = height = self._tile_size + self._tile_overlap * 2
        if region['left'] < 0:
            width += int(region['left'] / lfactor)
            region['left'] = 0
        if region['top'] < 0:
            height += int(region['top'] / lfactor)
            region['top'] = 0
        if region['left'] >= self._metadata['sizeX']:
            raise 'x is outside layer'
        if region['top'] >= self._metadata['sizeY']:
            raise 'y is outside layer'
        if region['left'] < self._metadata['sizeX'] and region['right'] > self._metadata['sizeX']:
            region['right'] = self._metadata['sizeX']
            width = int(math.ceil(float(region['right'] - region['left']) / lfactor))
        if region['top'] < self._metadata['sizeY'] and region['bottom'] > self._metadata['sizeY']:
            region['bottom'] = self._metadata['sizeY']
            height = int(math.ceil(float(region['bottom'] - region['top']) / lfactor))
        regionData, _ = self._tile_source.getRegion(region=region, output=dict(maxWidth=width, maxHeight=height), format=large_image.tilesource.TILE_FORMAT_PIL,
            jpegQuality=100)
        return regionData.convert('RGB')


    def get_dzi(self, format: str) -> str:
        """Return a string containing the XML metadata for the .dzi file.

        format:    the format of the individual tiles ('png' or 'jpeg')"""
        image = Element(
            "Image",
            TileSize=str(self._tile_size),
            Overlap=str(self._tile_overlap),
            Format=format,
            xmlns="http://schemas.microsoft.com/deepzoom/2008",
        )
        SubElement(image, "Size", Width=str(self._metadata['sizeX']), Height=str(self._metadata['sizeY']))
        tree = ElementTree(element=image)
        buf = BytesIO()
        tree.write(buf, encoding="UTF-8")
        return buf.getvalue().decode("UTF-8")
