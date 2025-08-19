import base64
import os
import sys
import zlib
from argparse import ArgumentParser
from collections import OrderedDict
from collections.abc import Callable
from io import BytesIO
from pathlib import Path, PurePath
from threading import Lock
from typing import Any, Literal, TypeAlias

import uvicorn
import yaml
from fastapi import FastAPI, HTTPException, Request, Response
from fastapi.responses import HTMLResponse
from fastapi.staticfiles import StaticFiles
from fastapi.templating import Jinja2Templates
from PIL import Image, ImageCms
from pydantic_settings import BaseSettings

sys.path.insert(0, os.path.abspath(Path(__file__).parent.parent.absolute()))
# pylint: disable=wrong-import-position
from openslide import ImageSlide
from openslide.deepzoom import DeepZoomGenerator as DeepZoomGeneratorOSD

from dz_py.deepzoom import DeepZoomGenerator

SRGB_PROFILE_BYTES = zlib.decompress(
    base64.b64decode(
        "eNpjYGA8kZOcW8wkwMCQm1dSFOTupBARGaXA/oiBmUGEgZOBj0E2Mbm4wDfYLYQBCIoT"
        "y4uTS4pyGFDAt2sMjCD6sm5GYl7K3IkMtg4NG2wdSnQa5y1V6mPADzhTUouTgfQHII5P"
        "LigqYWBg5AGyecpLCkBsCSBbpAjoKCBbB8ROh7AdQOwkCDsErCYkyBnIzgCyE9KR2ElI"
        "bKhdIMBaCvQsskNKUitKQLSzswEDKAwgop9DwH5jFDuJEMtfwMBg8YmBgbkfIZY0jYFh"
        "eycDg8QthJgKUB1/KwPDtiPJpUVlUGu0gLiG4QfjHKZS5maWk2x+HEJcEjxJfF8Ez4t8"
        "k8iS0VNwVlmjmaVXZ/zacrP9NbdwX7OQshjxFNmcttKwut4OnUlmc1Yv79l0e9/MU8ev"
        "pz4p//jz/38AR4Nk5Q=="
    )
)
SRGB_PROFILE = ImageCms.getOpenProfile(BytesIO(SRGB_PROFILE_BYTES))
ColorMode: TypeAlias = Literal[
    "default",
    "absolute-colorimetric",
    "perceptual",
    "relative-colorimetric",
    "saturation",
    "embed",
    "ignore",
]
Transform: TypeAlias = Callable[[Image.Image], None]


class AnnotatedDeepZoomGenerator(DeepZoomGenerator):
    filename: str
    mpp: float
    transform: Transform


class AnnotatedDeepZoomGeneratorOSD(DeepZoomGeneratorOSD):
    filename: str
    mpp: float
    transform: Transform


class _SlideCache:
    def __init__(
        self,
        cache_size: int,
        dz_opts: dict[str, Any],
        color_mode: ColorMode,
    ):
        self.cache_size = cache_size
        self.dz_opts = dz_opts
        self.color_mode = color_mode
        self._lock = Lock()
        self._cache: OrderedDict[Path, AnnotatedDeepZoomGenerator] = (
            OrderedDict()
        )
        # TODO: Share a single tile cache among all slide handles, if supported

    def get(self, path: Path) -> AnnotatedDeepZoomGenerator:
        with self._lock:
            if path in self._cache:
                # Move to end of LRU
                slide = self._cache.pop(path)
                self._cache[path] = slide
                return slide

        slide = AnnotatedDeepZoomGenerator(path, **self.dz_opts)
        # pylint: disable=protected-access
        if (
            slide._metadata.get("mm_x") is not None
            and slide._metadata.get("mm_y") is not None
        ):
            slide.mpp = (
                (slide._metadata["mm_x"] + slide._metadata["mm_y"])
                * (10**3)
                / 2
            )
        elif slide._metadata.get("mm_x") is not None:
            slide.mpp = slide._metadata["mm_x"] * (10**3)
        elif slide._metadata.get("mm_y") is not None:
            slide.mpp = slide._metadata["mm_y"] * (10**3)
        else:
            slide.mpp = 0
        slide.transform = self._get_transform(slide.get_icc_profile)

        with self._lock:
            if path not in self._cache:
                if len(self._cache) == self.cache_size:
                    self._cache.popitem(last=False)
                self._cache[path] = slide
        return slide

    def _get_transform(
        self, color_profile: ImageCms.ImageCmsProfile
    ) -> Transform:
        if color_profile is None:
            return lambda img: None
        mode = self.color_mode
        if mode == "ignore":
            # drop ICC profile from tiles
            return lambda img: img.info.pop("icc_profile")
        if mode == "embed":
            # embed ICC profile in tiles
            return lambda img: None
        if mode == "default":
            intent = ImageCms.Intent(ImageCms.getDefaultIntent(color_profile))
        elif mode == "absolute-colorimetric":
            intent = ImageCms.Intent.ABSOLUTE_COLORIMETRIC
        elif mode == "relative-colorimetric":
            intent = ImageCms.Intent.RELATIVE_COLORIMETRIC
        elif mode == "perceptual":
            intent = ImageCms.Intent.PERCEPTUAL
        elif mode == "saturation":
            intent = ImageCms.Intent.SATURATION
        else:
            raise ValueError(f"Unknown color mode {mode}")
        transform = ImageCms.buildTransform(
            color_profile,
            SRGB_PROFILE,
            "RGB",
            "RGB",
            intent,
            ImageCms.Flags(0),
        )

        def xfrm(img: Image.Image) -> None:
            ImageCms.applyTransform(img, transform, True)
            # Some browsers assume we intend the display's color space if we
            # don't embed the profile.  Pillow's serialization is larger, so
            # use ours.
            img.info["icc_profile"] = SRGB_PROFILE_BYTES

        return xfrm


