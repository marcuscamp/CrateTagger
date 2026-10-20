"""
CrateTagger — local music metadata finder and tag editor.
Designed for DJs, crate diggers, and anyone with a large music collection.
Developed by Marcus A. Campbell 
Github: marcuscamp | Instagram: @its.marcusc | Dj Page: @mrcs.freq

APIs:
  * AcoustID: identifies audio from an acoustic fingerprint (requires a free API key).
  * MusicBrainz: looks up recording/release metadata (no API key for ordinary non-commercial use).
  * Cover Art Archive: optional album artwork (no API key).

Install:
  python -m pip install mutagen requests pyacoustid
  Install Chromaprint's `fpcalc` command and make sure it is on PATH.
  Set ACoustID key (Windows PowerShell):
      $env:ACOUSTID_API_KEY="your_key_here"
  Then run:
      python cratetagger.py

The app never changes files during scanning. Review matches and click "Write selected tags".
"""

from __future__ import annotations

import io
import os
import queue
import threading
import time
import tkinter as tk
from dotenv import load_dotenv
from tkinter import filedialog, messagebox, ttk
from pathlib import Path
from typing import Any

import requests
from mutagen import File as MutagenFile
from mutagen.id3 import ID3, APIC, error as ID3Error, TALB, TPE1, TPE2, TIT2, TCON, TDRC, TRCK, TPOS, COMM
from mutagen.flac import FLAC, Picture
from mutagen.mp4 import MP4, MP4Cover

load_dotenv()

ACOUSTID_API_KEY = os.getenv("ACOUSTID_API_KEY")

APP_NAME = "CrateTagger"
APP_VERSION = "1.0.0"
AUDIO_EXTENSIONS = {
    ".mp3", ".wav", ".flac", ".m4a", ".mp4", ".aac", ".ogg", ".opus", ".aiff", ".aif", ".wma"
}
MB_BASE = "https://musicbrainz.org/ws/2"
COVER_BASE = "https://coverartarchive.org/release"
USER_AGENT = f"{APP_NAME}/{APP_VERSION} (local music library tagger)"
HTTP_TIMEOUT = 12


def get_audio_files(paths: list[str], recursive: bool = True) -> list[Path]:
    """Collect supported files, deduplicating paths and sorting deterministically."""
    found: set[Path] = set()
    for raw in paths:
        p = Path(raw).expanduser()
        if p.is_file() and p.suffix.lower() in AUDIO_EXTENSIONS:
            found.add(p.resolve())
        elif p.is_dir():
            iterator = p.rglob("*") if recursive else p.glob("*")
            for child in iterator:
                if child.is_file() and child.suffix.lower() in AUDIO_EXTENSIONS:
                    found.add(child.resolve())
    return sorted(found, key=lambda p: str(p).casefold())


def current_tags(path: Path) -> dict[str, str]:
    audio = MutagenFile(path, easy=True)
    if audio is None:
        return {}
    def first(key: str) -> str:
        val = audio.get(key, [])
        if isinstance(val, list):
            return str(val[0]) if val else ""
        return str(val or "")
    return {
        "title": first("title"),
        "artist": first("artist"),
        "album": first("album"),
        "date": first("date"),
        "genre": first("genre"),
        "tracknumber": first("tracknumber"),
        "albumartist": first("albumartist"),
        "discnumber": first("discnumber"),
    }

def best_genre(data: dict[str, Any]) -> str:
    """Return the most popular genre, falling back to general tags."""
    for field in ("genres", "tags"):
        items = data.get(field) or []

        if items:
            best = max(
                items,
                key=lambda item: int(item.get("count", 0))
            )
            name = str(best.get("name", "")).strip()

            if name:
                return name

    return ""


