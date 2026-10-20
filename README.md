# CrateTagger 🎧

**Identify tracks. Enrich metadata. Keep your DJ library organized.**

CrateTagger is a Python desktop application designed to make
music-library cleanup less manual. It fingerprints audio to help
identify tracks, retrieves available metadata from music databases, and
lets you review proposed changes before writing tags to your files.

Whether you're organizing a growing DJ crate or cleaning up a folder of
tracks with missing information, CrateTagger brings identification and
metadata tagging into one workflow.

> **Important:** CrateTagger does not upload your audio files to a
> music-recognition service. It generates an acoustic fingerprint
> locally and sends that fingerprint to AcoustID for matching. Metadata
> lookups and optional cover-art requests require an internet
> connection.

## ✨ Features

-   **Audio fingerprint identification** --- uses AcoustID and
    Chromaprint (`fpcalc`) to find likely matches, even when a filename
    is unhelpful.
-   **Metadata enrichment** --- retrieves available title, artist,
    album, release year, and genre information using MusicBrainz.
-   **Genre fallback lookups** --- checks MusicBrainz tags and can try
    related release-group and artist information when recording-level
    genre data is missing.
-   **Optional album artwork** --- looks up available cover art through
    the Cover Art Archive.
-   **Review before writing** --- inspect existing tags and proposed
    metadata before choosing to write changes.
-   **Fill missing fields by default** --- helps preserve metadata you
    have already entered.
-   **Batch processing** --- add individual audio files or scan folders,
    including subfolders.
-   **Progress and error feedback** --- track identification and
    tag-writing work is handled in background threads so the interface
    stays responsive.
-   **Desktop interface** --- a Tkinter GUI shows track status, match
    confidence, current tags, and proposed values.

## 🖥️ Preview

The application includes a track table with status, title, artist,
album, year, genre, match confidence, and filename, plus a detail panel
for current tags and proposed metadata.


https://github.com/user-attachments/assets/6e723d6d-ace7-4021-a4e4-676ff15d7f37


## 🧰 Tech stack

| Technology | Purpose |
|---|---|
| Python | Application logic and orchestration |
| Tkinter / ttk | Desktop graphical interface |
| AcoustID | Audio-fingerprint matching |
| Chromaprint / `fpcalc` | Local audio fingerprint generation |
| MusicBrainz | Recording, release, artist, and tag metadata |
| Cover Art Archive | Optional release artwork |
| Mutagen | Reading and writing audio metadata |
| Requests | HTTP requests to metadata services |
| python-dotenv | Loading local configuration from `.env` |

## 🎵 Supported audio formats

The file picker and scanner are configured for:

`MP3`, `WAV`, `FLAC`, `M4A`, `MP4`, `AAC`, `OGG`, `Opus`, `AIFF`, `AIF`,
and `WMA`.

**Format note:** Reading and writing tag fields and embedding artwork
depend on the container format and what Mutagen supports for that file.
Test on copies of important files before running a large batch.

## ⚙️ Setup

### 1. Install Python

Use a supported Python 3 installation. If `python` is not recognized in
your terminal, use the Python launcher (`py`) on Windows or correct your
PATH.

### 2. Clone or download this repository

``` bash
git clone https://github.com/YOUR-USERNAME/CrateTagger.git
cd CrateTagger
```

Replace the URL with your repository's actual GitHub URL. Alternatively,
download the repository as a ZIP and extract it.

### 3. Create a virtual environment (recommended)

**Windows PowerShell**

``` powershell
py -m venv .venv
.\.venv\Scripts\Activate.ps1
```

**macOS / Linux**

``` bash
python3 -m venv .venv
source .venv/bin/activate
```

### 4. Install Python dependencies

``` bash
python -m pip install -r requirements.txt
```

The `requirements.txt` file includes:

-   `mutagen`
-   `requests`
-   `pyacoustid`
-   `python-dotenv`

### 5. Install Chromaprint (`fpcalc`)

