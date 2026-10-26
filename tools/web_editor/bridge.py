"""The web editor's bridge: plain, JSON-friendly calls over the FM Editor
engine (tools/pc/fm_editor), for a page that runs it in Pyodide.

The page writes the two game files it took off the player's disc into
<root>/game, and keeps the mod being edited in <root>/mod: every change is
saved there at once (manifest.save_mod), so the page only has to keep the
folder (IndexedDB) to have it back next time. Nothing here writes the disc.
"""
from __future__ import annotations

import io
import json
import shutil
import zipfile
from pathlib import Path

from fm_editor import art, disc, gamedata, manifest, pngio, pools, validate
from fm_editor.gamedata import (ATTRIBUTE_NAMES, DECK_POOL_MIN_CARDS, DUELIST_NAMES, POOL_TOTAL, POOLS,
                                TYPE_NAMES)
from fm_editor.model import KEY_RE, Project

ROOT = Path("/persist")
state = {"files": None, "retail": None, "project": None}


def _game() -> Path:
    return ROOT / "game"


def _mod() -> Path:
    return ROOT / "mod"


def _project() -> Project:
    if state["project"] is None:
        raise RuntimeError("no game loaded yet")
    return state["project"]


def _out(value):
    return json.dumps(value)


# --- the game and the mod --------------------------------------------------------

def set_root(path: str):
    global ROOT
    ROOT = Path(path)


def has_game() -> bool:
    return (_game() / disc.EXECUTABLE).is_file() and (_game() / "DATA" / disc.ARCHIVE).is_file()


def load_game() -> str:
    """Read <root>/game, then the saved mod over it (or a new one)."""
    files = disc.load(_game())
    state["files"] = files
    state["retail"] = gamedata.load_game(files)
    notes = []
    if (_mod() / "mod.json").is_file():
        try:
            project, notes = manifest.open_mod(state["retail"], _mod())
            state["project"] = project
        except Exception as problem:            # a broken save: keep it aside, start afresh
            broken = ROOT / "mod-unreadable"
            shutil.rmtree(broken, ignore_errors=True)
            _mod().rename(broken)
            state["project"] = Project(state["retail"])
            notes = [f"The saved mod could not be read ({problem}); it was kept aside and a new one started."]
    else:
        state["project"] = Project(state["retail"])
        _save()
    return _out({"notes": [str(n) for n in notes], "info": _info()})


def _save():
    """Write the mod folder with this change (the page then keeps it)."""
    project = _project()
    manifest.save_mod(project, _mod())
    project.source_dir = _mod()


def new_mod() -> str:
    shutil.rmtree(_mod(), ignore_errors=True)
    state["project"] = Project(state["retail"])
    _save()
    return _out(_info())


def _info() -> dict:
    info = _project().info
    return {"id": info.id, "name": info.name, "version": info.version, "author": info.author,
            "description": info.description}


def info() -> str:
    return _out(_info())


def set_info(values_json: str) -> str:
    values = json.loads(values_json)
    info = _project().info
    if "id" in values:
        key = str(values["id"]).strip()
        if not KEY_RE.match(key):
            raise ValueError("The mod's id may only use letters, digits, - and _.")
        info.id = key
    for field in ("name", "version", "author", "description"):
        if field in values:
            setattr(info, field, str(values[field]))
    _save()
    return _out(_info())


def issues() -> str:
    found = validate.validate(_project())
    return _out([{"level": i.level, "area": i.area, "where": str(i.where), "message": i.message} for i in found])


def export_zip(path: str = "") -> str:
    """The mod folder as a .zip whose top folder is the mod's id, ready to
    go in the game's mods folder: written to `path`, whose file name is
    returned (the page reads it from there)."""
    _save()
    top = _project().info.id
    buffer = io.BytesIO()
    with zipfile.ZipFile(buffer, "w", zipfile.ZIP_DEFLATED) as out:
        for file in sorted(_mod().rglob("*")):
            if file.is_file():
                out.write(file, f"{top}/{file.relative_to(_mod()).as_posix()}")
    if path:
        Path(path).write_bytes(buffer.getvalue())
    return f"{top}.zip"


def import_zip(path: str) -> str:
    """Open a mod .zip (one this page exported, or another mod) in place of
    the one being edited."""
    work = ROOT / "import"
    shutil.rmtree(work, ignore_errors=True)
    work.mkdir(parents=True)
    with zipfile.ZipFile(path) as archive:
        for name in archive.namelist():
            target = (work / name).resolve()
            if not str(target).startswith(str(work.resolve())):
                raise ValueError("the .zip names a file outside its own folder")
        archive.extractall(work)
    manifests = sorted(work.rglob("mod.json"), key=lambda p: len(p.parts))
    if not manifests:
        raise ValueError("there is no mod.json in that .zip")
    project, notes = manifest.open_mod(state["retail"], manifests[0].parent)
    shutil.rmtree(_mod(), ignore_errors=True)
    state["project"] = project
    manifest.save_mod(project, _mod())
    project.source_dir = _mod()
    shutil.rmtree(work, ignore_errors=True)
    return _out({"notes": [str(n) for n in notes], "info": _info()})


