import asyncio
import hashlib
import os
import secrets
from contextlib import asynccontextmanager
from datetime import datetime, timedelta, timezone

from dotenv import load_dotenv

load_dotenv()  # lê backend/.env em desenvolvimento local (não sobrescreve variáveis já definidas no ambiente)

from fastapi import Depends, FastAPI, HTTPException
from fastapi.middleware.cors import CORSMiddleware
from fastapi.staticfiles import StaticFiles

from auth import create_token, get_current_user_id, hash_password, verify_password
from database import LINES, db, init_db
from notifications import VAPID_PUBLIC_KEY, notify_status_change, send_email, send_push
from models import (
    ForgotPasswordRequest,
    LoginRequest,
    NotificationPrefsRequest,
    ProfileUpdateRequest,
    PushSubscribeRequest,
    PushUnsubscribeRequest,
    RegisterRequest,
    ResetPasswordRequest,
    StatusOverrideRequest,
)

# URL pública do frontend, usada para montar o link de redefinição de senha
# que vai no e-mail. Em produção defina isso pra URL real (ex: a do Vercel).
FRONTEND_BASE_URL = os.environ.get("FRONTEND_BASE_URL", "http://localhost:8000")
RESET_TOKEN_TTL_MINUTES = 30

STATUS_LABELS = {
    "normal": "Operação normal",
    "reduzida": "Velocidade reduzida",
    "parcial": "Operação parcial",
    "paralisada": "Linha paralisada",
}

# A ARTESP libera no máximo 12 chamadas/hora -> 1 a cada 5 minutos.
# Ajuste aqui se o limite mudar.
ARTESP_POLL_INTERVAL_SECONDS = 5 * 60


def fetch_artesp_status() -> list[dict] | None:
    """Busca o status real na ARTESP.

    TODO: plugar aqui a função do scraper Python que você já tem (a que lê a
    API da ARTESP com a API key). Ela deve devolver uma lista de dicts, um
    por linha, por exemplo:

        [{"line_id": "1", "status": "normal", "detail": None}, ...]

    onde "status" é um dos valores: normal | reduzida | parcial | paralisada
    (se a ARTESP usar outros nomes de status, é só mapear aqui mesmo, antes
    de devolver).

    Por enquanto retorna None (sem dado real ainda), e o loop abaixo mantém
    o último status salvo no banco em vez de sobrescrever com dado simulado.
    """
    # api_key = os.environ.get("ARTESP_API_KEY")
    # resp = requests.get("https://api.artesp.sp.gov.br/...", headers={"Authorization": f"Bearer {api_key}"})
    # resp.raise_for_status()
    # raw = resp.json()
    # return [parse_artesp_line(item) for item in raw]
    return None


def _update_line_status_and_notify(conn, line_id: str, status_code: str, detail: str | None) -> None:
    """Atualiza o status da linha e, só se o status realmente mudou desde a
    última leitura, dispara as notificações (e-mail/WhatsApp) pros usuários
    que têm essa linha habilitada. Evita spam de notificação repetindo o
    mesmo status a cada poll."""
    prev = conn.execute("SELECT status FROM line_status WHERE line_id = %s", (line_id,)).fetchone()
    conn.execute(
        "UPDATE line_status SET status = %s, detail = %s, updated_at = now() WHERE line_id = %s",
        (status_code, detail, line_id),
    )
    changed = not prev or prev["status"] != status_code
    if changed:
        line_info = next((l for l in LINES if l["id"] == line_id), None)
        if line_info:
            notify_status_change(
                line_id=line_id,
                line_name=line_info["name"],
                status_label=STATUS_LABELS.get(status_code, status_code),
                detail=detail,
            )


async def status_poller():
    """Busca dado real da ARTESP respeitando o limite de 12 chamadas/hora. Se
    `fetch_artesp_status` ainda não estiver plugado (retorna None), simplesmente
    não atualiza nada — o dashboard continua mostrando o último status
    conhecido, sem inventar dado."""
    while True:
        try:
            data = fetch_artesp_status()
            if data:
                with db() as conn:
                    for item in data:
                        _update_line_status_and_notify(conn, item["line_id"], item["status"], item.get("detail"))
        except Exception as exc:
            # Nunca deixa o poller morrer por causa de um erro pontual na API externa.
            print(f"[status_poller] erro ao buscar status da ARTESP: {exc}")
        await asyncio.sleep(ARTESP_POLL_INTERVAL_SECONDS)


