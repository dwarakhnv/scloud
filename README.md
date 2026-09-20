SCloud is a Self-Hosted Cloud for Photo/Video/Media storage (mainly for media)
- Needs to be SUPER mobile friendly, Apple like experience.
- Django with user auth.
- Each user should be able to upload photos/videos/media.
- Should have shared spaces for multiple users to be a part of with ability to share publicly via link.
- Those on phones should be able to sync/upload select files from their photos to the site.
- Have scalable threads to handle multiple requests at a time.
- Be able to have tags on each file to denote certain people.
- Home page is a log in screen unless logged in then it will be their files. Kind of have it like a file browser.
- Have a contants class/file which has all the static details.
- Contants.DATA will be located under... `../data/{user.id}/files/` or under `../data/{group.id}/files/` by default
- Snippets or extreme low quality versions for thumbnails will be under `../data/{user.id}/thumbnails/` by default
- I want to be able to expand or move locations so if I have a external drive to use, it should point to there. Perhaps this data comes from `../config/config.env` which gets read into the constants class.
- Sqlite database at `../data/database.db`
- Store file references in the DB along with thumbnails and metadata like size, date_uploaded, etc.
- Allow users to add tags to the files.
- Filter files via tags + folder.
- Ability to move files. (should move thumbnail accordingly and update in DB as well.)
- Store all code under /src/

## Setup

```bash
pip install -r requirements.txt
cd src
python manage.py migrate
python manage.py createsuperuser
python manage.py runserver
```

Then visit http://localhost:8000 and sign in.

## Configuration

All static/environment configuration lives in [`config/config.env`](config/config.env) and is
read by [`src/scloud/constants.py`](src/scloud/constants.py) (the `Constants` class). Key
settings:

- `DATA_ROOT` — where all user/group files & thumbnails live. Point this at an external drive
  path to move storage off the local disk (e.g. `DATA_ROOT=D:/scloud-data`).
- `DATABASE_PATH` — location of the sqlite database file.
- `SECRET_KEY` / `DEBUG` / `ALLOWED_HOSTS` — standard Django settings, sourced from here instead
  of hardcoding in `settings.py`.
- `MAX_UPLOAD_SIZE_MB` — per-file upload size cap (default 10240 = 10 GB).
- `UPLOAD_CHUNK_SIZE_MB` — size of each piece the browser splits large uploads into (default 8).
- `THUMBNAIL_SIZE` — thumbnail long-edge size in pixels (default 256).
- `EMAIL_HOST` / `EMAIL_PORT` / `EMAIL_HOST_USER` / `EMAIL_HOST_PASSWORD` / `EMAIL_USE_TLS` /
  `DEFAULT_FROM_EMAIL` — outgoing mail for "forgot password" reset links. Leave `EMAIL_HOST`
  blank to print reset emails to the console instead (handy for local dev). For Gmail, create an
  [app password](https://myaccount.google.com/apppasswords) and use `smtp.gmail.com:587`.

### Handling very large uploads (10 GB+)

A few things work together to make multi-gigabyte uploads reliable, not just theoretically
allowed:

- **Chunked, resumable-per-chunk uploads.** The browser (`static/js/app.js`) splits any file
  larger than `UPLOAD_CHUNK_SIZE_MB` into fixed-size pieces and uploads them one at a time to
  `/upload/chunk/`, retrying an individual failed chunk (up to 4 attempts with backoff) instead of
  restarting the whole file. This is what makes a 10 GB upload survive a flaky mobile connection.
- **Streaming to disk, not memory.** `FILE_UPLOAD_MAX_MEMORY_SIZE` is set low (2 MB) so Django
  spools uploaded data straight to a temp file instead of buffering it in RAM.
  `DATA_UPLOAD_MAX_MEMORY_SIZE` is disabled outright since it only ever gated non-file form
  fields, never file content.
- **One filesystem, one drive.** `FILE_UPLOAD_TEMP_DIR` (and the chunk-assembly temp dir) live
  under `Constants.DATA_ROOT` rather than the OS temp directory, so finishing an upload is a fast
  same-drive rename instead of copying gigabytes across drives — and a large `DATA_ROOT` on an
  external drive never gets starved by temp files piling up on a small system drive.
- **Production server limits still need raising to match.** The Django dev server has no request
  size/timeout limits, but a real deployment does:
  - `gunicorn`: increase `--timeout` well beyond the default 30s (large uploads over slow mobile
    links can take minutes), e.g. `--timeout 600`.
  - `nginx` in front of it: `client_max_body_size 11g;` (a little headroom over `MAX_UPLOAD_SIZE_MB`)
    and a generous `proxy_read_timeout`/`proxy_send_timeout` (e.g. `600s`).
  - Consider `client_body_buffering off;`/streaming-friendly proxy settings if you put anything
    else in front of nginx.

On disk, data is organized as:

```
data/
  database.db
  user_<id>/
    files/            # original uploads, original filenames preserved
    thumbnails/        # low-quality jpeg previews, named <file_id>.jpg
  group_<id>/
    files/
    thumbnails/
```

## Architecture notes

- **accounts** app: custom `User` model (`accounts.User`), login/logout views.
- **storage** app: `Group`, `GroupMembership`, `Folder`, `Tag`, `MediaFile`, `ShareLink` models;
  the file-browser UI (My Space / Groups tabs, boxes/list/details views, tag filter chips);
  upload, move, tag, delete and public share-link endpoints.
- Thumbnails are generated on a background `ThreadPoolExecutor`
  (`storage/thumbnails.py`) so upload requests return immediately instead of blocking on
  image/video processing — this is also what keeps the server responsive to other concurrent
  requests while a batch of thumbnails is being generated. Images use Pillow; videos use the
  bundled `imageio-ffmpeg` binary to grab a frame.
- For serving under real concurrent load, run with a proper WSGI/ASGI server and multiple
  worker processes/threads, e.g.:
  `gunicorn scloud.wsgi:application --workers 4 --threads 4 --bind 0.0.0.0:8000` (from `src/`).
- File/thumbnail streaming supports HTTP Range requests (`storage/range_response.py`) so video
  playback can seek/scrub instead of downloading the whole file.
- Multi-select "Download" uses the Web Share API (`navigator.share`) where available so images/
  videos can be handed straight to the iOS/Android share sheet (from which "Save to Photos" is a
  native OS option) — this is the only way a website can offer camera-roll saving. It falls back
  to plain sequential downloads on desktop or when the share sheet is unavailable/cancelled.
  Non-media files (PDFs, etc.) always download normally since Photos can't hold them anyway.
- Public share links (`storage:shared`) can optionally grant anonymous visitors upload, folder
  creation, and/or tag management rights, scoped to exactly the shared folder/group root
  (`ShareLink.can_upload` / `can_create_folders` / `can_manage_tags`).
