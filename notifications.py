"""
Envio real de notificações (e-mail + WhatsApp) quando o status de uma linha muda.

E-mail: usa a API da Resend (https://resend.com) — free tier: 3.000 e-mails/mês,
100/dia. Defina RESEND_API_KEY. Para produção, verifique um domínio próprio na
Resend e ajuste RESEND_FROM; enquanto isso, o remetente de teste padrão deles
(onboarding@resend.dev) funciona, mas só envia pro e-mail da conta cadastrada
na Resend — ok pra validar o fluxo, não pra clientes reais ainda.

WhatsApp: usa a WhatsApp Cloud API da Meta. Defina WHATSAPP_TOKEN e
WHATSAPP_PHONE_NUMBER_ID (do seu app no Meta for Developers).

IMPORTANTE — limitação real da Cloud API: fora da janela de 24h após o
usuário ter escrito pro seu número, a Meta exige que a mensagem seja um
"template" pré-aprovado por eles (não texto livre). Esse arquivo já manda
texto livre (`send_whatsapp`), que funciona só dentro dessa janela de 24h
ou em números de teste. Pra alertas automáticos de linha (que a Meta vai
classificar como "utility"), você vai precisar criar e aprovar um template
de mensagem no painel da Meta — é rápido, mas é um passo manual que eu não
consigo fazer por você.
"""

import json
import os
from datetime import datetime
from zoneinfo import ZoneInfo

import requests

from database import db

RESEND_API_KEY = os.environ.get("RESEND_API_KEY")
RESEND_FROM = os.environ.get("RESEND_FROM", "MetroReport <onboarding@resend.dev>")

WHATSAPP_TOKEN = os.environ.get("WHATSAPP_TOKEN")
WHATSAPP_PHONE_NUMBER_ID = os.environ.get("WHATSAPP_PHONE_NUMBER_ID")

# Push (PWA) — o VAPID_PUBLIC_KEY também é usado pelo frontend pra assinar a
# notificação no navegador (endpoint /api/push/vapid-public-key).
VAPID_PRIVATE_KEY = os.environ.get("VAPID_PRIVATE_KEY")
VAPID_PUBLIC_KEY = os.environ.get("VAPID_PUBLIC_KEY")
VAPID_CLAIMS_EMAIL = os.environ.get("VAPID_CLAIMS_EMAIL", "mailto:contato@example.com")

SP_TZ = ZoneInfo("America/Sao_Paulo")


def send_push(subscription: dict, title: str, body: str, tag: str = "metroreport-status") -> bool:
    """subscription = {"endpoint": ..., "p256dh": ..., "auth": ...} (como salvo no banco)."""
    if not VAPID_PRIVATE_KEY:
        print("[notifications] VAPID_PRIVATE_KEY não definida — pulando push")
        return False
    try:
        from pywebpush import WebPushException, webpush

        webpush(
            subscription_info={
                "endpoint": subscription["endpoint"],
                "keys": {"p256dh": subscription["p256dh"], "auth": subscription["auth"]},
            },
            data=json.dumps({"title": title, "body": body, "tag": tag, "url": "/"}),
            vapid_private_key=VAPID_PRIVATE_KEY,
            vapid_claims={"sub": VAPID_CLAIMS_EMAIL},
        )
        return True
    except Exception as exc:
        # Uma subscription "gone" (410/404) significa que o navegador cancelou
        # sozinho (ex: app desinstalado) — removemos do banco pra não tentar de novo.
        status = getattr(getattr(exc, "response", None), "status_code", None)
        if status in (404, 410):
            with db() as conn:
                conn.execute("DELETE FROM push_subscriptions WHERE endpoint = %s", (subscription["endpoint"],))
        print(f"[notifications] erro ao enviar push: {exc}")
        return False


def send_email(to: str, subject: str, html: str) -> bool:
    if not RESEND_API_KEY:
        print(f"[notifications] RESEND_API_KEY não definida — pulando e-mail para {to}")
        return False
    try:
        resp = requests.post(
            "https://api.resend.com/emails",
            headers={"Authorization": f"Bearer {RESEND_API_KEY}", "Content-Type": "application/json"},
            json={"from": RESEND_FROM, "to": [to], "subject": subject, "html": html},
            timeout=10,
        )
        resp.raise_for_status()
        return True
    except Exception as exc:
        print(f"[notifications] erro ao enviar e-mail para {to}: {exc}")
        return False


def send_whatsapp(to_phone: str, message: str) -> bool:
    if not WHATSAPP_TOKEN or not WHATSAPP_PHONE_NUMBER_ID:
        print(f"[notifications] WhatsApp não configurado — pulando envio para {to_phone}")
        return False
    try:
        resp = requests.post(
            f"https://graph.facebook.com/v20.0/{WHATSAPP_PHONE_NUMBER_ID}/messages",
            headers={"Authorization": f"Bearer {WHATSAPP_TOKEN}", "Content-Type": "application/json"},
            json={
                "messaging_product": "whatsapp",
                "to": to_phone,
                "type": "text",
                "text": {"body": message},
            },
            timeout=10,
        )
        resp.raise_for_status()
        return True
    except Exception as exc:
        print(f"[notifications] erro ao enviar WhatsApp para {to_phone}: {exc}")
        return False


def notify_status_change(line_id: str, line_name: str, status_label: str, detail: str | None) -> None:
    """Avisa (push é o canal principal; e-mail/WhatsApp são complementares,
    conforme a preferência de cada usuário) todo mundo que tem essa linha
    habilitada nas notificações e está dentro da janela de horário
    configurada (se houver)."""
    now_str = datetime.now(SP_TZ).strftime("%H:%M")

    with db() as conn:
        rows = conn.execute(
            """
            SELECT u.id AS user_id, u.email, u.phone, u.notify_channel, np.start_time, np.end_time
            FROM notification_prefs np
            JOIN users u ON u.id = np.user_id
            WHERE np.line_id = %s AND np.enabled = 1
            """,
            (line_id,),
        ).fetchall()
        # subscriptions de push são buscadas à parte pois um usuário pode ter
        # mais de um aparelho/navegador instalado
        user_ids = [r["user_id"] for r in rows if not (r["start_time"] and r["end_time"] and not (r["start_time"] <= now_str <= r["end_time"]))]
        push_subs = []
        if user_ids:
            placeholders = ",".join(["%s"] * len(user_ids))
            push_subs = conn.execute(
                f"SELECT user_id, endpoint, p256dh, auth FROM push_subscriptions WHERE user_id IN ({placeholders})",
                tuple(user_ids),
            ).fetchall()

    subject = f"MetroReport — Linha {line_name}: {status_label}"
    message = f"Linha {line_name}: {status_label}." + (f" {detail}" if detail else "")
    html = f"<p><strong>Linha {line_name}</strong> — {status_label}</p>" + (f"<p>{detail}</p>" if detail else "")

    push_by_user: dict[int, list[dict]] = {}
    for sub in push_subs:
        push_by_user.setdefault(sub["user_id"], []).append(sub)

    for row in rows:
        if row["start_time"] and row["end_time"] and not (row["start_time"] <= now_str <= row["end_time"]):
            continue  # fora da janela de horário que o usuário escolheu
        channel = row["notify_channel"] or "email"
        for sub in push_by_user.get(row["user_id"], []):
            send_push(sub, f"Linha {line_name}", status_label + (f" — {detail}" if detail else ""))
        if channel in ("email", "both") and row["email"]:
            send_email(row["email"], subject, html)
        if channel in ("whatsapp", "both") and row["phone"]:
            send_whatsapp(row["phone"], message)