class _Directory:
    _DEFAULT_RELPATH = PurePath(".")

    def __init__(self, slidedir: Path, relpath: PurePath = _DEFAULT_RELPATH):
        self.name = relpath.name
        self.children: list[_Directory | _SlideFile] = []
        for cur_path in sorted((slidedir / relpath).iterdir()):
            cur_relpath = relpath / cur_path.name
            if cur_path.is_dir():
                cur_dir = _Directory(slidedir, cur_relpath)
                if cur_dir.children:
                    self.children.append(cur_dir)
            elif DeepZoomGenerator.can_read(cur_path):
                self.children.append(_SlideFile(cur_relpath))


class _SlideFile:
    def __init__(self, relpath: PurePath):
        self.name = relpath.name
        self.url_path = relpath.as_posix()


class DeepZoomMultiServer(FastAPI):
    slidedir: Path
    cache: _SlideCache
    users: dict[str, Any]


class Settings(BaseSettings):
    app_name: str = "Awesome API"
    config: dict[str, Any]


def create_app(
    config: dict[str, Any] | None = None,
) -> FastAPI:
    # Create and configure app
    app = DeepZoomMultiServer()
    app.mount(
        "/static",
        StaticFiles(
            directory=Path(__file__).parent.joinpath("./static").resolve()
        ),
        name="static",
    )
    templates = Jinja2Templates(
        directory=Path(__file__).parent.joinpath("./templates").resolve()
    )
    settings = Settings(
        config=dict(
            SLIDE_DIR=".",
            SLIDE_CACHE_SIZE=30,
            DEEPZOOM_TILE_SIZE=254,
            DEEPZOOM_OVERLAP=1,
            DEEPZOOM_LIMIT_BOUNDS=True,
            DEEPZOOM_TILE_QUALITY=75,
            DEEPZOOM_COLOR_MODE="default",
        )
    )
    if config is not None:
        settings.config.update(config)

    # Set up cache
    app.slidedir = Path(settings.config["SLIDE_DIR"]).resolve(strict=True)
    config_map = {
        "DEEPZOOM_TILE_SIZE": "tile_size",
        "DEEPZOOM_OVERLAP": "overlap",
        "DEEPZOOM_LIMIT_BOUNDS": "limit_bounds",
    }
    opts = {v: settings.config[k] for k, v in config_map.items()}
    app.cache = _SlideCache(
        settings.config["SLIDE_CACHE_SIZE"],
        opts,
        settings.config["DEEPZOOM_COLOR_MODE"],
    )
    app.users = {}

    # Helper functions
    def get_slide(user_path: PurePath) -> AnnotatedDeepZoomGenerator:
        try:
            path = (app.slidedir / user_path).resolve(strict=True)
        except OSError as e:
            # Does not exist
            raise HTTPException(status_code=404) from e
        if path.parts[: len(app.slidedir.parts)] != app.slidedir.parts:
            # Directory traversal
            raise HTTPException(status_code=404)
        try:
            slide = app.cache.get(path)
            slide.filename = path.name
            return slide
        except Exception as e:
            raise HTTPException(status_code=404) from e

    # Set up routes
    @app.get("/", response_class=HTMLResponse)
    def index(request: Request):
        return templates.TemplateResponse(
            "files.html",
            {"request": request, "root_dir": _Directory(app.slidedir)},
        )

    # note the order of these three routes matters
    @app.get("/{path:path}.dzi")
    def dzi(path: str) -> Response:
        try:
            slide = app.cache.get(path)
        except Exception:  # pylint: disable=broad-except
            slide = get_slide(PurePath(path))
        return Response(
            content=slide.get_dzi("jpeg"), media_type="application/xml"
        )

    @app.get(
        "/{path:path}_files/{level:int}/{col:int}_{row:int}.{format_:str}"
    )
    def tile(
        path: str, level: int, col: int, row: int, format_: str
    ) -> Response:
        try:
            slide = app.cache.get(path)
        except Exception:  # pylint: disable=broad-except
            slide = get_slide(PurePath(path))
        format_ = format_.lower()
        if format_ != "jpeg":
            # Not supported by DeepZoomGenerator
            raise HTTPException(status_code=404)
        try:
            tile = slide.get_tile(level, (col, row))
        except ValueError as e:
            # Invalid level or coordinates
            raise HTTPException(status_code=404) from e
        slide.transform(tile)
        buf = BytesIO()
        tile.save(
            buf,
            format_,
            quality=settings.config["DEEPZOOM_TILE_QUALITY"],
            icc_profile=tile.info.get("icc_profile"),
        )
        return Response(content=buf.getvalue(), media_type=f"image/{format_}")

    # this one should be the last one
    @app.get("/{path:path}")
    def slide(path: str, request: Request):
        slide = get_slide(PurePath(path))
        slide_url = app.url_path_for("dzi", path=path)
        for name, image in slide.associated_images.items():
            image_path = f"{path}_{name}"
            # pylint: disable=protected-access
            app.cache._cache[image_path] = AnnotatedDeepZoomGeneratorOSD(
                ImageSlide(image), **opts
            )
            app.cache._cache[image_path].filename = name
            app.cache._cache[image_path].mpp = slide.mpp
            app.cache._cache[image_path].transform = slide.transform
        associated_urls = {
            # treat associated images as slide files
            name: app.url_path_for("dzi", path=f"{path}_{name}")
            for name in slide.associated_images
        }
        return templates.TemplateResponse(
            "slide-multipane.html",
            {
                "request": request,
                "slide_url": slide_url,
                "associated": associated_urls,
                "properties": (
                    slide._metadata  # pylint: disable=protected-access
                ),
                "slide_mpp": slide.mpp,
            },
        )

    return app