@asynccontextmanager
async def lifespan(app: FastAPI):
    init_db()
    task = asyncio.create_task(status_poller())
    yield
    task.cancel()


app = FastAPI(title="MetroReport API", lifespan=lifespan)

app.add_middleware(
    CORSMiddleware,
    allow_origins=["*"],
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)


def user_public(row: dict) -> dict:
    return {
        "id": row["id"],
        "name": row["name"],
        "email": row["email"],
        "avatar_base64": row["avatar_base64"],
        "phone": row["phone"],
        "notify_channel": row["notify_channel"],
        "initials": "".join([p[0].upper() for p in row["name"].split()[:2]]),
    }


# ---------------------------------------------------------------- AUTH ----

@app.post("/api/auth/register")
def register(payload: RegisterRequest):
    with db() as conn:
        existing = conn.execute("SELECT id FROM users WHERE email = %s", (payload.email,)).fetchone()
        if existing:
            raise HTTPException(status_code=409, detail="Este e-mail já está cadastrado")
        password_hash, salt = hash_password(payload.password)
        cur = conn.execute(
            "INSERT INTO users (name, email, password_hash, salt) VALUES (%s, %s, %s, %s) RETURNING id",
            (payload.name.strip(), payload.email.lower(), password_hash, salt),
        )
        user_id = cur.fetchone()["id"]
        for line in LINES:
            conn.execute(
                "INSERT INTO notification_prefs (user_id, line_id, enabled) VALUES (%s, %s, 1)",
                (user_id, line["id"]),
            )
        row = conn.execute("SELECT * FROM users WHERE id = %s", (user_id,)).fetchone()
    token = create_token(user_id)
    return {"token": token, "user": user_public(row)}


@app.post("/api/auth/login")
def login(payload: LoginRequest):
    with db() as conn:
        row = conn.execute("SELECT * FROM users WHERE email = %s", (payload.email.lower(),)).fetchone()
    if not row or not verify_password(payload.password, row["salt"], row["password_hash"]):
        raise HTTPException(status_code=401, detail="E-mail ou senha incorretos")
    token = create_token(row["id"])
    return {"token": token, "user": user_public(row)}


@app.post("/api/auth/forgot-password")
def forgot_password(payload: ForgotPasswordRequest):
    with db() as conn:
        row = conn.execute(
            "SELECT id, name FROM users WHERE email = %s", (payload.email.lower(),)
        ).fetchone()
        if row:
            raw_token = secrets.token_urlsafe(32)
            token_hash = hashlib.sha256(raw_token.encode("utf-8")).hexdigest()
            expires_at = datetime.now(timezone.utc) + timedelta(minutes=RESET_TOKEN_TTL_MINUTES)
            conn.execute(
                "INSERT INTO password_reset_tokens (token_hash, user_id, expires_at) VALUES (%s, %s, %s)",
                (token_hash, row["id"], expires_at),
            )
            reset_link = f"{FRONTEND_BASE_URL}/?reset_token={raw_token}"
            send_email(
                payload.email.lower(),
                "Redefinir senha — MetroReport",
                f"<p>Olá {row['name']},</p>"
                f"<p>Clique no link abaixo para redefinir sua senha (válido por "
                f"{RESET_TOKEN_TTL_MINUTES} minutos):</p>"
                f"<p><a href='{reset_link}'>{reset_link}</a></p>"
                f"<p>Se você não pediu isso, ignore este e-mail.</p>",
            )
    # Resposta idêntica exista ou não o e-mail, pra não revelar quais e-mails
    # estão cadastrados na base.
    return {"ok": True, "message": "Se esse e-mail estiver cadastrado, enviamos um link de redefinição."}


@app.post("/api/auth/reset-password")
def reset_password(payload: ResetPasswordRequest):
    token_hash = hashlib.sha256(payload.token.encode("utf-8")).hexdigest()
    with db() as conn:
        row = conn.execute(
            "SELECT * FROM password_reset_tokens WHERE token_hash = %s AND used = 0",
            (token_hash,),
        ).fetchone()
        if not row or row["expires_at"] < datetime.now(timezone.utc):
            raise HTTPException(status_code=400, detail="Link inválido ou expirado. Peça um novo.")
        password_hash, salt = hash_password(payload.new_password)
        conn.execute(
            "UPDATE users SET password_hash = %s, salt = %s WHERE id = %s",
            (password_hash, salt, row["user_id"]),
        )
        conn.execute("UPDATE password_reset_tokens SET used = 1 WHERE token_hash = %s", (token_hash,))
    return {"ok": True}


