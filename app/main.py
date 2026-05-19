from fastapi import Depends, FastAPI
from fastapi.middleware.cors import CORSMiddleware
from sqlalchemy import text
from sqlalchemy.orm import Session

from app.database import get_db
from app.routers import auth as auth_router, chat as chat_router, properties as properties_router

app = FastAPI(
    title="DarSyria API",
    description="Backend for the DarSyria real estate platform",
    version="0.1.0"
)

app.add_middleware(
    CORSMiddleware,
    allow_origins=["http://localhost:3000"],
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)

app.include_router(auth_router.router)
app.include_router(chat_router.router)
app.include_router(properties_router.router)


@app.get("/health")
def health():
    return {"status": "ok", "service": "darsyria-api"}


@app.get("/health/db")
def health_db(db: Session = Depends(get_db)):
    """Verify the database is reachable and the schema is initialized."""
    result = db.execute(text("SELECT 1")).scalar()
    pgvector = db.execute(
        text("SELECT extname FROM pg_extension WHERE extname = 'vector'")
    ).scalar()
    users_table = db.execute(
        text("SELECT to_regclass('public.users')")
    ).scalar()
    return {
        "database": "connected" if result == 1 else "error",
        "pgvector_installed": pgvector == "vector",
        "users_table_exists": users_table == "users",
    }


@app.get("/")
def root():
    return {"message": "DarSyria API. See /docs for documentation."}
