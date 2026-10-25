"""Pinned static iOS ARM64 dependencies (SDL3, FreeType, libpng, zlib).

The same archives as macos_deps.py, cross-compiled for the iPhoneOS SDK with
Xcode's own clang (SDL's UIKit backend is Objective-C, which is safest with
the SDK's compiler). The game's units still use the pinned LLVM; these are
plain static libraries, so mixing the two compilers is fine.
"""

import hashlib
import json
import os
import platform
import shutil
import subprocess
import tarfile
from pathlib import Path

from build_config import IOS_MINIMUM
from dependency_archives import ARCHIVES
from fetch_tools import download, unpack
from fetch_tools import ensure as ensure_tool

ROOT = Path(__file__).resolve().parents[2]
OUT = ROOT / "tmp/pc/ios-deps"
INSTALL = OUT / "install"
LIBRARIES = {
    "zlib": "libz.a",
    "libpng": "libpng16.a",
    "freetype": "libfreetype.a",
    "sdl-source": "libSDL3.a",
}


def sdk_path():
    sdk = Path(
        subprocess.check_output(
            ["xcrun", "--sdk", "iphoneos", "--show-sdk-path"], text=True
        ).strip()
    )
    if not (sdk / "usr/include/stdlib.h").is_file():
        raise RuntimeError(f"xcrun returned an invalid iPhoneOS SDK: {sdk}")
    return sdk


def xcode_tool(name):
    return subprocess.check_output(
        ["xcrun", "--sdk", "iphoneos", "--find", name], text=True
    ).strip()


def source(name):
    url, digest = ARCHIVES[name]
    archive = download(url, digest)
    folder = OUT / "src" / name
    stamp = folder / ".archive-sha256"
    if stamp.is_file() and stamp.read_text() == digest:
        return folder
    with tarfile.open(archive) as bundle:
        top = bundle.getnames()[0].split("/")[0]
    temporary = OUT / "src" / (name + ".extract")
    shutil.rmtree(temporary, ignore_errors=True)
    unpack(archive, str(temporary))
    shutil.rmtree(folder, ignore_errors=True)
    (temporary / top).rename(folder)
    shutil.rmtree(temporary)
    stamp.write_text(digest)
    return folder


def ensure(names=tuple(LIBRARIES), jobs=8):
    if platform.system() != "Darwin":
        raise RuntimeError("the iOS dependency builder needs a Mac with Xcode")
    sdk = sdk_path()
    clang, clangxx = xcode_tool("clang"), xcode_tool("clang++")
    cmake, ninja = ensure_tool("cmake", pinned=True), ensure_tool("ninja", pinned=True)
    options = {
        "zlib": [
            "-DZLIB_BUILD_SHARED=OFF",
            "-DZLIB_BUILD_TESTING=OFF",
            "-DBUILD_SHARED_LIBS=OFF",
        ],
        "libpng": [
            "-DPNG_SHARED=OFF",
            "-DPNG_STATIC=ON",
            "-DPNG_TESTS=OFF",
            "-DPNG_TOOLS=OFF",
            "-DPNG_FRAMEWORK=OFF",
            f"-DZLIB_LIBRARY={INSTALL}/lib/libz.a",
            f"-DZLIB_INCLUDE_DIR={INSTALL}/include",
        ],
        "freetype": [
            "-DBUILD_SHARED_LIBS=OFF",
            "-DFT_DISABLE_ZLIB=ON",
            "-DFT_DISABLE_BZIP2=ON",
            "-DFT_DISABLE_PNG=ON",
            "-DFT_DISABLE_HARFBUZZ=ON",
            "-DFT_DISABLE_BROTLI=ON",
        ],
        "sdl-source": [
            "-DSDL_STATIC=ON",
            "-DSDL_SHARED=OFF",
            "-DSDL_TESTS=OFF",
            "-DSDL_TEST_LIBRARY=OFF",
            "-DSDL_EXAMPLES=OFF",
            "-DSDL_INSTALL=ON",
        ],
    }
    identity = subprocess.check_output([clang, "--version"], text=True).splitlines()[0]
    for name in names:
        directory = source(name)
        build = OUT / "build" / name
        stamp = build / "complete.json"
        command = [
            cmake,
            "-S",
            str(directory),
            "-B",
            str(build),
            "-G",
            "Ninja",
            f"-DCMAKE_MAKE_PROGRAM={ninja}",
            "-DCMAKE_BUILD_TYPE=Release",
            "-DCMAKE_SYSTEM_NAME=iOS",
            f"-DCMAKE_C_COMPILER={clang}",
            f"-DCMAKE_CXX_COMPILER={clangxx}",
            "-DCMAKE_OSX_ARCHITECTURES=arm64",
            f"-DCMAKE_OSX_DEPLOYMENT_TARGET={IOS_MINIMUM}",
            f"-DCMAKE_OSX_SYSROOT={sdk}",
            "-DCMAKE_XCODE_ATTRIBUTE_CODE_SIGNING_ALLOWED=NO",
            "-DCMAKE_TRY_COMPILE_TARGET_TYPE=STATIC_LIBRARY",
            f"-DCMAKE_INSTALL_PREFIX={INSTALL}",
            f"-DCMAKE_PREFIX_PATH={INSTALL}",
            f"-DCMAKE_FIND_ROOT_PATH={INSTALL};{sdk}",
            "-DCMAKE_FIND_ROOT_PATH_MODE_LIBRARY=ONLY",
            "-DCMAKE_FIND_ROOT_PATH_MODE_INCLUDE=ONLY",
            "-DCMAKE_FIND_ROOT_PATH_MODE_PACKAGE=ONLY",
            "-DCMAKE_FIND_ROOT_PATH_MODE_PROGRAM=NEVER",
            "-DPKG_CONFIG_EXECUTABLE=/usr/bin/false",
            "-DCMAKE_POLICY_VERSION_MINIMUM=3.5",
            *options[name],
        ]
        fingerprint = json.dumps(
            {
                "command": command,
                "archive": ARCHIVES[name][1],
                "builder": hashlib.sha256(Path(__file__).read_bytes()).hexdigest(),
                "compiler": identity,
            },
            sort_keys=True,
        )
        if (
            stamp.is_file()
            and stamp.read_text() == fingerprint
            and (INSTALL / "lib" / LIBRARIES[name]).is_file()
        ):
            continue
        shutil.rmtree(build, ignore_errors=True)
        environment = {
            key: value
            for key, value in os.environ.items()
            if key
            not in (
                "CPATH",
                "C_INCLUDE_PATH",
                "CPLUS_INCLUDE_PATH",
                "LIBRARY_PATH",
                "CFLAGS",
                "CXXFLAGS",
                "LDFLAGS",
                "SDKROOT",
                "MACOSX_DEPLOYMENT_TARGET",
                "IPHONEOS_DEPLOYMENT_TARGET",
            )
        }
        subprocess.run(command, check=True, env=environment)
        subprocess.run(
            [cmake, "--build", str(build), "--parallel", str(jobs)],
            check=True,
            env=environment,
        )
        subprocess.run([cmake, "--install", str(build)], check=True, env=environment)
        if not (INSTALL / "lib" / LIBRARIES[name]).is_file():
            raise RuntimeError(f"{name} did not install {LIBRARIES[name]}")
        stamp.write_text(fingerprint)
    return INSTALL


if __name__ == "__main__":
    import argparse

    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--jobs", type=int, default=8)
    print(f"iOS static dependencies: {ensure(jobs=parser.parse_args().jobs)}")