# ------------------------------------------------------------- PERFIL -----

@app.get("/api/me")
def get_me(user_id: int = Depends(get_current_user_id)):
    with db() as conn:
        row = conn.execute("SELECT * FROM users WHERE id = %s", (user_id,)).fetchone()
        if not row:
            raise HTTPException(status_code=404, detail="Usuário não encontrado")
    return user_public(row)


@app.put("/api/me/profile")
def update_profile(payload: ProfileUpdateRequest, user_id: int = Depends(get_current_user_id)):
    if payload.notify_channel and payload.notify_channel not in ("email", "whatsapp", "both", "none"):
        raise HTTPException(status_code=400, detail="Canal de notificação inválido")
    with db() as conn:
        if payload.name:
            conn.execute("UPDATE users SET name = %s WHERE id = %s", (payload.name.strip(), user_id))
        if payload.avatar_base64 is not None:
            conn.execute("UPDATE users SET avatar_base64 = %s WHERE id = %s", (payload.avatar_base64, user_id))
        if payload.phone is not None:
            conn.execute("UPDATE users SET phone = %s WHERE id = %s", (payload.phone.strip() or None, user_id))
        if payload.notify_channel is not None:
            conn.execute("UPDATE users SET notify_channel = %s WHERE id = %s", (payload.notify_channel, user_id))
        row = conn.execute("SELECT * FROM users WHERE id = %s", (user_id,)).fetchone()
    return user_public(row)


# -------------------------------------------------------------- LINHAS ----

@app.get("/api/lines/status")
def lines_status():
    with db() as conn:
        statuses = {r["line_id"]: r for r in conn.execute("SELECT * FROM line_status").fetchall()}
    result = []
    for line in LINES:
        st = statuses.get(line["id"])
        status_code = st["status"] if st else "normal"
        result.append({
            **line,
            "status": status_code,
            "status_label": STATUS_LABELS.get(status_code, status_code),
            "detail": st["detail"] if st else None,
            "updated_at": st["updated_at"].isoformat() if st and st["updated_at"] else None,
        })
    return result


@app.post("/api/lines/status/override")
def override_status(payload: StatusOverrideRequest):
    """Endpoint auxiliar para simular/testar incidentes manualmente durante a demo."""
    if payload.status not in STATUS_LABELS:
        raise HTTPException(status_code=400, detail="Status inválido")
    with db() as conn:
        _update_line_status_and_notify(conn, payload.line_id, payload.status, payload.detail)
    return {"ok": True}


# --------------------------------------------------------------- PUSH -----

@app.get("/api/push/vapid-public-key")
def get_vapid_public_key():
    if not VAPID_PUBLIC_KEY:
        raise HTTPException(status_code=503, detail="Push não configurado no servidor (falta VAPID_PUBLIC_KEY)")
    return {"public_key": VAPID_PUBLIC_KEY}


@app.post("/api/me/push-subscribe")
def push_subscribe(payload: PushSubscribeRequest, user_id: int = Depends(get_current_user_id)):
    with db() as conn:
        conn.execute(
            """INSERT INTO push_subscriptions (user_id, endpoint, p256dh, auth)
               VALUES (%s, %s, %s, %s)
               ON CONFLICT (endpoint) DO UPDATE SET
                 user_id = excluded.user_id, p256dh = excluded.p256dh, auth = excluded.auth""",
            (user_id, payload.endpoint, payload.p256dh, payload.auth),
        )
    return {"ok": True}


@app.post("/api/me/push-unsubscribe")
def push_unsubscribe(payload: PushUnsubscribeRequest, user_id: int = Depends(get_current_user_id)):
    with db() as conn:
        conn.execute(
            "DELETE FROM push_subscriptions WHERE endpoint = %s AND user_id = %s",
            (payload.endpoint, user_id),
        )
    return {"ok": True}


