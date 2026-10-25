"""Stage an iPhone/iPad .ipa from the iOS build, without any game data.

The .ipa is ad-hoc signed only: a signing service (or a developer account)
signs it again for a device. The player's disc image is chosen on the
device at first launch (src/pc/platform/ios/ios_glue.m).
"""

import argparse
import json
import plistlib
import re
import shutil
import struct
import subprocess
import sys
import zlib
from pathlib import Path

from build_config import IOS_MINIMUM

ROOT = Path(__file__).resolve().parents[2]
APP = "FMRecompiled.app"
EXECUTABLE = "memories-ios"
BUNDLE_ID = "io.github.yfm-redecomp.ios"


def png(width, height, pixel):
    """A plain RGB PNG of pixel(x, y) -> (r, g, b), without Pillow."""
    rows = b"".join(
        b"\0" + b"".join(bytes(pixel(x, y)) for x in range(width)) for y in range(height)
    )

    def chunk(kind, data):
        return struct.pack(">I", len(data)) + kind + data + struct.pack(">I", zlib.crc32(kind + data))

    return (
        b"\x89PNG\r\n\x1a\n"
        + chunk(b"IHDR", struct.pack(">IIBBBBB", width, height, 8, 2, 0, 0, 0))
        + chunk(b"IDAT", zlib.compress(rows, 9))
        + chunk(b"IEND", b"")
    )


def icon(size):
    """An original icon: a deep violet field with a gold card outline and a
    gold diamond, drawn from shapes (no game art)."""

    def pixel(x, y):
        u, v = (x + 0.5) / size, (y + 0.5) / size
        # background: violet, lighter toward the top
        r, g, b = 38 + 40 * (1 - v), 18 + 14 * (1 - v), 70 + 60 * (1 - v)
        # card: a rounded rectangle outline
        cx, cy, hw, hh = abs(u - 0.5), abs(v - 0.5), 0.27, 0.36
        inside = cx < hw and cy < hh
        edge = inside and (cx > hw - 0.035 or cy > hh - 0.035)
        if inside and not edge:
            r, g, b = r * 0.55, g * 0.55, b * 0.7
        # diamond in the card's middle
        if cx / 0.16 + cy / 0.22 < 1:
            shade = 1 - 0.35 * (cx / 0.16 + cy / 0.22)
            r, g, b = 245 * shade, 196 * shade, 70 * shade
        if edge:
            r, g, b = 232, 186, 74
        return int(min(255, r)), int(min(255, g)), int(min(255, b))

    return png(size, size, pixel)


def data_mods():
    """The repository's mods that need no code library: code mods are native
    libraries built for macOS, which iOS cannot load from this build."""
    tracked = subprocess.check_output(["git", "ls-files", "-z", "mods"], cwd=ROOT, text=True).split("\0")
    files = [Path(name) for name in tracked if name]
    keep = set()
    for manifest in files:
        if manifest.name != "mod.json":
            continue
        data = json.loads((ROOT / manifest).read_text(encoding="utf-8-sig"))
        if not data.get("library"):
            keep.add(manifest.parent)
    return [f for f in files if f.parent in keep or any(p in keep for p in f.parents)
            if f.suffix not in (".c", ".h", ".o", ".dylib")]


def sdk_version():
    try:
        return subprocess.check_output(["xcrun", "--sdk", "iphoneos", "--show-sdk-version"], text=True).strip()
    except (OSError, subprocess.CalledProcessError):
        return ""


