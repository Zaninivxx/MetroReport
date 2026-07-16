import hashlib
import os
import secrets
import time
from typing import Optional

import jwt
from fastapi import Depends, HTTPException, status
from fastapi.security import HTTPAuthorizationCredentials, HTTPBearer

# Em produção, defina MET RO_SECRET_KEY como variável de ambiente.
SECRET_KEY = os.environ.get("METRO_SECRET_KEY", "troque-esta-chave-em-producao-" + secrets.token_hex(8))
ALGORITHM = "HS256"
TOKEN_TTL_SECONDS = 60 * 60 * 24 * 7  # 7 dias

security = HTTPBearer(auto_error=False)


def hash_password(password: str, salt: Optional[str] = None) -> tuple[str, str]:
    if salt is None:
        salt = secrets.token_hex(16)
    digest = hashlib.pbkdf2_hmac("sha256", password.encode("utf-8"), salt.encode("utf-8"), 200_000)
    return digest.hex(), salt


def verify_password(password: str, salt: str, expected_hash: str) -> bool:
    digest, _ = hash_password(password, salt)
    return secrets.compare_digest(digest, expected_hash)


def create_token(user_id: int) -> str:
    payload = {"sub": str(user_id), "exp": int(time.time()) + TOKEN_TTL_SECONDS}
    return jwt.encode(payload, SECRET_KEY, algorithm=ALGORITHM)


def decode_token(token: str) -> int:
    try:
        payload = jwt.decode(token, SECRET_KEY, algorithms=[ALGORITHM])
        return int(payload["sub"])
    except jwt.PyJWTError:
        raise HTTPException(status_code=401, detail="Token inválido ou expirado")


def get_current_user_id(credentials: HTTPAuthorizationCredentials = Depends(security)) -> int:
    if credentials is None:
        raise HTTPException(status_code=401, detail="Não autenticado")
    return decode_token(credentials.credentials)


# ---------------------------------------------------- RESET DE SENHA ------
# Token de reset é gerado com alta entropia e só o hash (sha256) vai pro
# banco — mesmo que o banco vaze, ninguém consegue usar o token a partir dele.

def generate_reset_token() -> tuple[str, str]:
    """Retorna (token_bruto_para_mandar_por_email, hash_para_salvar_no_banco)."""
    raw = secrets.token_urlsafe(32)
    return raw, hashlib.sha256(raw.encode("utf-8")).hexdigest()


def hash_reset_token(raw_token: str) -> str:
    return hashlib.sha256(raw_token.encode("utf-8")).hexdigest()