def lookup_genre(entity_type: str, mbid: str) -> str:
    """Look up genre metadata for a MusicBrainz entity."""
    if not mbid:
        return ""

    # Respect MusicBrainz's request rate limit.
    time.sleep(1.1)

    try:
        response = requests.get(
            f"{MB_BASE}/{entity_type}/{mbid}",
            params={"fmt": "json", "inc": "genres+tags"},
            headers={"User-Agent": USER_AGENT},
            timeout=HTTP_TIMEOUT,
        )

        if response.ok:
            return best_genre(response.json())

    except (requests.RequestException, ValueError):
        pass

    return ""

def identify(path: Path, api_key: str, fetch_art: bool = True) -> dict[str, Any]:
    """Fingerprint one track and enrich it from MusicBrainz."""
    if not api_key:
        raise RuntimeError("Missing AcoustID API key. Add ACOUSTID_API_KEY to your environment.")
    try:
        import acoustid
    except ImportError as exc:
        raise RuntimeError("pyacoustid is not installed. Run: python -m pip install pyacoustid") from exc

    # fingerprint() invokes the local Chromaprint fpcalc executable.
    duration, fingerprint = acoustid.fingerprint_file(str(path))
    result = acoustid.lookup(api_key, fingerprint, duration, meta="recordings releasegroups releases")
    if result.get("status") != "ok":
        raise RuntimeError(f"AcoustID returned status: {result.get('status', 'unknown')}")

    candidates = []
    for hit in result.get("results", []):
        score = float(hit.get("score", 0))
        for rec in hit.get("recordings", []):
            rec = dict(rec)
            rec["_score"] = score
            candidates.append(rec)
    if not candidates:
        raise RuntimeError("No fingerprint match found.")

    # Prefer strongest fingerprint match; then choose a release with a date when available.
    candidates.sort(key=lambda r: (r["_score"], bool(r.get("releases"))), reverse=True)
    rec = candidates[0]
    rec_id = rec.get("id")
    metadata: dict[str, Any] = {
        "score": rec.get("_score", 0),
        "recording_id": rec_id or "",
        "title": rec.get("title", ""),
        "artist": "",
        "album": "",
        "date": "",
        "genre": "",
        "tracknumber": "",
        "albumartist": "",
        "discnumber": "",
        "cover": None,
        "source": "AcoustID",
    }

    artist_credits = rec.get("artists", [])
    metadata["artist"] = " & ".join(a.get("name", "") for a in artist_credits if a.get("name"))
    releases = rec.get("releases", [])
    release = sorted(
        releases,
        key=lambda r: (bool(r.get("date")), bool(r.get("country") == "US")),
        reverse=True
    )[0] if releases else {}
    metadata["album"] = release.get("title", "")
    metadata["date"] = release.get("date", "")[:4]
    # Do not infer track/disc numbers from medium-track-count: that is the
    # number of tracks on a medium, not this recording's position.
    # Leave these blank unless a source supplies the actual positions.
    metadata["albumartist"] = metadata["artist"]

    # MusicBrainz provides richer recording/release data; respect its one-request-per-second guidance.
    if rec_id:
        try:
            response = requests.get(
                f"{MB_BASE}/recording/{rec_id}",
                params={
                    "fmt": "json",
                    "inc": "artist-credits+tags+genres+releases+release-groups",
                },
                headers={"User-Agent": USER_AGENT},
                timeout=HTTP_TIMEOUT,
            )
            if response.ok:
                detail = response.json()
                credits = detail.get("artist-credit", [])
                names = [c.get("name") or c.get("artist", {}).get("name", "") for c in credits if isinstance(c, dict)]
                names = [n for n in names if n]
                if names:
                    metadata["artist"] = " & ".join(names)
                    metadata["albumartist"] = metadata["artist"]
                tags = detail.get("tags", [])
                if tags:
                    metadata["genre"] = max(tags, key=lambda t: int(t.get("count", 0))).get("name", "")
                detail_releases = detail.get("releases", [])
                if detail_releases:
                    detail_releases.sort(key=lambda r: bool(r.get("date")), reverse=True)
                    rel = detail_releases[0]
                    metadata["album"] = rel.get("title") or metadata["album"]
                    metadata["date"] = (rel.get("date") or metadata["date"])[:4]
                    metadata["release_id"] = rel.get("id", "")

                # GENRE LOOKUP: recording -> release group -> artist
                if not metadata.get("genre"):

                    # Try the release groups associated with this recording.
                    release_group_ids = []

                    for group in detail.get("release-groups", []):
                        if group.get("id"):
                            release_group_ids.append(group["id"])

                    # Some responses expose the release group within each release.
                    for release_item in detail.get("releases", []):
                        group = release_item.get("release-group") or {}
                        if group.get("id"):
                            release_group_ids.append(group["id"])

                    # Ask MusicBrainz for genre data for each available group.
                    for group_id in dict.fromkeys(release_group_ids):
                        genre = lookup_genre("release-group", group_id)

                        if genre:
                            metadata["genre"] = genre
                            break

                    # If the album/release group has no genre, try the artist.
                    if not metadata.get("genre"):
                        for credit in credits:
                            if not isinstance(credit, dict):
                                continue

                            artist_info = credit.get("artist") or {}
                            artist_id = artist_info.get("id")

                            if artist_id:
                                genre = lookup_genre("artist", artist_id)

                                if genre:
                                    metadata["genre"] = genre
                                    break
        except requests.RequestException:
            pass

    if fetch_art and metadata.get("release_id"):
        try:
            art = requests.get(
                f"{COVER_BASE}/{metadata['release_id']}/front-250",
                headers={"User-Agent": USER_AGENT},
                timeout=HTTP_TIMEOUT,
            )
            if art.ok and art.headers.get("content-type", "").startswith("image/"):
                metadata["cover"] = art.content
        except requests.RequestException:
            pass
    return metadata


