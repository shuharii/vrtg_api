from fastapi import FastAPI, HTTPException, Query
from pydantic import BaseModel, Field
from typing import Optional, List
from uuid import UUID
import os
import psycopg2
from psycopg2 import pool, sql
from datetime import datetime

app = FastAPI(title="Clans API", version="1.0.0")

# ---- ENV ----
DB_USER = os.getenv("DB_USER", "postgres")
DB_PASS = os.getenv("DB_PASS", "")
DB_NAME = os.getenv("DB_NAME", "vertigo_clan_dev")
DB_HOST = os.getenv("DB_HOST", "127.0.0.1")
DB_PORT = None if DB_HOST.startswith("/") else int(os.getenv("DB_PORT", "5432"))

DB_SCHEMA = os.getenv("DB_SCHEMA", "clan_schema")
DB_TABLE  = os.getenv("DB_TABLE", "clans")

MIN_CONNS = int(os.getenv("DB_MIN_CONNS", "1"))
MAX_CONNS = int(os.getenv("DB_MAX_CONNS", "5"))

# ---- POOL (lazy) ----
conn_pool: Optional[pool.SimpleConnectionPool] = None
def get_pool() -> pool.SimpleConnectionPool:
    global conn_pool
    if conn_pool is None:
        conn_pool = psycopg2.pool.SimpleConnectionPool(
            MIN_CONNS, MAX_CONNS,
            user=DB_USER, password=DB_PASS, dbname=DB_NAME,
            host=DB_HOST, port=DB_PORT,
            connect_timeout=10,
            sslmode="disable" if DB_HOST.startswith("/") else "prefer",
        )
    return conn_pool

# ---- MODELS ----
class CreateClanRequest(BaseModel):
    name: str = Field(..., min_length=1, max_length=255)
    region: str = Field(..., min_length=1, max_length=16)

class CreateClanResponse(BaseModel):
    id: str
    message: str = "Clan created successfully."

class Clan(BaseModel):
    id: str  # UUID string
    name: str
    region: str
    created_at: Optional[datetime] = None

# ---- ROUTES ----
@app.get("/")
def root():
    return {"status": "up", "docs": "/docs", "health": "/health"}

@app.get("/health")
def health():
    return {"status": "ok"}

@app.post("/clans", response_model=CreateClanResponse, status_code=201)
def create_clan(payload: CreateClanRequest):
    pool_ = get_pool()
    conn = None
    try:
        conn = pool_.getconn()
        with conn.cursor() as cur:
            cur.execute(
                sql.SQL("""
                    INSERT INTO {}.{} (name, region, created_at)
                    VALUES (%s, %s, NOW())
                    RETURNING id
                """).format(sql.Identifier(DB_SCHEMA), sql.Identifier(DB_TABLE)),
                (payload.name, payload.region),
            )
            new_id = cur.fetchone()[0]
        conn.commit()
        return CreateClanResponse(id=str(new_id))
    except psycopg2.Error as e:
        if conn: conn.rollback()
        raise HTTPException(status_code=500, detail=f"DB error: {e.pgerror or str(e)}")
    finally:
        if conn: pool_.putconn(conn)

