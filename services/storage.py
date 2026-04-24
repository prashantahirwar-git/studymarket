from __future__ import annotations
"""
services/storage.py — Supabase Storage abstraction layer.

SECURITY MODEL:
  - Documents (pdfs, docs, ppts) → stored in a PRIVATE bucket.
    Direct public URLs are NEVER stored or served. Access is always
    via a short-lived signed URL generated at download time.
  - Preview images (previews/) → stored in a PUBLIC bucket (intentional —
    buyers need to see previews before purchasing, with no auth required).

In local dev (no SUPABASE_URL set): falls back to /uploads on disk.

Public API:
    upload_file(file_obj, filename)          -> (storage_path, file_type)
    upload_preview_image(file_obj, filename) -> preview_url
    delete_file(path_or_url)                 -> bool
    get_download_response(storage_path, name)-> Flask response (signed URL redirect)
    is_supabase_enabled()                    -> bool
"""
import logging
import os
import uuid
import mimetypes
from config import (
    SUPABASE_URL, SUPABASE_KEY, STORAGE_BUCKET,
    UPLOAD_FOLDER, UPLOAD_SUBFOLDERS, ALLOWED_EXTENSIONS,
    ALLOWED_IMAGE_EXTENSIONS,
)

logger = logging.getLogger(__name__)

# Previews go into a separate public bucket (or public prefix)
# Previews live in the SAME bucket as docs, under the previews/ prefix.
# The previews/ subfolder is set to public read in Supabase policies.
# This avoids needing a second bucket.
_PREVIEW_PREFIX = "previews"

# ── Lazy Supabase client ──────────────────────────────────────────────────────
_supabase_client = None

def _get_client():
    global _supabase_client
    if _supabase_client is None:
        from supabase import create_client
        _supabase_client = create_client(SUPABASE_URL, SUPABASE_KEY)
    return _supabase_client


def is_supabase_enabled() -> bool:
    return bool(SUPABASE_URL and SUPABASE_KEY)


# ── Helpers ───────────────────────────────────────────────────────────────────

def _ext(filename: str) -> str:
    return filename.rsplit(".", 1)[-1].lower() if "." in filename else ""


def _storage_path(filename: str) -> str:
    ext       = _ext(filename)
    subfolder = UPLOAD_SUBFOLDERS.get(ext, "docs")
    return f"{subfolder}/{uuid.uuid4().hex}.{ext}"


def _content_type(filename: str) -> str:
    ct, _ = mimetypes.guess_type(filename)
    return ct or "application/octet-stream"


# ── Public API ────────────────────────────────────────────────────────────────

def upload_file(file_obj, original_filename: str) -> tuple[str, str]:
    """
    Upload a DOCUMENT to the private Supabase bucket (or local fallback).

    Returns:
        (storage_path, file_type)
        storage_path — opaque path stored in DB, NEVER a public URL.
                       Used later to generate signed download URLs.
        file_type    — extension string, e.g. "pdf"
    """
    ext = _ext(original_filename)
    if ext not in ALLOWED_EXTENSIONS:
        raise ValueError(f"File type '.{ext}' is not allowed.")

    if is_supabase_enabled():
        return _upload_supabase_private(file_obj, original_filename, ext)
    else:
        return _upload_local(file_obj, original_filename, ext)


def upload_preview_image(file_obj, original_filename: str) -> str:
    """
    Upload a preview image (jpg/jpeg/png/webp) to Supabase Storage or local.
    Accepts either a Werkzeug FileStorage object or a plain BytesIO.

    Returns:
        preview_url — public URL or local relative path
    """
    ext = _ext(original_filename)
    if ext not in ALLOWED_IMAGE_EXTENSIONS:
        raise ValueError(f"Preview must be jpg/jpeg/png/webp. Got '.{ext}'.")

    if is_supabase_enabled():
        url, _ = _upload_supabase_public_preview(file_obj, original_filename, ext)
    else:
        url, _ = _upload_local(file_obj, original_filename, ext)
    return url


def _upload_supabase_private(file_obj, original_filename: str, ext: str) -> tuple[str, str]:
    """Upload to the PRIVATE bucket. Returns (storage_path, ext)."""
    client       = _get_client()
    storage_path = _storage_path(original_filename)
    file_bytes   = file_obj.read()
    content_type = _content_type(original_filename)

    client.storage.from_(STORAGE_BUCKET).upload(
        path         = storage_path,
        file         = file_bytes,
        file_options = {"content-type": content_type, "upsert": "false"},
    )
    logger.info("Uploaded private file: %s (%d bytes)", storage_path, len(file_bytes))
    # Return the opaque storage path — NOT a public URL
    return storage_path, ext