@app.post("/api/dev/test-notification")
def dev_test_notification(user_id: int = Depends(get_current_user_id)):
    """Só pra debug durante o desenvolvimento: manda push pro(s) próprio(s)
    aparelho(s) de quem clicou, resumindo o status atual de todas as linhas —
    não mexe em nada no banco e não notifica mais ninguém. O fluxo real (só
    avisa o usuário quando UMA linha específica muda pra ruim) continua
    intacto em `_update_line_status_and_notify`."""
    with db() as conn:
        rows = conn.execute("SELECT * FROM line_status").fetchall()
        subs = conn.execute(
            "SELECT endpoint, p256dh, auth FROM push_subscriptions WHERE user_id = %s", (user_id,)
        ).fetchall()

    if not subs:
        raise HTTPException(
            status_code=400,
            detail="Você ainda não ativou as notificações push nesse navegador (clica em 'Ativar' no dashboard antes de testar).",
        )

    status_by_line = {r["line_id"]: r for r in rows}
    bad = []
    for line in LINES:
        st = status_by_line.get(line["id"])
        code = st["status"] if st else "normal"
        if code != "normal":
            bad.append({
                "name": line["name"],
                "status_label": STATUS_LABELS.get(code, code),
                "detail": st["detail"] if st else None,
            })

    if not bad:
        title = "MetroReport — teste"
        body = "Todas as linhas estão operando normalmente."
    else:
        resumo = "; ".join(
            f"Linha {b['name']}: {b['status_label']}" + (f" ({b['detail']})" if b["detail"] else "")
            for b in bad
        )
        title = f"MetroReport — teste: {len(bad)} linha(s) com problema"
        body = f"{resumo}. As demais linhas estão normais."

    sent = sum(1 for sub in subs if send_push(sub, title, body, tag="metroreport-dev-test"))

    return {"ok": True, "sent": sent, "total_devices": len(subs), "bad_lines": bad, "title": title, "body": body}


# --------------------------------------------------------- NOTIFICAÇÕES ---

@app.get("/api/me/notifications")
def get_notifications(user_id: int = Depends(get_current_user_id)):
    with db() as conn:
        rows = conn.execute(
            "SELECT line_id, enabled, start_time, end_time FROM notification_prefs WHERE user_id = %s", (user_id,)
        ).fetchall()
    prefs = {r["line_id"]: r for r in rows}
    result = []
    for line in LINES:
        row = prefs.get(line["id"])
        result.append({
            "line_id": line["id"],
            "name": line["name"],
            "enabled": bool(row["enabled"]) if row else True,
            "start_time": row["start_time"] if row else None,
            "end_time": row["end_time"] if row else None,
        })
    return result


@app.put("/api/me/notifications")
def update_notifications(payload: NotificationPrefsRequest, user_id: int = Depends(get_current_user_id)):
    for item in payload.prefs:
        if item.start_time and item.end_time and item.start_time >= item.end_time:
            raise HTTPException(status_code=400, detail="O horário final precisa ser depois do inicial")
    with db() as conn:
        for item in payload.prefs:
            conn.execute(
                """INSERT INTO notification_prefs (user_id, line_id, enabled, start_time, end_time)
                   VALUES (%s, %s, %s, %s, %s)
                   ON CONFLICT (user_id, line_id) DO UPDATE SET
                     enabled = excluded.enabled,
                     start_time = excluded.start_time,
                     end_time = excluded.end_time""",
                (user_id, item.line_id, int(item.enabled), item.start_time, item.end_time),
            )
    return {"ok": True}


# ----------------------------------------------------- ARQUIVOS ESTÁTICOS -
# Serve o frontend a partir do mesmo processo, para facilitar rodar localmente.
# Caminho absoluto baseado na localização deste arquivo (funciona não importa
# de onde o comando é executado, inclusive no Windows).
_FRONTEND_DIR = os.path.normpath(os.path.join(os.path.dirname(os.path.abspath(__file__)), "..", "frontend"))
app.mount("/", StaticFiles(directory=_FRONTEND_DIR, html=True), name="frontend")


# Permite rodar tanto com `uvicorn main:app --reload` quanto clicando em
# "Run" direto no main.py (ex: no VS Code) — nesse segundo caso não tem
# auto-reload, mas sobe o servidor do mesmo jeito.
if __name__ == "__main__":
    import uvicorn
    uvicorn.run("main:app", host="0.0.0.0", port=8000, reload=True)
