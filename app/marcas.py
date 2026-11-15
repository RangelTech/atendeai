"""Quatro produtos, um código: Atende AI Whats, Insta, TikTok e Face (spec 44 5.4). A marca vem do host."""
from __future__ import annotations

MARCAS = {
    "whats": {"nome": "Atende AI Whats", "rede": "WhatsApp", "provider": "whatsapp", "cor": "#25d366",
              "hosts": ["atende-whats.rangeltech.net", "atende-ai.rangeltech.net"],
              "conecta": "Leia o QR com o WhatsApp do número que vai atender (Aparelhos conectados).",
              "atende": "conversas do WhatsApp"},
    "insta": {"nome": "Atende AI Insta", "rede": "Instagram", "provider": "instagram", "cor": "#e1306c",
              "hosts": ["atende-insta.rangeltech.net"],
              "conecta": "Entre com o usuário e a senha do Instagram. Se pedir código, ele chega no seu celular.",
              "atende": "mensagens diretas do Instagram"},
    "tiktok": {"nome": "Atende AI TikTok", "rede": "TikTok", "provider": "tiktok", "cor": "#00f2ea",
               "hosts": ["atende-tiktok.rangeltech.net"],
               "conecta": "Leia o QR com o app do TikTok (Perfil → menu → leitor de QR).",
               "atende": "mensagens diretas do TikTok"},
    "face": {"nome": "Atende AI Face", "rede": "Facebook", "provider": "messenger", "cor": "#1877f2",
             "hosts": ["atende-face.rangeltech.net"],
             "conecta": "Entre com o e-mail e a senha do Facebook. Se pedir código, ele chega no seu celular.",
             "atende": "conversas do Messenger"},
}

# Planos por marca: contas conectadas e mensagens respondidas pela IA por mês.
PLANOS = {
    "start": {"nome": "Start", "preco": 29.90, "contas": 1, "msgs_mes": 1000,
              "itens": ["1 conta conectada", "1.000 respostas da IA por mês", "Regras montadas conversando", "Assumir a conversa quando quiser"]},
    "pro": {"nome": "Pro", "preco": 59.90, "contas": 2, "msgs_mes": 5000,
            "itens": ["2 contas conectadas", "5.000 respostas por mês", "Horário de atendimento", "Palavras que chamam você"]},
    "turbo": {"nome": "Top", "preco": 119.90, "contas": 5, "msgs_mes": 20000,
              "itens": ["5 contas conectadas", "20.000 respostas por mês", "Tudo do Pro", "Para agências que atendem vários clientes"]},
}


def por_host(host: str) -> str:
    h = (host or "").split(":")[0].lower()
    for k, m in MARCAS.items():
        if h in m["hosts"]:
            return k
    for k in MARCAS:  # dev: ?marca= ou subdomínio parcial
        if h.startswith(f"atende-{k}"):
            return k
    return "whats"


def publica(k: str) -> dict:
    m = MARCAS[k]
    return {"codigo": k, "nome": m["nome"], "rede": m["rede"], "cor": m["cor"], "conecta": m["conecta"], "atende": m["atende"]}
