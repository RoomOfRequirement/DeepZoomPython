import json
import sys

from cucim import CuImage

img = CuImage(sys.argv[1])

print(img.is_loaded)  # True if image data is loaded & available.
print(img.device)  # A device type.
print(img.ndim)  # The number of dimensions.
print(img.dims)  # A string containing a list of dimensions being requested.
print(img.shape)  # A tuple of dimension sizes (in the order of `dims`).
print(
    img.size("XYC")
)  # Returns size as a tuple for the given dimension order.
print(img.dtype)  # The data type of the image.
print(img.channel_names)  # A channel name list.
print(img.spacing())  # Returns physical size in tuple.
print(
    img.spacing_units()
)  # Units for each spacing element (size is same with `ndim`).
print(img.origin)  # Physical location of (0, 0, 0) (size is always 3).
print(img.direction)  # Direction cosines (size is always 3x3).
print(img.coord_sys)  # Coordinate frame in which the direction cosines are
# measured. Available Coordinate frame is not finalized yet.

# Returns a set of associated image names.
print(img.associated_images)
# Returns a dict that includes resolution information.
print(json.dumps(img.resolutions, indent=2))
# A metadata object as `dict`
print(json.dumps(img.metadata, indent=2))
# A raw metadata string.
print(img.raw_metadata)

# my gaming nvidia GPU does not support GPUDirect Storage (GDS)...
# can only refer to the cucim's GDS benchmark results at
# https://github.com/rapidsai/cucim/blob/branch-25.12/examples/python/gds_whole_slide/benchmark_read.py#L166

# tiffslide also have benchmark script at
# https://github.com/Bayer-Group/tiffslide/blob/main/tiffslide/tests/test_benchmark.py
# and in its [issue 72](https://github.com/Bayer-Group/tiffslide/issues/72),
# it claims a out-performing than openslide
