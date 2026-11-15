# Atende AI (Whats, Insta, TikTok, Face)

Atendimento com IA nas redes do cliente. Um código, quatro marcas (a marca vem do host):
`atende-whats`, `atende-insta`, `atende-tiktok`, `atende-face` (`.rangeltech.net`).

- **Conexão 24/7:** pelo gateway de canais do LUAR (`chatwoot-bridge`, `/internal/channels`), que mantém a sessão
  (Matrix + pontes mautrix; TikTok por worker) e entrega as mensagens num webhook assinado (HMAC, janela de 5 min).
  `account_id` no gateway = `ATENDEAI_CONTA_BASE` (7.000.000) + id do usuário, para nunca colidir com conta do Chatwoot.
- **Harness** (`app/atendente.py`): humano assumiu > palavra que chama humano > fora do horário > IA com as regras;
  sem regra ou sem resposta, passa para humano. Nunca inventa preço/prazo.
- **Regras (skill):** construtor por conversa (8 assuntos), edição à mão, versões, "Testar" sem enviar nada.
- **Painel:** conversas (assumir/devolver, responder como você), conta conectada (QR, código de pareamento, senha/2FA),
  plano. Login com senha (padrão), código por e-mail ou "esqueci a senha" (módulo comum).
- **Planos** por marca, pela Cakto: Start/Pro/Top = contas conectadas e respostas da IA por mês.

## Rodar os testes
```
pip install -r requirements-dev.txt && python -m pytest -q
```

## Variáveis
`ATENDEAI_LLM_KEY`, `ATENDEAI_SEGREDO_SESSAO`, `ATENDEAI_CANAIS_TOKEN` (= `CHANNELS_GATEWAY_TOKEN` do gateway),
`ATENDEAI_CANAIS_URL` (padrão `http://chatwoot-bridge:8100`), `ATENDEAI_WEBHOOK_BASE` (padrão `http://atendeai:8000`),
`ATENDEAI_CAKTO_SEGREDO`, `ATENDEAI_CHECKOUTS`, `ATENDEAI_PLANOS_CAKTO`, `ATENDEAI_ADMIN_KEY`, `ATENDEAI_DEMO_EMAIL`, SMTP_*.

Deploy: release neste repo (workflow `Release`), implantação só pelo `vps_rt_infra`.
