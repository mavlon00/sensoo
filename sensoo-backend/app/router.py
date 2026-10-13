import json
from datetime import datetime, timezone
from typing import Any, List
from uuid import uuid4

from fastapi import APIRouter, Depends, HTTPException, status
from sqlmodel import Session, select

from app.actions import VerificationAction
from app.ai_router import ai_router
from app.db import get_session
from app.models import (
    FeedItemResponse,
    ConversationCreate,
    ConversationResponse,
    ProductCode,
    ProductCodeCreate,
    ReportCreate,
    ReportResponse,
    ScanRequest,
    ScanResponse,
    ScanTelemetryRecord,
)

router = APIRouter(prefix="/api/v1", tags=["sensoo"])
router.include_router(ai_router)
verification_action = VerificationAction()

# Simple in-memory store for the sprint (replace with DB later).
REPORTS = []
CONVERSATIONS = []



@router.post("/scan", response_model=ScanResponse)
def scan_product(
    scan_data: ScanRequest,
    session: Session = Depends(get_session),
) -> Any:
    return verification_action.verify_and_record_scan(session, scan_data)


@router.post("/register", response_model=ProductCode)
def register_product(
    product_in: ProductCodeCreate,
    session: Session = Depends(get_session),
) -> Any:
    existing = session.exec(
        select(ProductCode).where(ProductCode.code == product_in.code)
    ).first()
    if existing:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail=f"Product code '{product_in.code}' already exists.",
        )
    product = verification_action.create(session, data=product_in)
    return product


@router.get("/feed", response_model=List[FeedItemResponse])
def get_feed(
    limit: int = 50,
    session: Session = Depends(get_session),
) -> Any:
    stmt = (
        select(ScanTelemetryRecord)
        .order_by(ScanTelemetryRecord.timestamp.desc(), ScanTelemetryRecord.id.desc())
        .limit(limit)
    )
    records = session.exec(stmt).all()

    feed_items = []
    for r in records:
        try:
            alarms_list = json.loads(r.alarms) if r.alarms else []
        except Exception:
            alarms_list = [r.alarms] if r.alarms else []

        feed_items.append(
            FeedItemResponse(
                id=r.id,
                code=r.code,
                role=r.role,
                lat=r.lat,
                lng=r.lng,
                timestamp=r.timestamp,
                alarms=alarms_list,
                device_id=r.device_id,
                created_at=r.created_at,
            )
        )
    return feed_items


@router.post("/reports", response_model=ReportResponse)
def create_report(body: ReportCreate) -> ReportResponse:
    """Submit a NAFDAC-style counterfeit report."""
    case_id = f"CASE-SENSOO-{uuid4().hex[:8].upper()}"
    report = {
        "case_id": case_id,
        "code": body.code,
        "seller_name": body.seller_name,
        "location": body.location,
        "description": body.description,
        "lat": body.lat,
        "lng": body.lng,
        "device_id": body.device_id,
        "image_url": body.image_url,
        "status": "Under Review",
        "created_at": datetime.now(timezone.utc).isoformat(),
    }
    REPORTS.append(report)
    return ReportResponse(
        success=True,
        case_id=case_id,
        message="Report submitted successfully. NAFDAC Sentinel will review it.",
    )


@router.post("/conversations", response_model=ConversationResponse)
def create_conversation(body: ConversationCreate) -> ConversationResponse:
    """Save an AI chat history message."""
    session_id = body.session_id or f"sess-{uuid4().hex[:10]}"
    item = {
        "id": len(CONVERSATIONS) + 1,
        "user_id": body.user_id,
        "role": body.role,
        "message": body.message,
        "session_id": session_id,
        "created_at": datetime.now(timezone.utc).isoformat(),
    }
    CONVERSATIONS.append(item)
    return ConversationResponse(
        success=True,
        id=item["id"],
        session_id=session_id,
        message="Conversation message saved",
    )


@router.get("/health")
def health_check() -> Any:
    return {"status": "healthy", "service": "sensoo-backend"}