def package(binary, out, label):
    if not re.fullmatch(r"[A-Za-z0-9][A-Za-z0-9._-]*", label):
        raise ValueError("version must be a filename-safe label")
    stage = out / "stage"
    shutil.rmtree(stage, ignore_errors=True)
    app = stage / "Payload" / APP
    app.mkdir(parents=True)
    shutil.copy2(binary, app / EXECUTABLE)
    (app / EXECUTABLE).chmod(0o755)

    languages = app / "languages"
    languages.mkdir()
    for name in ("en-eu", "fr", "de", "it", "es"):
        shutil.copyfile(ROOT / f"languages/{name}.txt", languages / f"{name}.txt")
    for relative in data_mods():
        destination = app / relative
        destination.parent.mkdir(parents=True, exist_ok=True)
        shutil.copyfile(ROOT / relative, destination)

    for name, size in (("AppIcon60x60@2x.png", 120), ("AppIcon60x60@3x.png", 180),
                       ("AppIcon76x76@2x~ipad.png", 152), ("AppIcon83.5x83.5@2x~ipad.png", 167)):
        (app / name).write_bytes(icon(size))

    shutil.copyfile(ROOT / "LICENSE", app / "LICENSE.txt")
    licenses = app / "licenses"
    licenses.mkdir()
    for name, source in {
        "SDL3.txt": "sdl-source/LICENSE.txt",
        "libpng.txt": "libpng/LICENSE",
        "zlib.txt": "zlib/LICENSE",
        "FreeType.txt": "freetype/docs/FTL.TXT",
    }.items():
        found = ROOT / "tmp/pc/ios-deps/src" / source
        if found.is_file():
            shutil.copyfile(found, licenses / name)

    build_number = subprocess.check_output(["git", "rev-list", "--count", "HEAD"], cwd=ROOT, text=True).strip()
    revision = subprocess.check_output(["git", "rev-parse", "HEAD"], cwd=ROOT, text=True).strip()
    release = re.match(r"^v?(\d+\.\d+\.\d+)", label)
    landscape = ["UIInterfaceOrientationLandscapeLeft", "UIInterfaceOrientationLandscapeRight"]
    sdk = sdk_version()
    info = {
        "CFBundleName": "FM Recompiled",
        "CFBundleDisplayName": "Forbidden Memories",
        "CFBundleIdentifier": BUNDLE_ID,
        "CFBundleExecutable": EXECUTABLE,
        "CFBundlePackageType": "APPL",
        "CFBundleInfoDictionaryVersion": "6.0",
        "CFBundleDevelopmentRegion": "en",
        "CFBundleVersion": build_number,
        "CFBundleShortVersionString": release.group(1) if release else "0.0." + build_number,
        "CFBundleSupportedPlatforms": ["iPhoneOS"],
        "CFBundleIcons": {"CFBundlePrimaryIcon": {"CFBundleIconFiles": ["AppIcon60x60"]}},
        "CFBundleIcons~ipad": {"CFBundlePrimaryIcon": {"CFBundleIconFiles": ["AppIcon60x60", "AppIcon76x76",
                                                                             "AppIcon83.5x83.5"]}},
        "MinimumOSVersion": IOS_MINIMUM,
        "LSRequiresIPhoneOS": True,
        "UIDeviceFamily": [1, 2],
        "UIRequiredDeviceCapabilities": ["arm64"],
        "UILaunchScreen": {},
        "UIRequiresFullScreen": True,
        "UIStatusBarHidden": True,
        "UIViewControllerBasedStatusBarAppearance": True,
        "UISupportedInterfaceOrientations": landscape,
        "UISupportedInterfaceOrientations~ipad": landscape,
        # Documents shows in Files (On My iPhone): saves, mods, the disc.
        "UIFileSharingEnabled": True,
        "LSSupportsOpeningDocumentsInPlace": True,
        "UIApplicationSupportsIndirectInputEvents": True,
        "GCSupportsControllerUserInteraction": True,
        "ITSAppUsesNonExemptEncryption": False,
        "DTPlatformName": "iphoneos",
        "DTPlatformVersion": sdk,
        "DTSDKName": "iphoneos" + sdk,
        "PackageVersion": label,
        "SourceRevision": revision,
    }
    (app / "Info.plist").write_bytes(plistlib.dumps(info, fmt=plistlib.FMT_BINARY))
    (app / "PkgInfo").write_bytes(b"APPL????")
    if sys.platform == "darwin":
        subprocess.run(["codesign", "--force", "--sign", "-", "--timestamp=none", str(app)], check=True)
    out.mkdir(parents=True, exist_ok=True)
    ipa = out / f"FMRecompiled-{label}.ipa"
    ipa.unlink(missing_ok=True)
    if sys.platform == "darwin":
        subprocess.run(["ditto", "-c", "-k", "--norsrc", "--keepParent", "Payload", str(ipa.resolve())],
                       cwd=stage, check=True)
    else:
        shutil.make_archive(str(ipa.with_suffix("")), "zip", stage, "Payload")
        ipa.with_suffix(".zip").rename(ipa)
    print(f"Packaged {ipa}")
    return ipa


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--binary", type=Path, default=ROOT / "tmp/pc/ios" / EXECUTABLE)
    parser.add_argument("--out", type=Path, default=ROOT / "tmp/pc-release/ios")
    parser.add_argument("--version", default="dev-local")
    args = parser.parse_args()
    package(args.binary.resolve(), args.out.resolve(), args.version)


if __name__ == "__main__":
    main()
