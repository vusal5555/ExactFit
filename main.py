from fastapi import FastAPI
from fastapi.middleware.cors import CORSMiddleware
from api.leads import router as leads_router


app = FastAPI(title="ExactFit API", version="0.1.0")

# Allow frontend to connect later
app.add_middleware(
    CORSMiddleware,
    allow_origins=["*"],  # Lock this down in production
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)


app.include_router(leads_router, prefix="/api")


@app.get("/")
def health_check():
    return {"status": "healthy", "service": "exactfit-api"}


@app.get("/api/leads")
def get_leads():
    # Placeholder - will connect to Supabase next
    return {"leads": [], "count": 0}
