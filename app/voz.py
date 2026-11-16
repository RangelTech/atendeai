"""Voz do Atende AI (spec 44, 8.2): entende o áudio que chega e responde em nota de voz com a voz do dono.

Tudo roda no servidor de voz da Rangel Tech (rt-voz, GPU própria, acessado pela rede interna). Sem custo por mensagem.
- ouvir(): áudio do cliente -> {tipo: fala|musica, texto, musica}
- falar(): texto -> OGG/Opus (nota de voz), na voz do dono quando ela já foi treinada
"""
from __future__ import annotations

import base64
import re

import httpx


_SEM_EMOJI = re.compile("[🀀-🫿☀-➿️‍]+")


class Voz:
    def __init__(self, base: str, token: str, transport: httpx.BaseTransport | None = None):
        self.base = (base or "").rstrip("/")
        self.token = token
        self.transport = transport

    @property
    def ligada(self) -> bool:
        return bool(self.base and self.token)

    def _h(self) -> dict:
        return {"Authorization": f"Bearer {self.token}"}

    def ouvir(self, audio: bytes, nome: str = "audio.ogg") -> dict:
        with httpx.Client(transport=self.transport, timeout=180) as h:
            r = h.post(self.base + "/v1/ouvir", headers=self._h(), files={"audio": (nome, audio)})
        r.raise_for_status()
        return r.json()

    def falar(self, texto: str, voz: str | None) -> tuple[bytes, int]:
        """(ogg, duração em ms)."""
        falado = _SEM_EMOJI.sub("", texto).strip()  # emoji não vira som estranho na voz
        corpo = {"texto": (falado or texto)[:1200], "formato": "ogg"}
        if voz:
            corpo["voz"] = voz
        with httpx.Client(transport=self.transport, timeout=240) as h:
            r = h.post(self.base + "/v1/falar", headers=self._h(), json=corpo)
        r.raise_for_status()
        segundos = float(r.headers.get("x-voz-segundos") or 0)
        return r.content, int(segundos * 1000)


def texto_da_entrada(ouvido: dict) -> str:
    """Como a mensagem de áudio entra no histórico e na decisão da IA."""
    m = ouvido.get("musica")
    if ouvido.get("tipo") == "musica" and m:
        return f"[o cliente mandou um áudio com música tocando: {m.get('titulo')} de {m.get('artista')}]"
    t = (ouvido.get("texto") or "").strip()
    return f"[áudio] {t}" if t else "[áudio sem fala]"


def anexo_voz(ogg: bytes, ms: int) -> dict:
    return {"kind": "audio", "mime": "audio/ogg", "name": "voz.ogg", "duration_ms": ms,
            "url": "data:audio/ogg;base64," + base64.b64encode(ogg).decode()}
