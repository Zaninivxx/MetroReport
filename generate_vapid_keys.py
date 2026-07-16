"""
Gera um novo par de chaves VAPID (usadas pra assinar as notificações push do
PWA). Rode isso uma vez antes de ir pra produção — as chaves do
.env.example são só pra teste, e como passaram por essa conversa com a IA,
o ideal é gerar as suas próprias antes de expor o app pra clientes de verdade.

Uso:
    cd backend
    python generate_vapid_keys.py

Copia a saída pro seu .env (linhas VAPID_PRIVATE_KEY / VAPID_PUBLIC_KEY).
"""

import base64

from cryptography.hazmat.primitives.serialization import Encoding, PublicFormat
from py_vapid import Vapid02

v = Vapid02()
v.generate_keys()

priv_num = v.private_key.private_numbers().private_value
priv_b64 = base64.urlsafe_b64encode(priv_num.to_bytes(32, "big")).rstrip(b"=").decode()

pub_raw = v.public_key.public_bytes(Encoding.X962, PublicFormat.UncompressedPoint)
pub_b64 = base64.urlsafe_b64encode(pub_raw).rstrip(b"=").decode()

print("Cole isso no seu .env:\n")
print(f"VAPID_PRIVATE_KEY={priv_b64}")
print(f"VAPID_PUBLIC_KEY={pub_b64}")
