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

    # no content range => file is smaller than chunk size, treat as normal upload
    if not content_range:
        return ChunkedUploadResult()

    # Prevent path traversal / absolute-path writes and unsafe cleanup()
    if not re.fullmatch(r"[A-Za-z0-9._-]{1,64}", chunk_id):
        return ChunkedUploadResult(
            response=JsonResponse(
                {
                    "chunked_upload": True,
                    "complete": False,
                    "success": False,
                    "error_message": "Invalid chunk upload id.",
                },
                status=400,
            )
        )
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

    if start < 0 or end < start or total <= 0 or end >= total:
        return ChunkedUploadResult(
            response=JsonResponse(
                {
                    "chunked_upload": True,
                    "complete": False,
                    "success": False,
                    "error_message": "Invalid Content-Range values.",
                },
                status=400,
            )
        )

    # Enforce the same upper bound as the normal upload field to avoid disk DoS
    max_upload_size = getattr(
        settings, "WAGTAILVIDEOS_MAX_UPLOAD_SIZE", 1024 * 1024 * 1024
    )
    if max_upload_size is not None and total > max_upload_size:
        return ChunkedUploadResult(
            response=JsonResponse(
                {
                    "chunked_upload": True,
                    "complete": False,
                    "success": False,
                    "error_message": "Uploaded file exceeds the maximum allowed size.",
                },
                status=413,
            )
        )

    # Validate that the uploaded bytes match the declared Content-Range
    expected_len = end - start + 1
    if getattr(upload, "size", None) is not None and upload.size != expected_len:
        return ChunkedUploadResult(
            response=JsonResponse(
                {
                    "chunked_upload": True,
                    "complete": False,
                    "success": False,
                    "error_message": "Uploaded chunk size does not match Content-Range.",
                },
                status=400,
            )
        )

    chunk_dir = os.path.join(_get_chunk_root_dir(), chunk_id)
    os.makedirs(chunk_dir, exist_ok=True)
    assembled_path = os.path.join(chunk_dir, "assembled.upload")

    current_size = (
        os.path.getsize(assembled_path) if os.path.exists(assembled_path) else 0
    )
    if start == 0 and current_size:
        # Client restarted upload; truncate any existing partial file.
        open(assembled_path, "wb").close()
        current_size = 0

    if start != current_size:
        return ChunkedUploadResult(
            response=JsonResponse(
                {
                    "chunked_upload": True,
                    "complete": False,
                    "success": False,
                    "error_message": "Unexpected chunk offset.",
                },
                status=409,
            )
        )

    # Append-only write prevents sparse files and out-of-order chunk corruption.
    with open(assembled_path, "ab") as assembled_file:
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
                    "success": True,
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