def write_tags(path: Path, metadata: dict[str, Any], fill_only: bool = True) -> list[str]:
    """Write metadata for MP3, FLAC, MP4/M4A, Ogg/Opus, and WAV where Mutagen supports it."""
    changed: list[str] = []
    ext = path.suffix.lower()
    audio = MutagenFile(path)
    if audio is None:
        raise RuntimeError("Mutagen could not open this audio file.")

    def should_set(key: str, current: Any) -> bool:
        return bool(metadata.get(key)) and (not fill_only or not current)

    # MP3 ID3 tags
    if ext == ".mp3":
        if audio.tags is None:
            audio.add_tags()
        tags = audio.tags
        mapping = {
            "title": ("TIT2", TIT2),
            "artist": ("TPE1", TPE1),
            "album": ("TALB", TALB),
            "date": ("TDRC", TDRC),
            "genre": ("TCON", TCON),
            "tracknumber": ("TRCK", TRCK),
            "discnumber": ("TPOS", TPOS),
            "albumartist": ("TPE2", TPE2),
        }
        for key, (frame_id, frame_cls) in mapping.items():
            value = str(metadata.get(key, "") or "")
            existing = str(tags.get(frame_id, "") or "")
            if should_set(key, existing):
                tags.delall(frame_id)
                tags.add(frame_cls(encoding=3, text=value))
                changed.append(key)
        if metadata.get("cover") and not tags.getall("APIC"):
            tags.add(APIC(encoding=3, mime="image/jpeg", type=3, desc="Cover", data=metadata["cover"]))
            changed.append("cover")
        audio.save()
        return changed

    # FLAC
    if isinstance(audio, FLAC):
        mapping = {
            "title": "title", "artist": "artist", "album": "album", "date": "date",
            "genre": "genre", "tracknumber": "tracknumber", "discnumber": "discnumber",
            "albumartist": "albumartist",
        }
        for key, tag in mapping.items():
            value = str(metadata.get(key, "") or "")
            if should_set(key, audio.get(tag, [""])[0] if audio.get(tag) else ""):
                audio[tag] = value
                changed.append(key)
        if metadata.get("cover") and not audio.pictures:
            pic = Picture()
            pic.data = metadata["cover"]
            pic.type = 3
            pic.mime = "image/jpeg"
            pic.desc = "Cover"
            audio.add_picture(pic)
            changed.append("cover")
        audio.save()
        return changed

    # MP4/M4A/AAC
    if isinstance(audio, MP4):
        mapping = {
            "title": "\xa9nam", "artist": "\xa9ART", "album": "\xa9alb", "date": "\xa9day",
            "genre": "\xa9gen", "tracknumber": "trkn", "discnumber": "disk", "albumartist": "aART",
        }
        for key, tag in mapping.items():
            value = str(metadata.get(key, "") or "")
            current = audio.get(tag, [])
            current_text = str(current[0]) if current else ""
            if should_set(key, current_text):
                if key in ("tracknumber", "discnumber"):
                    try:
                        number = int(value.split("/")[0])
                        audio[tag] = [(number, 0)]
                    except ValueError:
                        continue
                else:
                    audio[tag] = [value]
                changed.append(key)
        if metadata.get("cover") and "covr" not in audio:
            fmt = MP4Cover.FORMAT_JPEG if metadata["cover"].startswith(b"\xff\xd8") else MP4Cover.FORMAT_PNG
            audio["covr"] = [MP4Cover(metadata["cover"], imageformat=fmt)]
            changed.append("cover")
        audio.save()
        return changed

    # Generic Easy tags (Ogg, Opus, WAV, AIFF, etc.). Artwork support varies by format.
    easy = MutagenFile(path, easy=True)
    if easy is None:
        raise RuntimeError(f"Unsupported tagging format: {ext}")
    for key in ("title", "artist", "album", "date", "genre", "tracknumber", "discnumber", "albumartist"):
        value = str(metadata.get(key, "") or "")
        current = easy.get(key, [""])[0] if easy.get(key) else ""
        if should_set(key, current):
            easy[key] = [value]
            changed.append(key)
    easy.save()
    return changed


