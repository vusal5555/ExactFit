import os
from supabase import create_client, Client
from dotenv import load_dotenv


load_dotenv()

SUPABASE_URL: str = os.getenv("SUPABASE_URL")
SUPABASE_PUBLISHABLE_KEY: str = os.getenv("SUPABASE_PUBLISHABLE_KEY")

if not SUPABASE_URL or not SUPABASE_PUBLISHABLE_KEY:
    raise ValueError(
        "Supabase URL or Publishable Key is not set in environment variables."
    )


supabase: Client = create_client(SUPABASE_URL, SUPABASE_PUBLISHABLE_KEY)


def get_db() -> Client:
    return supabase
