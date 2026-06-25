import logging
import uuid

from fastapi import APIRouter, Depends, File, HTTPException, Request, UploadFile, status
from sqlalchemy import func, select
from sqlalchemy.orm import Session

from app.database import get_db
from app.dependencies import get_current_user
from app.limiter import limiter
from app.models.property import Property
from app.models.user import User
from app.models.verification_document import VerificationDocument
from app.schemas.verification import DocumentUploadResponse, VerificationMe
from app.services.r2_storage import StorageError, upload_verification_document

logger = logging.getLogger(__name__)
router = APIRouter(prefix="/verification", tags=["verification"])

# Cap stored documents per target so a single seller can't flood storage.
MAX_DOCS_PER_TARGET = 8


def _store_document(
    db: Session,
    *,
    kind: str,
    user: User,
    file: UploadFile,
    property_id=None,
) -> VerificationDocument:
    """Read, validate, upload to private R2, and persist a VerificationDocument."""
    raw_bytes = file.file.read()
    if not raw_bytes:
        raise HTTPException(status_code=422, detail="Empty file")

    doc_id = uuid.uuid4()
    try:
        result = upload_verification_document(
            owner_id=str(user.id),
            doc_id=str(doc_id),
            raw_bytes=raw_bytes,
            content_type=file.content_type,
            original_filename=file.filename,
            property_id=str(property_id) if property_id else None,
        )
    except StorageError as e:
        raise HTTPException(status_code=422, detail=str(e))

    doc = VerificationDocument(
        id=doc_id,
        kind=kind,
        user_id=user.id,
        property_id=property_id,
        storage_key=result["storage_key"],
        original_filename=result["original_filename"],
        size_bytes=result["size_bytes"],
        content_type=result["content_type"],
    )
    db.add(doc)
    return doc


def _doc_count(db: Session, *, kind: str, user_id, property_id=None) -> int:
    stmt = select(func.count(VerificationDocument.id)).where(
        VerificationDocument.kind == kind
    )
    if property_id is not None:
        stmt = stmt.where(VerificationDocument.property_id == property_id)
    else:
        stmt = stmt.where(VerificationDocument.user_id == user_id)
    return db.execute(stmt).scalar() or 0


@router.post("/company/documents", response_model=DocumentUploadResponse)
@limiter.limit("10/hour")
def upload_company_document(
    request: Request,
    file: UploadFile = File(...),
    db: Session = Depends(get_db),
    current_user: User = Depends(get_current_user),
):
    """A company uploads a business-registration document. Sets the account to
    'pending' (unless already verified) — an admin then reviews and approves."""
    if current_user.account_type != "company":
        raise HTTPException(
            status_code=400,
            detail="Only company accounts can submit company verification documents",
        )

    if _doc_count(db, kind="company", user_id=current_user.id) >= MAX_DOCS_PER_TARGET:
        raise HTTPException(status_code=400, detail="Too many documents on file")

    doc = _store_document(db, kind="company", user=current_user, file=file)

    # Don't downgrade an already-verified company on a re-upload.
    if current_user.verification_status != "verified":
        current_user.verification_status = "pending"

    db.commit()
    logger.info("Company verification doc %s uploaded by %s", doc.id, current_user.id)
    return DocumentUploadResponse(
        document_id=doc.id, kind="company", status=current_user.verification_status
    )


@router.post("/listings/{property_id}/documents", response_model=DocumentUploadResponse)
@limiter.limit("10/hour")
def upload_listing_document(
    property_id: uuid.UUID,
    request: Request,
    file: UploadFile = File(...),
    db: Session = Depends(get_db),
    current_user: User = Depends(get_current_user),
):
    """An individual seller uploads an ownership document (deed) for one listing.
    Sets that listing to 'pending' for admin review. Company-owned listings
    derive trust from the company's own verification instead."""
    prop = db.get(Property, property_id)
    if not prop:
        raise HTTPException(status_code=404, detail="Listing not found")
    if prop.owner_id != current_user.id:
        raise HTTPException(status_code=403, detail="You can only verify your own listings")
    if current_user.account_type == "company":
        raise HTTPException(
            status_code=400,
            detail="Company listings are covered by company verification, not per-listing documents",
        )

    if (
        _doc_count(db, kind="listing_ownership", user_id=current_user.id, property_id=property_id)
        >= MAX_DOCS_PER_TARGET
    ):
        raise HTTPException(status_code=400, detail="Too many documents on file")

    doc = _store_document(
        db, kind="listing_ownership", user=current_user, file=file, property_id=property_id
    )

    if prop.verification_status != "verified":
        prop.verification_status = "pending"
        prop.verification_rejection_reason = None

    db.commit()
    logger.info("Listing verification doc %s uploaded for %s", doc.id, property_id)
    return DocumentUploadResponse(
        document_id=doc.id, kind="listing_ownership", status=prop.verification_status
    )


@router.get("/me", response_model=VerificationMe)
def my_verification(
    db: Session = Depends(get_db),
    current_user: User = Depends(get_current_user),
):
    """The current user's company-verification state (no document URLs)."""
    has_doc = _doc_count(db, kind="company", user_id=current_user.id) > 0
    return VerificationMe(
        account_type=current_user.account_type,
        verification_status=current_user.verification_status,
        has_company_document=has_doc,
    )
