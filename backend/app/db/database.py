import os
from supabase import create_client, Client
from dotenv import load_dotenv

load_dotenv()

db_url = os.environ.get("SUPABASE_URL")
db_key = os.environ.get("SUPABASE_SECRET_KEY")

# Handle all CRUD operations
if not db_url or not db_key:
    raise ValueError(
        "Missing Supabase environment variables"
    )
supabase: Client = create_client(db_url, db_key)