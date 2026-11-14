"""Pull step screenshots out of a Kane .evidence pack (a plain zip) into report/assets/<claim-id>/.

Pack layout (Day 1): tests/<name>/steps/<n>-<flow>-<n>/{screenshot.jpg, annotated.png, step.json}.
Order: session_dir/evidence/*.evidence first, then run_dir (legacy). If nothing unpacks, return no frames:
the report card then shows step remarks, the test_url link and the `kane-cli evidence serve` command.
Zip members are only read, never extracted by name; files are written under names this module picks.
"""
from __future__ import annotations

import re
import zipfile
from pathlib import Path

STEP_RE = re.compile(r"^(?P<test>.*?)/?steps/(?P<n>\d+)-[^/]*/(?P<file>annotated\.png|screenshot\.jpg)$")
MAX_BYTES = 10 * 1024 * 1024


def find_pack(session_dir: str | None, run_dir: str | None = None) -> Path | None:
    for base in (session_dir, run_dir):
        if not base or not Path(base).is_dir():
            continue
        packs = sorted(Path(base).rglob("*.evidence"), key=lambda p: p.stat().st_mtime)
        if packs:
            return packs[-1]
    return None


def _pick(entries: dict[tuple[str, int], dict[str, object]]) -> list[tuple[int, str, object]]:
    """entries: (test, n) -> {file name: handle}. Prefer annotated.png. Return ordered (n, ext, handle)."""
    tests: list[str] = []
    for (t, _n) in entries:
        if t not in tests:
            tests.append(t)
    out = []
    for (t, n) in sorted(entries, key=lambda k: (tests.index(k[0]), k[1])):
        files = entries[(t, n)]
        name = "annotated.png" if "annotated.png" in files else "screenshot.jpg"
        out.append((n, Path(name).suffix, files[name]))
    return out


def _from_zip(pack: Path, dest: Path) -> list[dict]:
    entries: dict[tuple[str, int], dict[str, object]] = {}
    with zipfile.ZipFile(pack) as z:
        for info in z.infolist():
            m = STEP_RE.match(info.filename)
            if m and info.file_size <= MAX_BYTES:
                entries.setdefault((m["test"], int(m["n"])), {})[m["file"]] = info
        frames = []
        for i, (n, ext, info) in enumerate(_pick(entries), 1):
            name = f"{i:02d}-step{n}{ext}"
            (dest / name).write_bytes(z.read(info))  # type: ignore[arg-type]
            frames.append({"file": name, "step": n, "annotated": ext == ".png"})
    return frames


def _from_dir(run_dir: Path, dest: Path) -> list[dict]:
    entries: dict[tuple[str, int], dict[str, object]] = {}
    for p in run_dir.rglob("*"):
        m = STEP_RE.match(p.relative_to(run_dir).as_posix())
        if m and p.is_file() and p.stat().st_size <= MAX_BYTES:
            entries.setdefault((m["test"], int(m["n"])), {})[m["file"]] = p
    frames = []
    for i, (n, ext, src) in enumerate(_pick(entries), 1):
        name = f"{i:02d}-step{n}{ext}"
        (dest / name).write_bytes(Path(src).read_bytes())  # type: ignore[arg-type]
        frames.append({"file": name, "step": n, "annotated": ext == ".png"})
    return frames


def collect(session_dir: str | None, run_dir: str | None, dest: Path) -> dict:
    """Return {"pack": str|None, "frames": [...]}; frames are file names inside dest. Never raises."""
    pack = find_pack(session_dir, run_dir)
    frames: list[dict] = []
    dest.mkdir(parents=True, exist_ok=True)
    for old in dest.glob("*"):
        if old.is_file():
            old.unlink()
    if pack:
        try:
            frames = _from_zip(pack, dest)
        except (zipfile.BadZipFile, OSError, KeyError):
            frames = []
    if not frames and run_dir and Path(run_dir).is_dir():
        try:
            frames = _from_dir(Path(run_dir), dest)
        except OSError:
            frames = []
    return {"pack": str(pack) if pack else None, "frames": frames}
