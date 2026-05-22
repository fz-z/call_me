import os

from fastapi import APIRouter, Depends

from models import SipBindRequest, SipStatusResponse
from auth import require_admin

router = APIRouter(prefix="/api/sip", tags=["sip"])

_sip_state = {"bound_number": None, "trunk_id": None}


@router.post("/bind", response_model=SipStatusResponse)
def bind_sip(body: SipBindRequest, admin: dict = Depends(require_admin)):
    _sip_state["bound_number"] = body.phone_number
    _sip_state["trunk_id"] = "trunk_mvp_placeholder"
    return SipStatusResponse(
        bound_number=body.phone_number,
        trunk_id=_sip_state["trunk_id"],
        status="bound",
    )


@router.get("/status", response_model=SipStatusResponse)
def get_sip_status(admin: dict = Depends(require_admin)):
    return SipStatusResponse(
        bound_number=_sip_state["bound_number"],
        trunk_id=_sip_state["trunk_id"],
        status="bound" if _sip_state["bound_number"] else "unbound",
    )
