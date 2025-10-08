import math
import pathlib
from collections.abc import Mapping
from io import BytesIO
from typing import Union
from xml.etree.ElementTree import Element, ElementTree, SubElement

import large_image
from PIL import Image, ImageCms

from .util import lazyproperty


class DeepZoomGenerator:
    def __init__(
        self,
        path: Union[str, pathlib.Path],
        tile_size: int = 254,
        overlap: int = 1,
        limit_bounds=True,
    ):
        self._path = path
        self._tile_size = tile_size
        self._tile_overlap = overlap
        self._limit_bounds = limit_bounds

    @lazyproperty
    def _tile_source(self) -> large_image.tilesource.TileSource:
        # https://github.com/girder/large_image/blob/master/large_image/tilesource/base.py#L37
        if self._limit_bounds:
            return large_image.getTileSource(
                self._path, edge="crop"
            )  # crop edge means limit bound to non-empty region
        else:
            return large_image.getTileSource(self._path)

    @lazyproperty
    def _metadata(self) -> dict:
        return self._tile_source.getMetadata()

    def __repr__(self) -> str:
        return (
            f"{self.__class__.__name__}"
            f"({self._metadata}, "
            f"tile_size={self._tile_size}, "
            f"overlap={self._tile_overlap})"
        )

    @lazyproperty
    def level_count(self) -> int:
        return self._metadata["levels"]

    @lazyproperty
    def dzi_level_count(self) -> int:
        return int(
            math.ceil(
                math.log(max(self._metadata["sizeX"], self._metadata["sizeY"]))
                / math.log(2)
            )
        )

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
        return None

    @lazyproperty
    def associated_images(self) -> Mapping[str, Image.Image]:
        associated_images_list = self._tile_source.getAssociatedImagesList()
        if len(associated_images_list) == 0:
            return {}
        else:
            return {
                # pylint: disable=protected-access
                name: self._tile_source._getAssociatedImage(name)
                for name in associated_images_list
            }

    @lazyproperty
    def mpp(self) -> float | None:
        mm_x = self._metadata.get("mm_x")
        mm_y = self._metadata.get("mm_y")
        if mm_x and mm_y:
            return (mm_x + mm_y) * 500.0
        if mm_x:
            return mm_x * 1000.0
        if mm_y:
            return mm_y * 1000.0
        return None

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
        maxlevel = int(
            math.ceil(
                math.log(max(self._metadata["sizeX"], self._metadata["sizeY"]))
                / math.log(2)
            )
        )
        if level < 1 or level > maxlevel:
            raise ValueError("level must be between 1 and the image scale")
        lfactor = 2 ** (maxlevel - level)
        x, y = address
        region = {
            "left": (x * self._tile_size - self._tile_overlap) * lfactor,
            "top": (y * self._tile_size - self._tile_overlap) * lfactor,
            "right": (
                ((x + 1) * self._tile_size + self._tile_overlap) * lfactor
            ),
            "bottom": (
                ((y + 1) * self._tile_size + self._tile_overlap) * lfactor
            ),
        }
        width = height = self._tile_size + self._tile_overlap * 2
        if region["left"] < 0:
            width += int(region["left"] / lfactor)
            region["left"] = 0
        if region["top"] < 0:
            height += int(region["top"] / lfactor)
            region["top"] = 0
        if region["left"] >= self._metadata["sizeX"]:
            raise ValueError("x is outside layer")
        if region["top"] >= self._metadata["sizeY"]:
            raise ValueError("y is outside layer")
        if (
            region["left"] < self._metadata["sizeX"]
            and region["right"] > self._metadata["sizeX"]
        ):
            region["right"] = self._metadata["sizeX"]
            width = int(
                math.ceil(float(region["right"] - region["left"]) / lfactor)
            )
        if (
            region["top"] < self._metadata["sizeY"]
            and region["bottom"] > self._metadata["sizeY"]
        ):
            region["bottom"] = self._metadata["sizeY"]
            height = int(
                math.ceil(float(region["bottom"] - region["top"]) / lfactor)
            )
        region_data, _ = self._tile_source.getRegion(
            region=region,
            output=dict(maxWidth=width, maxHeight=height),
            format=large_image.tilesource.TILE_FORMAT_PIL,
            jpegQuality=100,
        )
        return region_data.convert("RGB")

    def get_dzi(
        self, _format: str = "jpeg"  # pylint: disable=unused-variable
    ) -> str:
        """Return a string containing the XML metadata for the .dzi file."""
        image = Element(
            "Image",
            TileSize=str(self._tile_size),
            Overlap=str(self._tile_overlap),
            Format="jpeg",
            xmlns="http://schemas.microsoft.com/deepzoom/2008",
        )
        SubElement(
            image,
            "Size",
            Width=str(self._metadata["sizeX"]),
            Height=str(self._metadata["sizeY"]),
        )
        tree = ElementTree(element=image)
        buf = BytesIO()
        tree.write(buf, encoding="UTF-8")
        return buf.getvalue().decode("UTF-8")

    def get_thumbnail(self) -> Image.Image:
        """Return a thumbnail image of the source."""
        thumbnail, _ = self._tile_source.getThumbnail(
            width=1024,
            height=1024,
            format=large_image.tilesource.TILE_FORMAT_PIL,
            jpegQuality=100,
        )
        if thumbnail is None:
            raise ValueError("No thumbnail available for this image")
        return thumbnail.convert("RGB")

    @classmethod
    def can_read(cls, path: Union[str, pathlib.Path]) -> bool:
        return large_image.tilesource.canRead(path)
