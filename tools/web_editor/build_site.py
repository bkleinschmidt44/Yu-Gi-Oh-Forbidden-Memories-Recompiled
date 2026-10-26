"""Build the web editor's site: the page, the disc reader, and engine.zip
(the FM Editor engine, text_listing.py, the editor's recipe tables and the
bridge), which the page unpacks into Pyodide in the repository's own layout
(text_listing.py and the engine find their files by it).

    python3 tools/web_editor/build_site.py [out-folder]     (default tmp/web-editor)
"""
import sys
import zipfile
from pathlib import Path

HERE = Path(__file__).resolve().parent
ROOT = HERE.parents[1]
PC = ROOT / "tools/pc"


def engine_files():
    for path in sorted((PC / "fm_editor").glob("*.py")):
        yield path, f"tools/pc/fm_editor/{path.name}"
    yield PC / "text_listing.py", "tools/pc/text_listing.py"
    for path in sorted((PC / "hd_recipes").glob("*.json")):
        yield path, f"tools/pc/hd_recipes/{path.name}"
    yield HERE / "bridge.py", "tools/web_editor/bridge.py"


def build(out: Path):
    out.mkdir(parents=True, exist_ok=True)
    with zipfile.ZipFile(out / "engine.zip", "w", zipfile.ZIP_DEFLATED) as archive:
        for source, name in engine_files():
            archive.write(source, name)
    for name in ("index.html", "disc-reader.js", "icon.png"):
        if (HERE / name).is_file():
            (out / name).write_bytes((HERE / name).read_bytes())
    (out / ".nojekyll").write_text("")
    sys.path.insert(0, str(PC))
    from package_ios import icon     # the iOS app's own icon, for the Home Screen
    (out / "icon.png").write_bytes(icon(180))
    print(f"Built {out}: engine.zip {(out / 'engine.zip').stat().st_size // 1024} KB")


if __name__ == "__main__":
    build(Path(sys.argv[1]) if len(sys.argv) > 1 else ROOT / "tmp/web-editor")
