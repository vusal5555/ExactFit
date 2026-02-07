from fastapi import APIRouter, HTTPException
from pydantic import BaseModel
from typing import List, Optional
from agents.enrichment_agent import enrich_leads
from utils.database import get_db

router = APIRouter()
db = get_db()


class EnrichRequest(BaseModel):
    lead_ids: Optional[List[str]] = None
    enrich_all: bool = False
    target_job_title: Optional[str] = None  # NEW: Customer's target role


@router.post("/enrich")
def run_enrichment(request: EnrichRequest):
    """
    Enrich leads with contact emails.

    Args:
        lead_ids: Specific leads to enrich
        enrich_all: Or enrich all discovered leads
        target_job_title: Role to find (e.g., "VP Sales", "HR Manager", "Head of Support")
    """

    # Get leads from database
    if request.enrich_all:
        result = db.table("leads").select("*").eq("status", "discovered").execute()
    elif request.lead_ids:
        result = db.table("leads").select("*").in_("id", request.lead_ids).execute()
    else:
        raise HTTPException(
            status_code=400, detail="Provide lead_ids or set enrich_all=True"
        )

    leads = result.data

    if not leads:
        return {"message": "No leads to enrich", "enriched": 0}

    # Run enrichment with customer's target job title
    enrichment_result = enrich_leads(leads, target_job_title=request.target_job_title)

    # Update database with enriched data
    updated_count = 0
    for lead in enrichment_result["enriched_leads"]:
        lead_id = lead.get("id")

        if not lead_id:
            continue

        update_data = {
            "status": "enriched",
            "contact_email": lead.get("contact_email", ""),
            "contact_name": lead.get("contact_name", ""),
            "contact_title": lead.get("contact_title", ""),
            "confidence": lead.get("confidence", 0),
            "linkedin_url": lead.get("linkedin_url", ""),
        }

        sources = lead.get("sources", [])
        if isinstance(sources, list):
            update_data["sources"] = sources

        try:
            db.table("leads").update(update_data).eq("id", lead_id).execute()
            updated_count += 1
        except Exception as e:
            print(f"Failed to update lead {lead_id}: {e}")

    # Mark failed leads
    for lead in enrichment_result["failed_leads"]:
        lead_id = lead.get("id")

        if not lead_id:
            continue

        try:
            current_raw = lead.get("raw_data", {}) or {}
            current_raw["enrichment_error"] = lead.get("error", "Unknown")

            db.table("leads").update(
                {"status": "enrichment_failed", "raw_data": current_raw}
            ).eq("id", lead_id).execute()
        except Exception as e:
            print(f"Failed to update failed lead {lead_id}: {e}")

    return {
        "message": "Enrichment complete",
        "stats": enrichment_result["stats"],
        "enriched_count": updated_count,
        "failed_count": len(enrichment_result["failed_leads"]),
        "target_job_title": request.target_job_title or "Any",
    }


@router.get("/enrich/status")
def get_enrichment_status():
    """Get counts of leads by status."""

    result = db.table("leads").select("status").execute()

    counts = {"discovered": 0, "enriched": 0, "enrichment_failed": 0}

    for lead in result.data:
        status = lead.get("status", "unknown")
        if status in counts:
            counts[status] += 1

    return counts