@app.get("/clans", response_model=List[Clan])
def list_clans(
    region: Optional[str] = Query(None, description="Filter by exact region"),
    sort_by: str = Query("created_at", description="id|name|region|created_at"),
    order: str = Query("desc", description="asc|desc"),
    limit: int = Query(100, ge=1, le=1000),
    offset: int = Query(0, ge=0),
):
    pool_ = get_pool()
    conn = None
    try:
        allowed_cols = {"id", "name", "region", "created_at"}
        if sort_by not in allowed_cols:
            raise HTTPException(status_code=400, detail=f"Invalid sort_by: {sort_by}")
        order_norm = order.lower()
        if order_norm not in {"asc", "desc"}:
            raise HTTPException(status_code=400, detail=f"Invalid order: {order}")
        order_sql = sql.SQL("ASC") if order_norm == "asc" else sql.SQL("DESC")

        base_q = sql.SQL("SELECT id, name, region, created_at FROM {}.{}").format(
            sql.Identifier(DB_SCHEMA), sql.Identifier(DB_TABLE)
        )
        where_q = sql.SQL("")
        params = []
        if region:
            where_q = sql.SQL(" WHERE region = %s")
            params.append(region)

        order_q = sql.SQL(" ORDER BY {} ").format(sql.Identifier(sort_by)) + order_sql
        limit_q = sql.SQL(" LIMIT %s OFFSET %s")
        params.extend([limit, offset])

        conn = pool_.getconn()
        with conn.cursor() as cur:
            cur.execute(base_q + where_q + order_q + limit_q, params)
            rows = cur.fetchall()

        return [Clan(id=str(r[0]), name=r[1], region=r[2], created_at=r[3]) for r in rows]
    except psycopg2.Error as e:
        raise HTTPException(status_code=500, detail=f"DB error: {e.pgerror or str(e)}")
    finally:
        if conn: pool_.putconn(conn)

@app.get("/clans/{clan_id}", response_model=Clan)
def get_clan(clan_id: UUID):
    pool_ = get_pool()
    conn = None
    try:
        conn = pool_.getconn()
        with conn.cursor() as cur:
            cur.execute(
                sql.SQL("SELECT id, name, region, created_at FROM {}.{} WHERE id = %s")
                   .format(sql.Identifier(DB_SCHEMA), sql.Identifier(DB_TABLE)),
                (str(clan_id),),
            )
            row = cur.fetchone()
            if not row:
                raise HTTPException(status_code=404, detail="Clan not found")
            return Clan(id=str(row[0]), name=row[1], region=row[2], created_at=row[3])
    except psycopg2.Error as e:
        raise HTTPException(status_code=500, detail=f"DB error: {e.pgerror or str(e)}")
    finally:
        if conn: pool_.putconn(conn)

@app.delete("/clans/{clan_id}")
def delete_clan(clan_id: UUID):
    pool_ = get_pool()
    conn = None
    try:
        conn = pool_.getconn()
        with conn.cursor() as cur:
            cur.execute(
                sql.SQL("DELETE FROM {}.{} WHERE id = %s RETURNING id")
                   .format(sql.Identifier(DB_SCHEMA), sql.Identifier(DB_TABLE)),
                (str(clan_id),),
            )
            deleted = cur.fetchone()
        conn.commit()
        if not deleted:
            raise HTTPException(status_code=404, detail="Clan not found")
        return {"id": str(deleted[0]), "message": "Clan deleted successfully."}
    finally:
        if conn: pool_.putconn(conn)

# ---- Auto-migrate on startup ----
@app.on_event("startup")
def migrate():
    # Cloud Run'da DB ulaşılmazsa app düşmesin:
    try:
        pool_ = get_pool()
        conn = pool_.getconn()
        try:
            with conn.cursor() as cur:
                cur.execute(sql.SQL("CREATE SCHEMA IF NOT EXISTS {}").format(sql.Identifier(DB_SCHEMA)))
                # UUID için extension (Cloud SQL Postgres'te serbest)
                cur.execute('CREATE EXTENSION IF NOT EXISTS "pgcrypto";')
                cur.execute(sql.SQL("""
                    CREATE TABLE IF NOT EXISTS {}.{} (
                        id UUID PRIMARY KEY DEFAULT gen_random_uuid(),
                        name TEXT NOT NULL,
                        region VARCHAR(16) NOT NULL,
                        created_at TIMESTAMP NOT NULL DEFAULT NOW()
                    )
                """).format(sql.Identifier(DB_SCHEMA), sql.Identifier(DB_TABLE)))
            conn.commit()
        finally:
            pool_.putconn(conn)
    except Exception as e:
        import logging
        logging.exception("Startup migrate failed (continuing): %s", e)

@app.on_event("shutdown")
def shutdown_event():
    global conn_pool
    if conn_pool is not None:
        conn_pool.closeall()

        conn_pool = None
