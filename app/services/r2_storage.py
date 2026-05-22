"""
Cloudflare R2 storage service.

R2 is S3-compatible, so we use boto3. The only differences from S3 are:
- Custom endpoint URL (R2 instead of AWS)
- "auto" region (R2 doesn't use AWS regions)
- Public URLs via pub-*.r2.dev or custom domain (set via R2_PUBLIC_URL)
"""
import io
import logging
import uuid
from typing import Optional

import boto3
from botocore.client import Config
from PIL import Image, ImageOps
from PIL.Image import Resampling

from app.config import settings

logger = logging.getLogger(__name__)


MAX_DISPLAY_WIDTH = 1600
MAX_DISPLAY_HEIGHT = 1600
JPEG_QUALITY = 82
MAX_UPLOAD_SIZE_MB = 10


class StorageError(Exception):
    """Raised when an R2 operation fails."""


def _get_client():
    """Build a boto3 S3 client configured for R2."""
    return boto3.client(
        "s3",
        endpoint_url=settings.r2_endpoint_url,
        aws_access_key_id=settings.r2_access_key_id,
        aws_secret_access_key=settings.r2_secret_access_key,
        region_name="auto",
        config=Config(signature_version="s3v4"),
    )


def process_image(raw_bytes: bytes) -> tuple[bytes, str]:
    """
    Process an uploaded image:
    - Validate it's actually an image
    - Strip EXIF metadata (privacy: removes GPS, camera, timestamps)
    - Auto-rotate based on EXIF orientation
    - Resize if larger than MAX_DISPLAY_WIDTH x MAX_DISPLAY_HEIGHT
    - Convert to JPEG with quality compression

    Returns (processed_bytes, content_type).
    Raises StorageError if the input isn't a valid image.
    """
    try:
        img = Image.open(io.BytesIO(raw_bytes))
    except Exception as e:
        raise StorageError(f"Not a valid image file: {e}") from e

    if img.format not in ("JPEG", "PNG", "WEBP", "HEIC", "HEIF"):
        raise StorageError(f"Unsupported image format: {img.format}")

    # Auto-rotate based on EXIF orientation, then strip EXIF
    img = ImageOps.exif_transpose(img)

    if img.mode != "RGB":
        img = img.convert("RGB")

    img.thumbnail(
        (MAX_DISPLAY_WIDTH, MAX_DISPLAY_HEIGHT),
        Resampling.LANCZOS,
    )

    output = io.BytesIO()
    img.save(
        output,
        format="JPEG",
        quality=JPEG_QUALITY,
        optimize=True,
        progressive=True,
    )
    output.seek(0)
    return output.getvalue(), "image/jpeg"


def upload_property_image(
    property_id: str,
    raw_bytes: bytes,
    original_filename: Optional[str] = None,
) -> dict:
    """
    Upload an image for a property to R2.

    Returns a dict with: storage_key, public_url, size_bytes, content_type.
    Raises StorageError if processing or upload fails.
    """
    processed_bytes, content_type = process_image(raw_bytes)

    if len(processed_bytes) > MAX_UPLOAD_SIZE_MB * 1024 * 1024:
        raise StorageError(
            f"Processed image still exceeds {MAX_UPLOAD_SIZE_MB} MB — refusing to upload"
        )

    image_id = uuid.uuid4()
    storage_key = f"properties/{property_id}/{image_id}.jpg"

    client = _get_client()
    try:
        client.put_object(
            Bucket=settings.r2_bucket_name,
            Key=storage_key,
            Body=processed_bytes,
            ContentType=content_type,
            CacheControl="public, max-age=31536000, immutable",
        )
    except Exception as e:
        logger.exception("R2 upload failed for property %s", property_id)
        raise StorageError(f"Upload failed: {e}") from e

    public_url = f"{settings.r2_public_url.rstrip('/')}/{storage_key}"

    return {
        "storage_key": storage_key,
        "public_url": public_url,
        "size_bytes": len(processed_bytes),
        "content_type": content_type,
        "original_filename": original_filename,
    }


def delete_object(storage_key: str) -> None:
    """Delete one object from R2 by storage key. Idempotent."""
    client = _get_client()
    try:
        client.delete_object(
            Bucket=settings.r2_bucket_name,
            Key=storage_key,
        )
    except Exception as e:
        logger.exception("R2 delete failed for key %s", storage_key)
        raise StorageError(f"Delete failed: {e}") from e


def delete_property_images(property_id: str) -> int:
    """
    Delete all images for a property. Used when a property is deleted.
    Returns the count of deleted objects.
    """
    client = _get_client()
    prefix = f"properties/{property_id}/"
    try:
        paginator = client.get_paginator("list_objects_v2")
        keys_to_delete = []
        for page in paginator.paginate(
            Bucket=settings.r2_bucket_name,
            Prefix=prefix,
        ):
            for obj in page.get("Contents", []):
                keys_to_delete.append({"Key": obj["Key"]})

        if not keys_to_delete:
            return 0

        client.delete_objects(
            Bucket=settings.r2_bucket_name,
            Delete={"Objects": keys_to_delete},
        )
        return len(keys_to_delete)
    except Exception as e:
        logger.exception("R2 bulk delete failed for property %s", property_id)
        raise StorageError(f"Bulk delete failed: {e}") from e
