# MetroReport — Web App

Web app completo: tela de login/cadastro, banco de dados **Postgres real e
persistente na nuvem**, dashboard com status das linhas em "bolhas"
coloridas, notificações por linha, e perfil com iniciais/foto.

## Estrutura

```
metroreport/
├── backend/
│   ├── main.py          → API FastAPI (rotas de auth, linhas, perfil, notificações)
│   ├── database.py      → conexão Postgres + schema + lista de linhas
│   ├── auth.py           → hash de senha (PBKDF2) + JWT
│   ├── models.py        → schemas (Pydantic)
│   ├── requirements.txt
│   └── .env.example     → modelo do arquivo .env (copie e preencha)
└── frontend/
    ├── index.html
    ├── css/style.css
    └── js/app.js
```

## Passo 1 — criar o banco de dados gratuito

Antes o projeto usava SQLite (um arquivo local). O problema: no Railway e no
Render (planos gratuitos), o disco é **efêmero** — a cada novo deploy o
arquivo `.db` some e todos os cadastros de clientes são perdidos. Por isso o
banco agora é um **Postgres gerenciado na nuvem**, que persiste independente
de quantas vezes você reiniciar ou redeployar o backend.

Escolha um (todos têm plano gratuito que aguenta tranquilamente a fase de
validação do projeto):

- **[Supabase](https://supabase.com)** — mais simples de começar, já vem com
  painel visual pra ver os dados direto no navegador.
- **[Neon](https://neon.tech)** — foco só em Postgres, também tem painel, boa
  opção se quiser algo mais enxuto.
- **Postgres do próprio Railway** (se o backend já vai estar lá, um clique
  a mais no mesmo projeto já sobe o banco).

Depois de criar, copie a **connection string** (algo como
`postgresql://usuario:senha@host:5432/nomedobanco`).

## Passo 2 — configurar variáveis de ambiente

```bash
cd backend
cp .env.example .env
```

Abra `.env` e preencha:

```
DATABASE_URL=postgresql://usuario:senha@host:5432/nomedobanco
METRO_SECRET_KEY=uma-string-aleatoria-bem-longa
```

(gere a `METRO_SECRET_KEY` com `python -c "import secrets; print(secrets.token_hex(32))"`)

## Passo 3 — rodar local (Windows / VS Code)

```bash
cd backend
pip install -r requirements.txt
uvicorn main:app --reload --port 8000
```

Abra **http://localhost:8000** — o próprio backend já serve o frontend.

As tabelas são criadas automaticamente no Postgres na primeira execução
(não precisa rodar nenhum script de migração à parte).

## O que já está funcionando

- **Cadastro/login** com senha (hash PBKDF2 + JWT)
- **Esqueci minha senha**: pede o link por e-mail, clica, define nova senha
  (token de uso único, expira em 30 min, hash do token no banco)
- **Banco Postgres persistente** — cadastros de clientes e preferências não
  se perdem mais a cada deploy
- **Notificações de verdade**: quando o status de uma linha muda, os
  usuários com aquela linha habilitada recebem e-mail e/ou WhatsApp
  (conforme a preferência de cada um, configurável no Perfil), respeitando
  a janela de horário que a pessoa escolheu
- **Dashboard**: bolhas de cada linha (Metrô + CPTM), cor oficial, status ao
  vivo, indicador pulsante quando há instabilidade
- **Perfil**: nome, telefone, canal de notificação preferido, avatar com
  iniciais automáticas, opção de trocar por foto
- **Sidebar retrátil** + versão mobile com menu deslizante

## Notificação push (PWA) — canal principal

O app agora é um **PWA instalável**: a pessoa loga uma vez, autoriza
notificações (banner que aparece no dashboard), e a partir daí recebe aviso
automático quando uma linha muda de status — mesmo com o site fechado —,
sem precisar abrir o app pra conferir.

- **Instalar no celular**: abrir o site no Chrome (Android) e usar "Adicionar
  à tela inicial", ou no Safari (iPhone) usar o botão de compartilhar →
  "Adicionar à Tela de Início".
- **iPhone tem uma limitação da própria Apple**: só funciona se a pessoa
  *instalar* o atalho (não é automático s\u00f3 de visitar pelo Safari) e o
  aparelho estiver no iOS 16.4 ou mais novo.
- As chaves VAPID (usadas pra assinar as notificações) já vêm prontas no
  `.env.example` pra você testar. **Antes de ir pra produção**, gere as
  suas próprias rodando `python generate_vapid_keys.py` dentro de `backend/`
  e substitua no `.env` — as do exemplo passaram por esta conversa, então
  tratam-se como não-privadas.
- Os ícones do app (`frontend/icons/icon-192.png` e `icon-512.png`) são um
  placeholder simples gerado automaticamente — troque por uma arte de
  verdade quando tiver a identidade visual fechada.

## Configurar e-mail e WhatsApp (canais complementares ao push)

- **E-mail**: crie uma conta grátis na [Resend](https://resend.com), gere uma
  API key e coloque em `RESEND_API_KEY` no `.env`. Sem domínio próprio
  verificado, o remetente de teste (`onboarding@resend.dev`) só envia pro
  e-mail da sua própria conta Resend — dá pra validar o fluxo, mas pra
  clientes reais é preciso verificar um domínio (rápido, no painel deles).
- **WhatsApp**: crie um app no [Meta for Developers](https://developers.facebook.com/),
  ative a WhatsApp Cloud API, e coloque `WHATSAPP_TOKEN` e
  `WHATSAPP_PHONE_NUMBER_ID` no `.env`. **Atenção**: fora da janela de 24h
  após o cliente ter mandado mensagem pro seu número, a Meta exige que o
  aviso seja um *template* de mensagem pré-aprovado por eles (não texto
  livre) — isso é um cadastro manual no painel da Meta que fica pra você
  fazer quando for pra produção.
- Se nenhuma das duas estiver configurada, o sistema não quebra: só loga no
  console que pulou o envio, e o resto do produto continua funcionando.

## O que foi removido

- A funcionalidade de **"Meu trajeto"** (cadastro de casa/trabalho com aviso
  de rota alternativa) foi retirada — back e frontend — a pedido, por não
  fazer sentido pro momento atual do produto.

## O que ainda é simulado (próximo passo)

O status das linhas só é atualizado quando `fetch_artesp_status()` (em
`main.py`) retornar dados reais — hoje ela retorna `None` de propósito, então
o dashboard mantém o último status salvo. Para ligar ao scraper real:

1. Implemente a chamada real dentro de `fetch_artesp_status()`.
2. Sempre que capturar uma mudança, o próprio poller já faz o
   `UPDATE line_status ...` — o resto (dashboard, notificações) reflete sozinho.
3. `POST /api/lines/status/override` já existe pra forçar um status
   manualmente durante testes/demonstração com o cliente.

## Segurança — antes de deployar

- **Nunca** suba o arquivo `.env` pro Git (já está no `.gitignore`).
- Regenere a API key da ARTESP e o token do bot do Telegram que ficaram
  expostos antes — mesmo trocando de repositório, considere-os comprometidos.
- Sem `METRO_SECRET_KEY` definida, o token JWT usa uma chave gerada na hora,
  que muda a cada restart — isso derruba todo mundo do login sozinho.

## Deploy sugerido

- **Banco**: Supabase ou Neon (gratuito, persistente)
- **Backend**: Railway ou Render (sobe o FastAPI direto, lendo `DATABASE_URL`
  e `METRO_SECRET_KEY` das variáveis de ambiente do próprio painel)
- Como o backend já serve o frontend, um único deploy resolve tudo.
