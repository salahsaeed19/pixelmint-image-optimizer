# Image Optimizer

A small, self-hosted Django web app for compressing, resizing and converting images. Upload one or many JPG, PNG or WebP files, tune the settings, and download the optimized results individually or as a ZIP. Every run is recorded in a persistent history.

## Features

- Upload one or several images, with **drag & drop** and instant previews
- **JPG / JPEG / PNG / WebP** input, max **15 MB** per image and **10 images** per batch
- Compression **quality 10–100** (default **80**) with a live value readout
- **Resize** by width and/or height, with optional **aspect-ratio preservation** (images are never enlarged)
- Keep the original format or convert to **JPG, PNG or WebP**
- Correct transparency handling: transparent PNG/WebP becomes a **white background** when saved as JPG
- Honest statistics: original/optimized dimensions, file sizes, bytes saved and reduction %. If the result is larger than the source, it is shown as larger
- Individual download and **Download all (ZIP)**
- **History** page (newest first, paginated), stored in SQLite
- **Django Admin** integration for the history records
- Real image validation with Pillow (the file extension is never trusted), EXIF orientation handling, UUID file names, CSRF protection, and friendly error messages

## Stack

Python 3.13 · Django 5.2 · SQLite3 · Pillow · Django templates · HTML/CSS · vanilla JavaScript (no frontend libraries)

## Setup (Windows, PowerShell)

```powershell
cd D:\Works\Python\Django\django-image-optimizer

# 1. Create the virtual environment
py -3.13 -m venv .venv

# 2. Install dependencies
.\.venv\Scripts\python.exe -m pip install --upgrade pip
.\.venv\Scripts\python.exe -m pip install -r requirements.txt

# 3. Create the SQLite database
.\.venv\Scripts\python.exe manage.py migrate

# 4. (Optional) create an admin user for /admin/
.\.venv\Scripts\python.exe manage.py createsuperuser
```

## Run

```powershell
.\.venv\Scripts\python.exe manage.py runserver 127.0.0.1:8000
```

Open **http://127.0.0.1:8000/**

| URL | Page |
| --- | --- |
| `/` | Upload and optimize |
| `/history/` | Optimization history |
| `/admin/` | Django Admin |

## Tests and checks

```powershell
.\.venv\Scripts\python.exe manage.py makemigrations --check
.\.venv\Scripts\python.exe manage.py check
.\.venv\Scripts\python.exe manage.py test
```

Tests generate all images programmatically with Pillow and use a temporary `MEDIA_ROOT` that is deleted afterwards.

## Project layout

```
config/                     Django project (settings, root URLs)
optimizer/
  models.py                 OptimizationRecord (metadata only, no image binaries)
  forms.py                  Upload + settings validation
  views.py                  Thin views: home, results, history, downloads
  services/
    image_processing.py     Pure Pillow logic (validate, orient, resize, convert, encode)
    batch.py                Processes a batch, saves files and history rows
    naming.py               Safe/UUID filenames
  templates/optimizer/      Django templates
  static/optimizer/         styles.css, app.js
  tests/                    Unit and integration tests
media/                      Created at runtime: originals/ and optimized/ (git-ignored)
```

## Configuration

Limits live in `config/settings.py` (`OPTIMIZER_MAX_FILE_SIZE`, `OPTIMIZER_MAX_FILES`, `OPTIMIZER_MAX_PIXELS`, ...). Optional environment variables: `DJANGO_DEBUG` (default `1`), `DJANGO_SECRET_KEY`, and `DJANGO_TIME_ZONE` (default `UTC`, e.g. `Africa/Cairo`).

## Notes and limitations

- **PNG is lossless**, so the quality slider does not change PNG output; PNG files are re-encoded with maximum compression. For stronger savings convert to JPG or WebP.
- Metadata such as EXIF is stripped (orientation is applied to the pixels first; ICC profiles are kept). Animated WebP/PNG inputs are reduced to their first frame, and a warning is shown.
- Both the uploaded original and the optimized file are kept in `media/` (under random UUID names) so previews and history work. Deleting a history record in the admin also deletes its files.
- This is a local/development setup: `DEBUG` defaults to on and `/media/` is served by Django's development server only. For production, set `DJANGO_DEBUG=0`, a real `DJANGO_SECRET_KEY`, adjust `ALLOWED_HOSTS`, and serve `MEDIA_ROOT` from a web server.
- There are no user accounts: the history is shared by everyone who can reach the site.