def _upload_supabase_public_preview(file_obj, original_filename: str, ext: str) -> tuple:
    """
    Upload preview to the SAME bucket as docs, under previews/ subfolder.
    Returns (public_url, ext).  Public URL works without signed URL because
    the previews/ path has a public SELECT policy in Supabase.
    """
    client       = _get_client()
    storage_path = f"{_PREVIEW_PREFIX}/{uuid.uuid4().hex}.{ext}"
    file_bytes   = file_obj.read()
    content_type = _content_type(original_filename)

    client.storage.from_(STORAGE_BUCKET).upload(
        path         = storage_path,
        file         = file_bytes,
        file_options = {"content-type": content_type, "upsert": "false"},
    )
    # Store the full public URL directly so the img tag can use it without
    # going through a Flask proxy endpoint
    public_url = (
        f"{SUPABASE_URL}/storage/v1/object/public/{STORAGE_BUCKET}/{storage_path}"
    )
    logger.info("Uploaded public preview: %s", storage_path)
    return public_url, ext


def _upload_local(file_obj, original_filename: str, ext: str) -> tuple:
    subfolder   = UPLOAD_SUBFOLDERS.get(ext, "docs")
    dest_dir    = os.path.join(UPLOAD_FOLDER, subfolder)
    os.makedirs(dest_dir, exist_ok=True)
    unique_name = f"{uuid.uuid4().hex}.{ext}"
    dest_path   = os.path.join(dest_dir, unique_name)

    # Support both Werkzeug FileStorage (.save()) and BytesIO (.read())
    import io
    if hasattr(file_obj, "save"):
        file_obj.save(dest_path)
    else:
        data = file_obj.read() if hasattr(file_obj, "read") else file_obj
        with open(dest_path, "wb") as f:
            f.write(data)

    rel_path = f"{subfolder}/{unique_name}"
    return rel_path, ext


# ── Delete ────────────────────────────────────────────────────────────────────

def delete_file(path_or_url: str) -> bool:
    """
    Delete a file from storage.
    Accepts either a storage_path (private doc) or a full public URL (preview).
    """
    if not path_or_url:
        return False
    if is_supabase_enabled():
        return _delete_supabase(path_or_url)
    return _delete_local(path_or_url)


def _delete_supabase(path_or_url: str) -> bool:
    try:
        client = _get_client()
        if path_or_url.startswith("http"):
            # Preview image — public URL → extract bucket + path
            # Both preview and doc public URLs use the main STORAGE_BUCKET
            marker = f"/public/{STORAGE_BUCKET}/"
            idx    = path_or_url.find(marker)
            if idx == -1:
                return False
            storage_path = path_or_url[idx + len(marker):]
            client.storage.from_(STORAGE_BUCKET).remove([storage_path])
        else:
            # Private document — path stored directly
            client.storage.from_(STORAGE_BUCKET).remove([path_or_url])
        return True
    except Exception as e:
        logger.warning("Supabase delete error for %s: %s", path_or_url, e)
        return False


def _delete_local(rel_path: str) -> bool:
    # Strip any leading http (shouldn't happen in local mode, but be safe)
    if rel_path.startswith("http"):
        return False
    abs_path = os.path.join(UPLOAD_FOLDER, rel_path)
    if os.path.exists(abs_path):
        os.remove(abs_path)
        return True
    return False


# ── Download ──────────────────────────────────────────────────────────────────

def get_download_response(storage_path: str, download_name: str):
    """
    Generate a response that delivers the private document to an authorised user.
    Supabase: generates a short-lived signed URL (5 min) and redirects.
    Local dev: serves directly from disk.
    """
    if is_supabase_enabled():
        return _supabase_signed_redirect(storage_path, download_name)
    return _local_send_file(storage_path, download_name)


def _supabase_signed_redirect(storage_path: str, download_name: str):
    from flask import redirect
    try:
        client = _get_client()
        # storage_path is now the opaque path (e.g. "pdfs/abc123.pdf")
        # NOT a public URL — this is the fix for the public access vulnerability
        signed = client.storage.from_(STORAGE_BUCKET).create_signed_url(
            path       = storage_path,
            expires_in = 300,   # 5 minutes
            options    = {"download": download_name},
        )
        return redirect(signed["signedURL"])
    except Exception as e:
        logger.error("Signed URL generation failed for %s: %s", storage_path, e)
        from flask import abort
        abort(500)


def _local_send_file(rel_path: str, download_name: str):
    from flask import send_file, abort
    abs_path = os.path.join(UPLOAD_FOLDER, rel_path)
    if not os.path.exists(abs_path):
        abort(404)
    return send_file(abs_path, as_attachment=True, download_name=download_name)
