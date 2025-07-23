import large_image
import pathlib
from PIL import Image, ImageCms
from io import BytesIO
import math
from xml.etree.ElementTree import Element, ElementTree, SubElement

from typing import Union
from collections.abc import Mapping
from .util import lazyproperty

class DeepZoomGenerator:
    def __init__(self, path: Union[str, pathlib.Path], tile_size: int = 254, overlap: int = 1, limit_bounds = True):
        self._path = path
        self._tile_size = tile_size
        self._tile_overlap = overlap
        self._limit_bounds = limit_bounds
    @lazyproperty
    def _tile_source(self) -> large_image.tilesource.TileSource:
        # https://github.com/girder/large_image/blob/master/large_image/tilesource/base.py#L37
        if self._limit_bounds:
            return large_image.getTileSource(self._path, edge='crop') # crop edge means limit bound to non-empty region
        else:
            return large_image.getTileSource(self._path)
    
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
    

    @lazyproperty
    def get_icc_profile(self) -> ImageCms.ImageCmsProfile | None:
        """
        Get a list of all ICC profiles that are available for the source, or
        get a specific profile.

        :param idx: a 0-based index into the profiles to get one profile, or
            None to get a list of all profiles.
        :returns: either one or a list of PIL.ImageCms.CmsProfile objects, or
            None if no profiles are available.  If a list, entries in the list
            may be None.
        """
        profiles = self._tile_source.getICCProfiles()
        if profiles is None:
            return None
        for profile in profiles:
            if profile:
                return profile
            

    @lazyproperty
    def associated_images(self) -> Mapping[str, Image.Image]:
        associated_images_list = self._tile_source.getAssociatedImagesList()
        if len(associated_images_list) == 0:
            return {}
        else:
            return {name: self._tile_source._getAssociatedImage(name) for name in associated_images_list}


    def get_tile_at_z(self, z: int, xy: tuple[int, int]) -> Image.Image:
        """Return an RGB PIL.Image for a tile.

        z:     the pyramidal level.
        xy:    the address of the tile within the level as a (col, row)
               tuple."""
        return self._tile_source.getTile(xy[0], xy[1], z, True).convert("RGB")
    

    def get_tile(self, level: int, address: tuple[int, int]) -> Image.Image:
        """Return an RGB PIL.Image for a tile.

        level:     the Deep Zoom level.
        address:   the address of the tile within the level as a (col, row)
                   tuple."""
        # https://github.com/girder/large_image/blob/master/girder/girder_large_image/rest/tiles.py#L645
        maxlevel = int(math.ceil(math.log(max(self._metadata['sizeX'], self._metadata['sizeY'])) / math.log(2)))
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
        """Return a string containing the XML metadata for the .dzi file."""
        # pylint: disable=unused-variable
        image = Element(
            "Image",
            TileSize=str(self._tile_size),
            Overlap=str(self._tile_overlap),
            Format='jpeg',
            xmlns="http://schemas.microsoft.com/deepzoom/2008",
        )
        SubElement(image, "Size", Width=str(self._metadata['sizeX']), Height=str(self._metadata['sizeY']))
        tree = ElementTree(element=image)
        buf = BytesIO()
        tree.write(buf, encoding="UTF-8")
        return buf.getvalue().decode("UTF-8")
            

    @classmethod
    def canRead(cls, path: Union[str, pathlib.Path]) -> bool:
        return large_image.tilesource.canRead(path)