`pyacoustid` relies on the external Chromaprint `fpcalc` executable to
generate fingerprints. Installing the Python requirements alone does
**not** install this executable.

Install a compatible Chromaprint build for your operating system, then
ensure `fpcalc` is available on your system PATH. If it is not on PATH,
configure the path according to your local setup and the version of the
app you are using.

Verify that your terminal can run:

``` bash
fpcalc -version
```

If the command is not recognized, resolve the `fpcalc` installation or
PATH configuration before identifying tracks.

### 6. Configure your AcoustID API key

Track identification requires an AcoustID application API key. Obtain
your own key from the [AcoustID website](https://acoustid.org/).

Create a `.env` file in the same directory as `cratetagger.py`:

``` dotenv
ACOUSTID_API_KEY=your_acoustid_api_key_here
```

If your local `fpcalc` executable is not on PATH and your app
configuration supports an explicit path, configure that path for your
machine.

**Never commit your real `.env` file or API key to GitHub.** The `.env`
file is intended to stay on your computer. Keep `.env` in `.gitignore`;
share only a placeholder `.env.example` if you want to document
configuration.

### 7. Run CrateTagger

``` bash
python cratetagger.py
```

## 🚀 How to use it

1.  **Add tracks** using **Add files**, or choose **Scan folder** to
    load a music folder.
2.  **Choose scan options.** Folder scanning includes subfolders by
    default. Album artwork lookup is optional.
3.  **Select tracks** in the table, or leave the selection empty to
    identify all queued tracks.
4.  Click **Identify tracks**. CrateTagger generates fingerprints and
    looks for matching recordings.
5.  **Review the results.** Select a track to inspect its current tags
    and proposed metadata, including the fingerprint match score.
6.  Select the tracks you want to update and click **Write selected
    tags**.
7.  Confirm the operation. CrateTagger reports which fields were
    changed.

### Fill missing fields vs. overwrite

**Fill missing fields only** is enabled by default. When enabled, the
app writes metadata only into fields that are currently empty. Turning
it off allows proposed values to replace existing values for supported
fields.

Tag writing edits audio files **in place**. Back up important music
libraries before writing changes, and review results before processing a
large collection.

## 🔐 Privacy and API use

-   Audio fingerprint generation happens locally through `fpcalc`.
-   The app sends fingerprints to AcoustID for identification; it does
    not upload the full audio file as part of this workflow.
-   MusicBrainz and Cover Art Archive are contacted over the internet to
    retrieve metadata and artwork.
-   An AcoustID API key is required for track identification. Ordinary
    MusicBrainz metadata lookups do not require a personal API key.
-   MusicBrainz requests are paced to respect its request-rate guidance.
-   Do not share API keys in source code, screenshots, issue reports, or
    commits.

## ⚠️ Limitations

-   Identification depends on the quality and availability of
    fingerprint matches. Some tracks may return no match or an incorrect
    match.
-   A match score is a signal, not a guarantee that the result is
    correct. Review proposed metadata before writing it.
-   Genre information varies by recording and database coverage.
    Fallback lookups may still return no genre or a broad artist-level
    tag.
-   Artwork may be unavailable for some releases.
-   Metadata support varies by audio format. Artwork embedding and
    individual tag fields may behave differently across formats.
-   The application currently focuses on identification and metadata
    tagging. Musical-key detection and Camelot notation are potential
    future enhancements, not features to assume are available in this
    version.

## 🧑‍💻 Development note

CrateTagger was developed with AI-assisted coding and reviewed by a
human during implementation. The project is intended to be iterated on,
tested against real-world audio libraries, and improved as issues are
found.

## 🤝 Feedback and contributions

Found a bug, have an idea, or want to improve compatibility? Open a
GitHub issue with the operating system, Python version, audio format,
and a description of the behavior. **Never include API keys or private
audio files in an issue.**

## 📄 License

No license has been specified yet. Until a license is added to the
repository, others should not assume they have permission to reuse,
modify, or redistribute this code.
