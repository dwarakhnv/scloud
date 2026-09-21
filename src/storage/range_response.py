"""Minimal HTTP Range support so video/audio thumbnails and originals can be
seeked/scrubbed in the browser instead of always downloading from byte 0."""
import mimetypes
import os
import re

from django.http import FileResponse, HttpResponse, StreamingHttpResponse

RANGE_RE = re.compile(r"bytes=(\d+)-(\d*)")

# Read/write in modest chunks rather than the whole requested range at once -
# this is what lets a worker thread serve a multi-GB video range (or several
# of them concurrently) without ballooning memory or blocking on one giant
# read before it can send a single byte back to the client.
CHUNK_SIZE = 1024 * 1024  # 1MB


def _iter_range(path, start, length, chunk_size=CHUNK_SIZE):
    with open(path, "rb") as f:
        f.seek(start)
        remaining = length
        while remaining > 0:
            chunk = f.read(min(chunk_size, remaining))
            if not chunk:
                break
            remaining -= len(chunk)
            yield chunk


def serve_file_with_range(request, path, filename=None, content_type=None):
    if not os.path.exists(path):
        return HttpResponse(status=404)

    file_size = os.path.getsize(path)
    content_type = content_type or mimetypes.guess_type(str(path))[0] or "application/octet-stream"
    range_header = request.META.get("HTTP_RANGE", "")
    match = RANGE_RE.match(range_header)

    if not match:
        response = FileResponse(open(path, "rb"), content_type=content_type)
        response["Content-Length"] = file_size
        response["Accept-Ranges"] = "bytes"
        if filename:
            response["Content-Disposition"] = f'inline; filename="{filename}"'
        return response

    start = int(match.group(1))
    end = int(match.group(2)) if match.group(2) else file_size - 1
    end = min(end, file_size - 1)
    length = end - start + 1

    response = StreamingHttpResponse(
        _iter_range(path, start, length), status=206, content_type=content_type
    )
    response["Content-Length"] = length
    response["Content-Range"] = f"bytes {start}-{end}/{file_size}"
    response["Accept-Ranges"] = "bytes"
    if filename:
        response["Content-Disposition"] = f'inline; filename="{filename}"'
    return response