# --- cards -----------------------------------------------------------------------

def cards() -> str:
    """Every card for the pickers: [id, name, kind, attack, defense, level]."""
    project = _project()
    out = []
    for cid in sorted(project.cards):
        card = project.cards[cid]
        kind = TYPE_NAMES[card.type] if 0 <= card.type < len(TYPE_NAMES) else "?"
        out.append([cid, card.name, kind, card.attack, card.defense, card.level,
                    ATTRIBUTE_NAMES[card.attribute] if card.is_monster() and 0 <= card.attribute < 6 else ""])
    return _out(out)


# --- duelists' decks and drops ---------------------------------------------------

def duelists() -> str:
    project = _project()
    out = []
    for d in range(1, len(project.pools)):
        changed = [p for p in POOLS if _clean(project.pools[d][p]) != _clean(project.retail.pools[d][p])]
        out.append({"id": d, "name": DUELIST_NAMES[d] if d < len(DUELIST_NAMES) else f"Duelist {d}",
                    "changed": changed})
    return _out(out)


def _clean(pool: dict) -> dict:
    return {cid: w for cid, w in pool.items() if w}


def pool(d: int, which: str) -> str:
    project = _project()
    now = _clean(project.pools[d][which])
    retail = _clean(project.retail.pools[d][which])
    rows = sorted(now.items(), key=lambda item: (-item[1], item[0]))
    return _out({"duelist": d, "pool": which, "total": POOL_TOTAL, "rows": [[c, w] for c, w in rows],
                 "retail": {str(c): w for c, w in retail.items()}, "changed": now != retail,
                 "min_cards": DECK_POOL_MIN_CARDS if which == "deck" else 1})


def pool_set(d: int, which: str, cid: int, weight: int) -> str:
    """One card's weight (out of 2048) set, the rest scaled to make up the
    total as the game does; 0 takes the card out."""
    project = _project()
    weight = max(0, min(POOL_TOTAL, int(weight)))
    result = pools.apply_edit(project.pools[d][which], {int(cid): weight}, deck=which == "deck")
    if result is None:
        if which == "deck":
            raise ValueError(f"A deck pool needs at least {DECK_POOL_MIN_CARDS} cards with a chance above 0.")
        raise ValueError("A drop pool needs at least one card with a chance above 0.")
    project.pools[d][which] = result
    _save()
    return pool(d, which)


def pool_replace(d: int, which: str, rows_json: str) -> str:
    """The whole pool at once ({card: weight}), brought to 2048 keeping its
    proportions."""
    project = _project()
    rows = {int(c): int(w) for c, w in json.loads(rows_json).items() if int(w) > 0}
    result = pools.normalize(rows)
    if not result or (which == "deck" and len(result) < DECK_POOL_MIN_CARDS):
        raise ValueError("That pool has too few cards.")
    project.pools[d][which] = result
    _save()
    return pool(d, which)


def pool_revert(d: int, which: str) -> str:
    _project().revert_pool(d, which)
    _save()
    return pool(d, which)


# --- card art --------------------------------------------------------------------

def art_png(cid: int, part: str, path: str) -> bool:
    """The card part as the game shows it, as a PNG at `path`; False when
    there is none to show."""
    project = _project()
    image, _where = art.shown_image(project, state["files"].wa, int(cid), part)
    if image is None:
        return False
    Path(path).write_bytes(pngio.encode(image))
    return True


def art_status(cid: int) -> str:
    project = _project()
    cid = int(cid)
    out = {}
    for part in ("art", "thumbnail"):
        _image, where = art.shown_image(project, state["files"].wa, cid, part)
        out[part] = {"from": where, "changed": (cid, part) in art.state(project).images}
    return _out(out)


def art_set(cid: int, part: str, path: str) -> str:
    """The PNG at `path` as the card's picture (or thumbnail)."""
    project = _project()
    image = pngio.decode(Path(path).read_bytes())
    notes = art.set_image(project, int(cid), part, image)
    _save()
    return _out(notes)


def art_revert(cid: int, part: str = "art") -> str:
    art.revert(_project(), int(cid), part)
    _save()
    return art_status(cid)


def art_changed() -> str:
    return _out(sorted(art.changed_cards(_project())))
