"""Configuração por variável de ambiente (segredos em /opt/platform/secrets/atendeai.env na VPS)."""
from __future__ import annotations

import json
import os
from dataclasses import dataclass, field


@dataclass
class Config:
    dados: str = "/data"
    base_url: str = "https://atende-ai.rangeltech.net"
    llm_base: str = "https://qwen.rangeltech.net/v1"
    llm_key: str = ""
    llm_modelo: str = "rt-planejar"       # quem responde o cliente final (GPT pelo llm-access)
    segredo_sessao: str = "dev"
    smtp_host: str = ""
    smtp_port: int = 587
    smtp_user: str = ""
    smtp_senha: str = ""
    smtp_from: str = "Atende AI <contato@rangeltech.net>"
    cakto_segredo: str = ""
    checkouts: dict = field(default_factory=dict)            # {"whats:pro": url, ...}
    planos_por_produto: dict = field(default_factory=dict)   # {"<id produto Cakto>": "whats:pro"}
    # gateway de canais do LUAR (rede interna da VPS)
    canais_url: str = "http://chatwoot-bridge:8100"
    canais_token: str = ""
    webhook_base: str = "http://atendeai:8000"              # como o gateway enxerga este serviço
    conta_base: int = 7_000_000                               # account_id no gateway = conta_base + id do usuário
    admin_key: str = ""
    demo_email: str = ""
    demo_senha: str = ""
    lancamento_ate: str = "2026-12-15"
    dev: bool = False
    voz_base: str = ""        # servidor de voz (rt-voz) pela rede interna; vazio = sem voz
    voz_token: str = ""
    imagem_base: str = ""     # llm-access (GPT de imagem) para as fotos da persona; vazio = usa llm_base
    imagem_key: str = ""


def carregar() -> Config:
    e = os.environ.get
    return Config(
        dados=e("ATENDEAI_DADOS", "/data"),
        base_url=e("ATENDEAI_BASE_URL", "https://atende-ai.rangeltech.net").rstrip("/"),
        llm_base=e("ATENDEAI_LLM_BASE", "https://qwen.rangeltech.net/v1").rstrip("/"),
        llm_key=e("ATENDEAI_LLM_KEY", ""),
        llm_modelo=e("ATENDEAI_LLM_MODELO", "rt-planejar"),
        segredo_sessao=e("ATENDEAI_SEGREDO_SESSAO", "dev"),
        smtp_host=e("SMTP_HOST", ""),
        smtp_port=int(e("SMTP_PORT", "587") or 587),
        smtp_user=e("SMTP_USER", ""),
        smtp_senha=e("SMTP_PASSWORD", ""),
        smtp_from=e("ATENDEAI_SMTP_FROM", "Atende AI <contato@rangeltech.net>"),
        cakto_segredo=e("ATENDEAI_CAKTO_SEGREDO", ""),
        checkouts=json.loads(e("ATENDEAI_CHECKOUTS", "") or "{}"),
        planos_por_produto=json.loads(e("ATENDEAI_PLANOS_CAKTO", "") or "{}"),
        canais_url=e("ATENDEAI_CANAIS_URL", "http://chatwoot-bridge:8100").rstrip("/"),
        canais_token=e("ATENDEAI_CANAIS_TOKEN", ""),
        webhook_base=e("ATENDEAI_WEBHOOK_BASE", "http://atendeai:8000").rstrip("/"),
        conta_base=int(e("ATENDEAI_CONTA_BASE", "7000000")),
        admin_key=e("ATENDEAI_ADMIN_KEY", ""),
        demo_email=e("ATENDEAI_DEMO_EMAIL", ""),
        demo_senha=e("ATENDEAI_DEMO_SENHA", ""),
        voz_base=e("ATENDEAI_VOZ_BASE", "").rstrip("/"),
        voz_token=e("ATENDEAI_VOZ_TOKEN", ""),
        imagem_base=e("ATENDEAI_IMAGEM_BASE", "").rstrip("/"),
        imagem_key=e("ATENDEAI_IMAGEM_KEY", ""),
        lancamento_ate=e("ATENDEAI_LANCAMENTO_ATE", "2026-12-15"),
        dev=e("ATENDEAI_DEV", "") == "1",
    )
