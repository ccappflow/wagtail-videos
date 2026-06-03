import os
import re
import shutil
import tempfile

from django.conf import settings
from django.core.files.uploadedfile import UploadedFile
from django.http import JsonResponse

CONTENT_RANGE_RE = re.compile(r"^bytes (?P<start>\d+)-(?P<end>\d+)/(?P<total>\d+)$")


class ChunkedUploadResult:
    def __init__(self, response=None, cleanup=None):
        self.response = response
        self.cleanup = cleanup


def get_upload_chunk_size():
    return getattr(settings, "WAGTAILVIDEOS_UPLOAD_CHUNK_SIZE", None)


def _get_chunk_root_dir():
    temp_dir = getattr(settings, "FILE_UPLOAD_TEMP_DIR", None) or tempfile.gettempdir()
    return os.path.join(temp_dir, "wagtailvideos-chunks")


def _get_chunk_identifier(request):
    return request.headers.get("X-Chunk-Upload-Id") or request.POST.get(
        "chunk_upload_id"
    )


def handle_chunked_upload(request, field_name):
    if get_upload_chunk_size() is None:
        return ChunkedUploadResult()

    content_range = request.headers.get("Content-Range")
    chunk_id = _get_chunk_identifier(request)

    if not content_range or not chunk_id:
        return ChunkedUploadResult()

    match = CONTENT_RANGE_RE.match(content_range)
    if not match:
        return ChunkedUploadResult(
            response=JsonResponse(
                {
                    "chunked_upload": True,
                    "complete": False,
                    "success": False,
                    "error_message": "Invalid Content-Range header.",
                },
                status=400,
            )
        )

    upload = request.FILES.get(field_name)
    if upload is None:
        return ChunkedUploadResult(
            response=JsonResponse(
                {
                    "chunked_upload": True,
                    "complete": False,
                    "success": False,
                    "error_message": "Missing uploaded chunk.",
                },
                status=400,
            )
        )

    start = int(match.group("start"))
    end = int(match.group("end"))
    total = int(match.group("total"))

    chunk_dir = os.path.join(_get_chunk_root_dir(), chunk_id)
    os.makedirs(chunk_dir, exist_ok=True)
    assembled_path = os.path.join(chunk_dir, "assembled.upload")

    mode = "r+b" if os.path.exists(assembled_path) else "wb"
    with open(assembled_path, mode) as assembled_file:
        assembled_file.seek(start)
        for chunk in upload.chunks():
            assembled_file.write(chunk)

    is_complete = end + 1 >= total
    if not is_complete:
        return ChunkedUploadResult(
            response=JsonResponse(
                {
                    "chunked_upload": True,
                    "complete": False,
                    "uploaded_bytes": end + 1,
                }
            )
        )

    assembled_file = open(assembled_path, "rb")
    request.FILES.setlist(
        field_name,
        [
            UploadedFile(
                file=assembled_file,
                name=upload.name,
                content_type=upload.content_type,
                size=total,
                charset=getattr(upload, "charset", None),
            )
        ],
    )

    def cleanup():
        assembled_file.close()
        shutil.rmtree(chunk_dir, ignore_errors=True)

    return ChunkedUploadResult(cleanup=cleanup)
