"""
services/storage.py — Supabase Storage abstraction layer.

All file operations go through this module.
In production (Render + Supabase): files live in Supabase Storage bucket.
In local dev (no SUPABASE_URL set): falls back to local /uploads folder.

Public API:
    upload_file(file_obj, filename, content_type) -> str  (public URL or rel path)
    delete_file(file_url)                         -> bool
    get_download_url(file_url)                    -> str  (signed URL, 5-min expiry)
    is_supabase_enabled()                         -> bool
"""
import os, uuid, mimetypes
from config import (
    SUPABASE_URL, SUPABASE_KEY, STORAGE_BUCKET,
    UPLOAD_FOLDER, UPLOAD_SUBFOLDERS, ALLOWED_EXTENSIONS,
)


# ─── Lazy Supabase client ─────────────────────────────────────────────────────
_supabase_client = None

def _get_client():
    global _supabase_client
    if _supabase_client is None:
        from supabase import create_client
        _supabase_client = create_client(SUPABASE_URL, SUPABASE_KEY)
    return _supabase_client


def is_supabase_enabled() -> bool:
    """True when SUPABASE_URL and SUPABASE_KEY are both set."""
    return bool(SUPABASE_URL and SUPABASE_KEY)


# ─── Helpers ──────────────────────────────────────────────────────────────────
def _ext(filename: str) -> str:
    return filename.rsplit(".", 1)[-1].lower() if "." in filename else ""


def _storage_path(filename: str) -> str:
    """Build the Supabase Storage object path: pdfs/abc123.pdf"""
    ext       = _ext(filename)
    subfolder = UPLOAD_SUBFOLDERS.get(ext, "docs")
    unique    = f"{uuid.uuid4().hex}.{ext}"
    return f"{subfolder}/{unique}"


def _content_type(filename: str) -> str:
    ct, _ = mimetypes.guess_type(filename)
    return ct or "application/octet-stream"


# ─── Public API ───────────────────────────────────────────────────────────────
def upload_file(file_obj, original_filename: str) -> tuple[str, str]:
    """
    Upload a file to Supabase Storage (or local /uploads fallback).

    Returns:
        (file_url, file_type)
        file_url  — Supabase public URL  OR  local relative path (subfolder/name.ext)
        file_type — extension string, e.g. "pdf"
    """
    ext = _ext(original_filename)
    if ext not in ALLOWED_EXTENSIONS:
        raise ValueError(f"File type '.{ext}' is not allowed.")

    if is_supabase_enabled():
        return _upload_supabase(file_obj, original_filename, ext)
    else:
        return _upload_local(file_obj, original_filename, ext)


def _upload_supabase(file_obj, original_filename: str, ext: str) -> tuple[str, str]:
    client       = _get_client()
    storage_path = _storage_path(original_filename)   # e.g.  pdfs/abc123.pdf
    file_bytes   = file_obj.read()
    content_type = _content_type(original_filename)

    # Upload to Supabase Storage bucket
    client.storage.from_(STORAGE_BUCKET).upload(
        path        = storage_path,
        file        = file_bytes,
        file_options= {"content-type": content_type, "upsert": "false"},
    )

    # Build the public URL
    # Format: https://<project>.supabase.co/storage/v1/object/public/<bucket>/<path>
    public_url = f"{SUPABASE_URL}/storage/v1/object/public/{STORAGE_BUCKET}/{storage_path}"
    return public_url, ext


def _upload_local(file_obj, original_filename: str, ext: str) -> tuple[str, str]:
    subfolder = UPLOAD_SUBFOLDERS.get(ext, "docs")
    dest_dir  = os.path.join(UPLOAD_FOLDER, subfolder)
    os.makedirs(dest_dir, exist_ok=True)
    unique_name = f"{uuid.uuid4().hex}.{ext}"
    dest_path   = os.path.join(dest_dir, unique_name)
    file_obj.save(dest_path)
    rel_path = f"{subfolder}/{unique_name}"
    return rel_path, ext


def delete_file(file_url: str) -> bool:
    """
    Delete a file.
    file_url is either a full Supabase URL or a local relative path.
    """
    if not file_url:
        return False

    if is_supabase_enabled() and file_url.startswith("http"):
        return _delete_supabase(file_url)
    else:
        return _delete_local(file_url)


def _delete_supabase(public_url: str) -> bool:
    """Extract storage path from public URL and delete from bucket."""
    try:
        client = _get_client()
        # Extract path after /public/<bucket>/
        marker = f"/public/{STORAGE_BUCKET}/"
        idx    = public_url.find(marker)
        if idx == -1:
            return False
        storage_path = public_url[idx + len(marker):]
        client.storage.from_(STORAGE_BUCKET).remove([storage_path])
        return True
    except Exception as e:
        print(f"⚠️  Supabase delete error: {e}")
        return False


def _delete_local(rel_path: str) -> bool:
    abs_path = os.path.join(UPLOAD_FOLDER, rel_path)
    if os.path.exists(abs_path):
        os.remove(abs_path)
        return True
    return False


def get_download_response(file_url: str, download_name: str):
    """
    Return either:
      - A Flask redirect to a signed Supabase URL  (Supabase mode)
      - A Flask send_file response                 (local mode)

    Caller must import and use this correctly:
        resp = get_download_response(product["file_url"], safe_name)
        return resp
    """
    if is_supabase_enabled() and file_url.startswith("http"):
        return _supabase_signed_redirect(file_url, download_name)
    else:
        return _local_send_file(file_url, download_name)


def _supabase_signed_redirect(public_url: str, download_name: str):
    """Generate a 5-minute signed URL and redirect the user to it."""
    from flask import redirect
    try:
        client = _get_client()
        marker = f"/public/{STORAGE_BUCKET}/"
        idx    = public_url.find(marker)
        if idx == -1:
            # URL format unexpected — try sending the public URL directly
            return redirect(public_url)
        storage_path = public_url[idx + len(marker):]
        signed = client.storage.from_(STORAGE_BUCKET).create_signed_url(
            path       = storage_path,
            expires_in = 300,          # 5 minutes
            options    = {"download": download_name},
        )
        return redirect(signed["signedURL"])
    except Exception as e:
        print(f"⚠️  Signed URL error: {e}")
        # Fall back to public URL
        return redirect(public_url)


def _local_send_file(rel_path: str, download_name: str):
    """Serve file from local disk."""
    from flask import send_file, abort
    abs_path = os.path.join(UPLOAD_FOLDER, rel_path)
    if not os.path.exists(abs_path):
        abort(404)
    return send_file(abs_path, as_attachment=True, download_name=download_name)