class CrateTaggerApp(tk.Tk):
    def __init__(self):
        super().__init__()
        self.title("CrateTagger • Music Metadata Studio")
        self.geometry("1240x760")
        self.minsize(960, 600)
        self.configure(bg="#111318")
        self.paths: list[Path] = []
        self.rows: dict[str, dict[str, Any]] = {}
        self.events: queue.Queue = queue.Queue()
        self.busy = False
        self._setup_style()
        self._build_ui()
        self.after(100, self._poll_events)

    def _setup_style(self):
        style = ttk.Style(self)
        style.theme_use("clam")
        style.configure(".", font=("Segoe UI", 10))
        style.configure("Treeview", background="#191c23", foreground="#e8eaf0",
                        fieldbackground="#191c23", rowheight=30, borderwidth=0)
        style.configure("Treeview.Heading", background="#252a35", foreground="#b9c2d0",
                        font=("Segoe UI Semibold", 9), padding=8)
        style.map("Treeview", background=[("selected", "#343d50")], foreground=[("selected", "#ffffff")])
        style.configure("TProgressbar", troughcolor="#252a35", background="#7c9cff")
        style.configure("TCheckbutton", background="#111318", foreground="#d7dbe4")
        style.map("TCheckbutton", background=[("active", "#111318")], foreground=[("active", "#ffffff")])

    def _build_ui(self):
        header = tk.Frame(self, bg="#111318")
        header.pack(fill="x", padx=24, pady=(20, 12))
        tk.Label(header, text="CRATETAGGER", bg="#111318", fg="#f5f7fb",
                 font=("Segoe UI Semibold", 20)).pack(side="left")
        tk.Label(header, text="MUSIC METADATA STUDIO", bg="#111318", fg="#7f8ba3",
                 font=("Segoe UI", 9)).pack(side="left", padx=(14, 0), pady=(7, 0))
        self.status_var = tk.StringVar(value="Ready • Add files or scan a folder")
        tk.Label(header, textvariable=self.status_var, bg="#111318", fg="#9ca8bb",
                 font=("Segoe UI", 9)).pack(side="right", pady=(7, 0))

        toolbar = tk.Frame(self, bg="#191c23", padx=14, pady=12)
        toolbar.pack(fill="x", padx=24, pady=(0, 14))
        self._button(toolbar, "＋ Add files", self.add_files, primary=True).pack(side="left", padx=(0, 8))
        self._button(toolbar, "▣ Scan folder", self.add_folder).pack(side="left", padx=(0, 8))
        self._button(toolbar, "⌕ Identify tracks", self.identify_selected).pack(side="left", padx=(0, 8))
        self._button(toolbar, "✓ Write selected tags", self.write_selected, primary=True).pack(side="left")
        self._button(toolbar, "Clear list", self.clear_list).pack(side="right")

        options = tk.Frame(self, bg="#111318")
        options.pack(fill="x", padx=26, pady=(0, 10))
        self.recursive_var = tk.BooleanVar(value=True)
        ttk.Checkbutton(options, text="Include subfolders when scanning", variable=self.recursive_var).pack(side="left")
        self.fill_only_var = tk.BooleanVar(value=True)
        ttk.Checkbutton(options, text="Fill missing fields only (recommended)", variable=self.fill_only_var).pack(side="left", padx=(22, 0))
        self.art_var = tk.BooleanVar(value=True)
        ttk.Checkbutton(options, text="Fetch album artwork", variable=self.art_var).pack(side="left", padx=(22, 0))

        table_frame = tk.Frame(self, bg="#111318")
        table_frame.pack(fill="both", expand=True, padx=24)
        columns = ("status", "title", "artist", "album", "year", "genre", "confidence", "file")
        self.tree = ttk.Treeview(table_frame, columns=columns, show="headings", selectmode="extended")
        headings = {
            "status": "STATUS", "title": "TITLE", "artist": "ARTIST", "album": "ALBUM",
            "year": "YEAR", "genre": "GENRE", "confidence": "MATCH", "file": "FILE"
        }
        widths = {"status": 105, "title": 190, "artist": 165, "album": 165, "year": 65,
                  "genre": 110, "confidence": 78, "file": 230}
        for col in columns:
            self.tree.heading(col, text=headings[col])
            self.tree.column(col, width=widths[col], minwidth=55, anchor="w")
        yscroll = ttk.Scrollbar(table_frame, orient="vertical", command=self.tree.yview)
        xscroll = ttk.Scrollbar(table_frame, orient="horizontal", command=self.tree.xview)
        self.tree.configure(yscrollcommand=yscroll.set, xscrollcommand=xscroll.set)
        self.tree.grid(row=0, column=0, sticky="nsew")
        yscroll.grid(row=0, column=1, sticky="ns")
        xscroll.grid(row=1, column=0, sticky="ew")
        table_frame.rowconfigure(0, weight=1)
        table_frame.columnconfigure(0, weight=1)
        self.tree.bind("<<TreeviewSelect>>", self.show_details)

        self.detail = tk.Text(self, height=6, bg="#191c23", fg="#d7dbe4", insertbackground="white",
                              relief="flat", padx=14, pady=10, font=("Consolas", 10), wrap="word")
        self.detail.pack(fill="x", padx=24, pady=(12, 10))
        self.detail.insert("1.0", "Select a track to inspect its current tags and proposed metadata. Scanning never modifies your files.")
        self.detail.configure(state="disabled")

        footer = tk.Frame(self, bg="#111318")
        footer.pack(fill="x", padx=24, pady=(0, 16))
        self.progress = ttk.Progressbar(footer, mode="determinate")
        self.progress.pack(side="left", fill="x", expand=True, padx=(0, 14))
        tk.Label(footer, text="Local-first • Review before writing • No audio uploads by this app",
                 bg="#111318", fg="#758198", font=("Segoe UI", 9)).pack(side="right")

    def _button(self, parent, label, command, primary=False):
        return tk.Button(parent, text=label, command=command, bg=("#7c9cff" if primary else "#292e39"),
                         fg=("#111318" if primary else "#e7eaf1"), activebackground="#9db4ff",
                         activeforeground="#111318", relief="flat", borderwidth=0,
                         padx=13, pady=9, cursor="hand2", font=("Segoe UI Semibold", 9))

    def add_files(self):
        names = filedialog.askopenfilenames(title="Choose audio files",
            filetypes=[("Audio files", "*.mp3 *.wav *.flac *.m4a *.mp4 *.aac *.ogg *.opus *.aiff *.aif *.wma"),
                       ("All files", "*.*")])
        if names:
            self._add_paths(list(names))

    def add_folder(self):
        folder = filedialog.askdirectory(title="Choose music folder")
        if folder:
            files = get_audio_files([folder], self.recursive_var.get())
            self._add_paths([str(p) for p in files])

    def _add_paths(self, names):
        existing = {str(p) for p in self.paths}
        new_paths = [Path(n).resolve() for n in names if Path(n).is_file() and str(Path(n).resolve()) not in existing]
        self.paths.extend(new_paths)
        for path in new_paths:
            tags = current_tags(path)
            iid = str(path)
            self.rows[iid] = {"path": path, "current": tags, "metadata": {}, "status": "Ready"}
            self.tree.insert("", "end", iid=iid, values=("Ready", tags.get("title") or "—",
                tags.get("artist") or "—", tags.get("album") or "—", tags.get("date") or "—",
                tags.get("genre") or "—", "—", path.name))
        self.status_var.set(f"{len(self.paths)} tracks in queue")

    def clear_list(self):
        if self.busy:
            return
        self.paths.clear()
        self.rows.clear()
        for item in self.tree.get_children():
            self.tree.delete(item)
        self.status_var.set("Ready • Add files or scan a folder")
        self._set_detail("Select a track to inspect its current tags and proposed metadata.")

    def identify_selected(self):
        if self.busy:
            return
        selected = list(self.tree.selection())
        targets = selected if selected else list(self.tree.get_children())
        if not targets:
            messagebox.showinfo("Nothing to identify", "Add some audio files first.")
            return
        api_key = os.getenv("ACOUSTID_API_KEY", "").strip()
        if not api_key:
            messagebox.showerror("AcoustID API key required",
                "Create a free AcoustID application key, then set the ACOUSTID_API_KEY environment variable.\n\n"
                "Windows PowerShell:\n$env:ACOUSTID_API_KEY=\"your_key_here\"\n\n"
                "Restart this app after setting it.")
            return
        self.busy = True
        self.progress.configure(maximum=len(targets), value=0)
        self.status_var.set(f"Identifying 0 / {len(targets)} tracks…")
        threading.Thread(target=self._identify_worker, args=(targets, api_key), daemon=True).start()

    def _identify_worker(self, targets, api_key):
        for index, iid in enumerate(targets, 1):
            path = self.rows[iid]["path"]
            self.events.put(("status", iid, "Fingerprinting…"))
            try:
                result = identify(path, api_key, self.art_var.get())
                self.events.put(("identified", iid, result))
            except Exception as exc:
                self.events.put(("failed", iid, str(exc)))
            self.events.put(("progress", index, len(targets)))
            # MusicBrainz requests are limited to one per second; pause between tracks.
            if index < len(targets):
                time.sleep(1.05)
        self.events.put(("finished",))

    def write_selected(self):
        selected = list(self.tree.selection())
        if not selected:
            messagebox.showinfo("Select tracks", "Select one or more identified tracks to write.")
            return
        ready = [iid for iid in selected if self.rows.get(iid, {}).get("metadata")]
        if not ready:
            messagebox.showinfo("No metadata", "Identify the selected tracks first.")
            return
        mode = "only missing fields" if self.fill_only_var.get() else "all proposed fields"
        if not messagebox.askyesno("Confirm tag changes",
                f"Write metadata to {len(ready)} file(s), updating {mode}?\n\n"
                "This edits the audio files in place. Consider making a backup first."):
            return
        self.busy = True
        self.progress.configure(maximum=len(ready), value=0)
        threading.Thread(target=self._write_worker, args=(ready, self.fill_only_var.get()), daemon=True).start()

    def _write_worker(self, targets, fill_only):
        for index, iid in enumerate(targets, 1):
            row = self.rows[iid]
            try:
                changed = write_tags(row["path"], row["metadata"], fill_only=fill_only)
                self.events.put(("written", iid, changed))
            except Exception as exc:
                self.events.put(("failed", iid, f"Write failed: {exc}"))
            self.events.put(("progress", index, len(targets)))
        self.events.put(("finished",))

    def _poll_events(self):
        try:
            while True:
                event = self.events.get_nowait()
                kind = event[0]
                if kind == "status":
                    _, iid, status = event
                    self._set_row_status(iid, status)
                elif kind == "identified":
                    _, iid, metadata = event
                    self.rows[iid]["metadata"] = metadata
                    self._render_row(iid, "Matched")
                elif kind == "failed":
                    _, iid, error = event
                    self.rows[iid]["error"] = error
                    self._set_row_status(iid, "No match / error")
                elif kind == "written":
                    _, iid, changed = event
                    self.rows[iid]["written"] = changed
                    self.rows[iid]["current"] = current_tags(self.rows[iid]["path"])
                    self._render_row(iid, "Tagged" if changed else "Already complete")
                elif kind == "progress":
                    _, value, maximum = event
                    self.progress.configure(maximum=maximum, value=value)
                    self.status_var.set(f"Working… {value} / {maximum}")
                elif kind == "finished":
                    self.busy = False
                    self.status_var.set("Finished • Review the results below")
        except queue.Empty:
            pass
        self.after(100, self._poll_events)

    def _set_row_status(self, iid, status):
        if iid not in self.rows:
            return
        self.rows[iid]["status"] = status
        self._render_row(iid, status)

    def _render_row(self, iid, status=None):
        row = self.rows[iid]
        tags = row.get("metadata") or row.get("current", {})
        score = tags.get("score")
        match = f"{score:.0%}" if isinstance(score, (float, int)) else "—"
        vals = (status or row.get("status", "Ready"), tags.get("title") or "—",
                tags.get("artist") or "—", tags.get("album") or "—", tags.get("date") or "—",
                tags.get("genre") or "—", match, row["path"].name)
        self.tree.item(iid, values=vals)

    def show_details(self, _event=None):
        selected = self.tree.selection()
        if not selected:
            return
        row = self.rows[selected[0]]
        current = row.get("current", {})
        meta = row.get("metadata", {})
        lines = [f"FILE  {row['path']}", "", "CURRENT TAGS"]
        lines.extend(f"  {k:12} {v or '—'}" for k, v in current.items())
        if meta:
            lines += ["", f"PROPOSED METADATA  •  fingerprint match {meta.get('score', 0):.0%}"]
            lines.extend(f"  {k:12} {meta.get(k) or '—'}" for k in
                         ("title", "artist", "album", "date", "genre", "tracknumber", "discnumber", "albumartist"))
            lines.append(f"  {'artwork':12} {'available' if meta.get('cover') else 'not found'}")
        if row.get("error"):
            lines += ["", "MESSAGE", f"  {row['error']}"]
        if row.get("written") is not None:
            lines += ["", "WRITTEN FIELDS", "  " + (", ".join(row["written"]) if row["written"] else "No changes needed")]
        self._set_detail("\n".join(lines))

    def _set_detail(self, text):
        self.detail.configure(state="normal")
        self.detail.delete("1.0", "end")
        self.detail.insert("1.0", text)
        self.detail.configure(state="disabled")


if __name__ == "__main__":
    app = CrateTaggerApp()
    app.mainloop()
