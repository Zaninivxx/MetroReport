import os
from contextlib import contextmanager

import psycopg
from psycopg.rows import dict_row

# String de conexão do banco Postgres (gratuito) — defina em uma variável de
# ambiente ou em um arquivo .env local (veja .env.example).
# Serviços gratuitos recomendados: Supabase, Neon ou Railway Postgres.
DATABASE_URL = os.environ.get("DATABASE_URL")

if not DATABASE_URL:
    raise RuntimeError(
        "DATABASE_URL não definida. Crie um banco Postgres gratuito (Supabase, "
        "Neon ou Railway) e coloque a connection string na variável de ambiente "
        "DATABASE_URL (veja backend/.env.example)."
    )

# Linhas oficiais de Metrô + CPTM de São Paulo (dados estáticos base)
LINES = [
    {"id": "1",  "number": "1",  "name": "Azul",      "type": "metro", "color": "#0854A0"},
    {"id": "2",  "number": "2",  "name": "Verde",      "type": "metro", "color": "#00693C"},
    {"id": "3",  "number": "3",  "name": "Vermelha",   "type": "metro", "color": "#EE1C25"},
    {"id": "4",  "number": "4",  "name": "Amarela",    "type": "metro", "color": "#F5C400"},
    {"id": "5",  "number": "5",  "name": "Lilás",      "type": "metro", "color": "#9C4A9C"},
    {"id": "15", "number": "15", "name": "Prata",      "type": "metro", "color": "#8D8E90"},
    {"id": "7",  "number": "7",  "name": "Rubi",       "type": "cptm",  "color": "#9A1F40"},
    {"id": "8",  "number": "8",  "name": "Diamante",   "type": "cptm",  "color": "#7B7C7E"},
    {"id": "9",  "number": "9",  "name": "Esmeralda",  "type": "cptm",  "color": "#00814F"},
    {"id": "10", "number": "10", "name": "Turquesa",   "type": "cptm",  "color": "#00A19A"},
    {"id": "11", "number": "11", "name": "Coral",      "type": "cptm",  "color": "#F0592B"},
    {"id": "12", "number": "12", "name": "Safira",     "type": "cptm",  "color": "#0F3E8C"},
    {"id": "13", "number": "13", "name": "Jade",       "type": "cptm",  "color": "#00543C"},
]


def get_conn():
    # row_factory=dict_row deixa cada linha acessível como row["coluna"],
    # exatamente como o sqlite3.Row usado antes — o resto do código não muda.
    return psycopg.connect(DATABASE_URL, row_factory=dict_row)


@contextmanager
def db():
    conn = get_conn()
    try:
        yield conn
        conn.commit()
    except Exception:
        conn.rollback()
        raise
    finally:
        conn.close()


def init_db():
    with db() as conn:
        conn.execute("""
            CREATE TABLE IF NOT EXISTS users (
                id SERIAL PRIMARY KEY,
                name TEXT NOT NULL,
                email TEXT UNIQUE NOT NULL,
                password_hash TEXT NOT NULL,
                salt TEXT NOT NULL,
                avatar_base64 TEXT,
                created_at TIMESTAMPTZ NOT NULL DEFAULT now()
            )
        """)
        # migração leve: adiciona colunas novas se o banco já existia sem elas
        conn.execute("ALTER TABLE users ADD COLUMN IF NOT EXISTS phone TEXT")
        conn.execute("ALTER TABLE users ADD COLUMN IF NOT EXISTS notify_channel TEXT NOT NULL DEFAULT 'email'")
        conn.execute("""
            CREATE TABLE IF NOT EXISTS notification_prefs (
                user_id INTEGER NOT NULL REFERENCES users(id) ON DELETE CASCADE,
                line_id TEXT NOT NULL,
                enabled INTEGER NOT NULL DEFAULT 1,
                start_time TEXT,
                end_time TEXT,
                PRIMARY KEY (user_id, line_id)
            )
        """)
        conn.execute("""
            CREATE TABLE IF NOT EXISTS line_status (
                line_id TEXT PRIMARY KEY,
                status TEXT NOT NULL DEFAULT 'normal',
                detail TEXT,
                updated_at TIMESTAMPTZ NOT NULL DEFAULT now()
            )
        """)
        conn.execute("""
            CREATE TABLE IF NOT EXISTS password_reset_tokens (
                token_hash TEXT PRIMARY KEY,
                user_id INTEGER NOT NULL REFERENCES users(id) ON DELETE CASCADE,
                expires_at TIMESTAMPTZ NOT NULL,
                used INTEGER NOT NULL DEFAULT 0,
                created_at TIMESTAMPTZ NOT NULL DEFAULT now()
            )
        """)
        conn.execute("""
            CREATE TABLE IF NOT EXISTS push_subscriptions (
                id SERIAL PRIMARY KEY,
                user_id INTEGER NOT NULL REFERENCES users(id) ON DELETE CASCADE,
                endpoint TEXT UNIQUE NOT NULL,
                p256dh TEXT NOT NULL,
                auth TEXT NOT NULL,
                created_at TIMESTAMPTZ NOT NULL DEFAULT now()
            )
        """)
        # popula status inicial (normal) se ainda não existir
        for line in LINES:
            conn.execute(
                "INSERT INTO line_status (line_id, status, detail) VALUES (%s, 'normal', NULL) "
                "ON CONFLICT (line_id) DO NOTHING",
                (line["id"],),
            )
