import math
import pathlib
from collections.abc import Mapping
from io import BytesIO
from typing import Union
from xml.etree.ElementTree import Element, ElementTree, SubElement

import cupy as cp
import numpy as np
from cucim import CuImage
from PIL import Image
from skimage.util import img_as_float32

from dz_py.util import lazyproperty


# reference: https://github.com/slideflow/slideflow/blob/master/slideflow/slide/backends/cucim.py
class DeepZoomGenerator:
    def __init__(
        self,
        path: Union[str, pathlib.Path],
        tile_size: int = 254,
        overlap: int = 1,
    ):
        self._path = path
        self._tile_size = tile_size
        self._tile_overlap = overlap
        self._reader = CuImage(self._path)

    @staticmethod
    def cucim2numpy(
        img: Union[CuImage, cp.ndarray, np.ndarray],
    ) -> np.ndarray:
        """Convert a cuCIM image to a numpy array."""
        if isinstance(img, CuImage):
            np_img = np.asarray(img)
        elif isinstance(img, np.ndarray):
            np_img = img
        else:
            if isinstance(img, cp.ndarray):
                np_img = img.get()
            else:
                raise ValueError(f"Unsupported image type: {type(img)}")
        return ((img_as_float32(np_img)) * 255).astype(np.uint8)

    @staticmethod
    def numpy2image(array: np.ndarray) -> Image.Image:
        return Image.fromarray(array).convert("RGB")

    @staticmethod
    def cucim2image(
        img: Union[CuImage, cp.ndarray, np.ndarray],
    ) -> Image.Image:
        """Convert a cuCIM image to a PIL.Image."""
        return DeepZoomGenerator.numpy2image(
            DeepZoomGenerator.cucim2numpy(img)
        )

    @lazyproperty
    def _metadata(self) -> dict:
        return self._reader.metadata["cucim"]

    def __repr__(self) -> str:
        return (
            f"{self.__class__.__name__}"
            f"({self._metadata}, "
            f"tile_size={self._tile_size}, "
            f"overlap={self._tile_overlap})"
        )

    @lazyproperty
    def resolutions(self):
        return self._metadata["resolutions"]

    @lazyproperty
    def level_count(self) -> int:
        return self.resolutions["level_count"]

    @lazyproperty
    def level_dimensions(self):
        return self.resolutions["level_dimensions"]

    @lazyproperty
    def level_downsamples(self):
        return self.resolutions["level_downsamples"]

    @lazyproperty
    def level_tile_sizes(self):
        return self.resolutions["level_tile_sizes"]

    @lazyproperty
    def dzi_level_count(self) -> int:
        sizeX = self.level_dimensions[0][0]
        sizeY = self.level_dimensions[0][1]
        return int(math.ceil(math.log(max(sizeX, sizeY)) / math.log(2)))

    @lazyproperty
    def associated_images(self) -> Mapping[str, Image.Image]:
        return {
            name: DeepZoomGenerator.cucim2image(
                self._reader.associated_image(name)
            )
            for name in self._reader.associated_images
        }

    @lazyproperty
    def mpp(self) -> float | None:
        _mpp = None
        # print(self._reader.metadata)
        for prop_key in self._reader.metadata:
            if _mpp is not None:
                break
            if "MPP" in self._reader.metadata[prop_key]:
                _mpp = self._reader.metadata[prop_key]["MPP"]
            elif "DICOM_PIXEL_SPACING" in self._reader.metadata[prop_key]:
                ps = self._reader.metadata[prop_key]["DICOM_PIXEL_SPACING"][0]
                _mpp = ps * 1000  # Convert from millimeters -> microns
            elif "spacing" in self._reader.metadata[prop_key]:
                ps = self._reader.metadata[prop_key]["spacing"]
                if isinstance(ps, (list, tuple)):
                    ps = ps[0]
                if "spacing_units" in self._reader.metadata[prop_key]:
                    spacing_unit = self._reader.metadata[prop_key][
                        "spacing_units"
                    ]
                    if isinstance(spacing_unit, (list, tuple)):
                        spacing_unit = spacing_unit[0]
                    if spacing_unit in ("mm", "millimeters", "millimeter"):
                        _mpp = ps * 1000
                    elif spacing_unit in ("cm", "centimeters", "centimeter"):
                        _mpp = ps * 10000
                    elif spacing_unit in (
                        "um",
                        "microns",
                        "micrometers",
                        "micrometer",
                    ):
                        _mpp = ps
                    else:
                        continue
        return _mpp

    def best_level_for_downsample(
        self,
        downsample: float,
    ) -> int:
        """Return lowest magnification level with a downsample level lower than
        the given target.

        Args:
            downsample (float): Ratio of target resolution to resolution
                at the highest magnification level. The downsample level of the
                highest magnification layer is equal to 1.

        Returns:
            int:    Optimal downsample level.
        """
        max_downsample = 0
        for d in self.level_downsamples:
            if d < downsample:
                max_downsample = d
        try:
            max_level = self.level_downsamples.index(max_downsample)
        except Exception:  # pylint: disable=broad-except
            print(f"Error attempting to read level {max_downsample}")
            return 0
        return max_level

    def get_level(self, level: int) -> Image.Image:
        """Return an RGB PIL.Image for a pyramid level."""
        return DeepZoomGenerator.cucim2image(
            self._reader.read_region(level=level)
        )

    def _get_region(
        self, address: tuple[int, int], lfactor: int
    ) -> tuple[dict, int, int]:
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
        sizeX = self.level_dimensions[0][0]
        sizeY = self.level_dimensions[0][1]
        if region["left"] < 0:
            width += int(region["left"] / lfactor)
            region["left"] = 0
        if region["top"] < 0:
            height += int(region["top"] / lfactor)
            region["top"] = 0
        if region["left"] >= sizeX:
            raise ValueError("x is outside layer")
        if region["top"] >= sizeY:
            raise ValueError("y is outside layer")
        if region["left"] < sizeX and region["right"] > sizeX:
            region["right"] = sizeX
            width = int(
                math.ceil(float(region["right"] - region["left"]) / lfactor)
            )
        if region["top"] < sizeY and region["bottom"] > sizeY:
            region["bottom"] = sizeY
            height = int(
                math.ceil(float(region["bottom"] - region["top"]) / lfactor)
            )
        return region, width, height

    def get_tile_at_z(self, z: int, xy: tuple[int, int]) -> Image.Image:
        """Return an RGB PIL.Image for a tile.

        z:     the pyramidal level.
        xy:    the address of the tile within the level as a (col, row)
               tuple."""
        region, _, _ = self._get_region(xy, 1)
        return self.get_level(z).crop(
            (
                region["left"],
                region["top"],
                region["right"],
                region["bottom"],
            )
        )

    def get_tile(self, level: int, address: tuple[int, int]) -> Image.Image:
        """Return an RGB PIL.Image for a tile.

        level:     the Deep Zoom level.
        address:   the address of the tile within the level as a (col, row)
                   tuple."""
        maxlevel = self.dzi_level_count
        if level < 1 or level > maxlevel:
            raise ValueError("level must be between 1 and the image scale")
        lfactor = 2 ** (maxlevel - level)
        region, width, height = self._get_region(address, lfactor)
        top_left = (region["left"], region["top"])
        ds_level = self.best_level_for_downsample(lfactor)
        ds_level_downsample = self.level_downsamples[ds_level]
        # print(lfactor, ds_level, ds_level_downsample)
        return DeepZoomGenerator.cucim2image(
            self._reader.read_region(
                location=top_left,
                size=(
                    int(width * lfactor / ds_level_downsample),
                    int(height * lfactor / ds_level_downsample),
                ),
                level=ds_level,
            )
        ).resize((width, height), resample=Image.Resampling.LANCZOS)

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
        sizeX = self.level_dimensions[0][0]
        sizeY = self.level_dimensions[0][1]
        SubElement(
            image,
            "Size",
            Width=str(sizeX),
            Height=str(sizeY),
        )
        tree = ElementTree(element=image)
        buf = BytesIO()
        tree.write(buf, encoding="UTF-8")
        return buf.getvalue().decode("UTF-8")

    def get_thumbnail(self) -> Image.Image:
        """Return a thumbnail image of the source."""
        if "thumbnail" in self._reader.associated_images:
            return DeepZoomGenerator.cucim2image(
                self._reader.associated_image("thumbnail")
            )
        else:
            raise ValueError("No thumbnail available for this image")

    @classmethod
    def can_read(cls, path: Union[str, pathlib.Path]) -> bool:
        ext = pathlib.Path(path).suffix
        return ext in (".svs", ".tif")
