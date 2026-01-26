from fastapi import APIRouter, HTTPException
from pydantic import BaseModel
from typing import Optional, List
from utils.database import get_db


router = APIRouter()

db = get_db()


class LeadCreate(BaseModel):
    company_name: str
    domain: Optional[str] = None
    contact_email: Optional[str] = None
    contact_name: Optional[str] = None
    job_title: Optional[str] = None
    sources: List[str] = []


class LeadResponse(BaseModel):
    id: str
    company_name: str
    domain: Optional[str]
    contact_email: Optional[str]
    score: int
    intent_tier: int
    status: str


class ResponseModel(BaseModel):
    leads: List[LeadResponse]
    count: int


@router.get("/leads", response_model=ResponseModel)
def get_leads(tier: Optional[int] = None, status: Optional[str] = None):

    query = db.table("leads").select("*").order("score", desc=True)

    if tier:
        query = query.eq("intent_tier", tier)
    if status:
        query = query.eq("status", status)

    result = query.execute()
    return {"leads": result.data, "count": len(result.data)}


@router.post("/leads")
def create_lead(lead: LeadCreate):
    result = (
        db.table("leads")
        .insert(
            {
                "company_name": lead.company_name,
                "domain": lead.domain,
                "contact_email": lead.contact_email,
                "contact_name": lead.contact_name,
                "job_title": lead.job_title,
                "sources": lead.sources,
                "status": "discovered",
            }
        )
        .execute()
    )

    return {"lead": result.data[0], "message": "Lead created"}


@router.get("/leads/{lead_id}")
def get_lead(lead_id: str):
    result = db.table("leads").select("*").eq("id", lead_id).execute()

    if not result.data:
        raise HTTPException(status_code=404, detail="Lead not found")

    return {"lead": result.data[0]}