# python .\main.py -s 512 -Q 90 -g log_config.yml D:\volumes\tusd\upload_data\orgin
if __name__ == "__main__":
    parser = ArgumentParser(usage="%(prog)s [options] [SLIDE-DIRECTORY]")
    parser.add_argument(
        "-B",
        "--ignore-bounds",
        dest="DEEPZOOM_LIMIT_BOUNDS",
        default=True,
        action="store_false",
        help="display entire scan area",
    )
    parser.add_argument(
        "--color-mode",
        dest="DEEPZOOM_COLOR_MODE",
        choices=[
            "default",
            "absolute-colorimetric",
            "perceptual",
            "relative-colorimetric",
            "saturation",
            "embed",
            "ignore",
        ],
        default="default",
        help=(
            "convert tiles to sRGB using default rendering intent of ICC "
            "profile, or specified rendering intent; or embed original "
            "ICC profile; or ignore ICC profile (compat) [default]"
        ),
    )
    parser.add_argument(
        "-d",
        "--debug",
        dest="DEBUG",
        action="store_true",
        help="run in debugging mode (insecure)",
    )
    parser.add_argument(
        "-e",
        "--overlap",
        metavar="PIXELS",
        dest="DEEPZOOM_OVERLAP",
        type=int,
        help="overlap of adjacent tiles [1]",
    )
    parser.add_argument(
        "-l",
        "--listen",
        metavar="ADDRESS",
        dest="host",
        default="127.0.0.1",
        help="address to listen on [127.0.0.1]",
    )
    parser.add_argument(
        "-p",
        "--port",
        metavar="PORT",
        dest="port",
        type=int,
        default=5000,
        help="port to listen on [5000]",
    )
    parser.add_argument(
        "-Q",
        "--quality",
        metavar="QUALITY",
        dest="DEEPZOOM_TILE_QUALITY",
        type=int,
        help="JPEG compression quality [75]",
    )
    parser.add_argument(
        "-s",
        "--size",
        metavar="PIXELS",
        dest="DEEPZOOM_TILE_SIZE",
        type=int,
        help="tile size [254]",
    )
    parser.add_argument(
        "SLIDE_DIR",
        metavar="SLIDE-DIRECTORY",
        type=Path,
        nargs="?",
        help="slide directory",
    )
    parser.add_argument(
        "-g",
        "--log_config_file_path",
        metavar="LOG_CONFIG_FILE_PATH",
        dest="log_config_file_path",
        type=str,
        help="log config yaml file path [log_config.yaml]",
    )

    args = parser.parse_args()
    config_ = {}
    # Set only those settings specified on the command line
    for k in dir(args):
        v = getattr(args, k)
        if not k.startswith("_") and v is not None:
            config_[k] = v
    app_ = create_app(config_)
    if config_.get("log_config_file_path"):
        with open(config_["log_config_file_path"], "r", encoding="utf-8") as f:
            log_config = yaml.safe_load(f)
        uvicorn.run(
            app_,
            host=args.host,
            port=args.port,
            workers=1,
            log_config=log_config,
        )
    else:
        uvicorn.run(app_, host=args.host, port=args.port, workers=1)
