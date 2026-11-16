"""Cliente do gateway de canais do LUAR (contrato: chatwoot-rt/docs/canais/CONTRATO_GATEWAY.md).

O gateway guarda a sessão de cada conta (Matrix + pontes mautrix, TikTok por worker) e entrega as
mensagens num webhook assinado. Senha e código só passam em `step`, de forma síncrona; nada disso é
guardado aqui nem vai para log.
"""
from __future__ import annotations

import hashlib
import hmac
import time

import httpx


class CanalErro(Exception):
    def __init__(self, status: int, codigo: str):
        super().__init__(f"{status} {codigo}")
        self.status = status
        self.codigo = codigo


class Gateway:
    def __init__(self, url: str, token: str, transport: httpx.BaseTransport | None = None):
        self.url = url.rstrip("/") + "/internal/channels"
        self.token = token
        self.transport = transport

    def _r(self, metodo: str, caminho: str, **kw) -> dict:
        if not self.token:
            raise CanalErro(503, "gateway_sem_token")
        try:
            with httpx.Client(transport=self.transport, timeout=60) as h:
                r = h.request(metodo, self.url + caminho, headers={"Authorization": f"Bearer {self.token}"}, **kw)
        except httpx.HTTPError as e:
            raise CanalErro(503, "gateway_fora") from e
        if r.status_code >= 400:
            try:
                d = r.json().get("detail")
            except ValueError:
                d = None
            raise CanalErro(r.status_code, str(d or "erro"))
        return r.json() if r.content else {}

    def conectar(self, conta: int, provider: str, ator: str, fluxo: str | None = None) -> dict:
        return self._r("POST", "/connections", json={"account_id": conta, "provider": provider, "actor_id": ator,
                                                     "consent": {"accepted": True, "version": "atendeai-2026-11"}, "login_flow": fluxo})

    def status(self, conta: int, cid: str) -> dict:
        return self._r("GET", f"/connections/{cid}", params={"account_id": conta})

    def passo(self, conta: int, cid: str, step_id: str, tipo: str, dados: dict) -> dict:
        return self._r("POST", f"/connections/{cid}/step", json={"account_id": conta, "step_id": step_id, "kind": tipo, "data": dados})

    def cancelar(self, conta: int, cid: str) -> dict:
        return self._r("POST", f"/connections/{cid}/cancel", json={"account_id": conta})

    def desconectar(self, conta: int, cid: str, ator: str) -> dict:
        return self._r("POST", f"/connections/{cid}/disconnect", json={"account_id": conta, "actor_id": ator})

    def reconectar(self, conta: int, cid: str, ator: str) -> dict:
        return self._r("POST", f"/connections/{cid}/reauth", json={"account_id": conta, "actor_id": ator})

    def entrega(self, conta: int, cid: str, url: str, segredo: str) -> dict:
        return self._r("PUT", f"/connections/{cid}/delivery", json={"account_id": conta, "webhook_url": url, "webhook_secret": segredo, "inbox_ref": "atendeai"})

    def enviar(self, conta: int, cid: str, conversa: str, texto: str, chave: str, anexos: list[dict] | None = None) -> dict:
        corpo = {"account_id": conta, "idempotency_key": chave, "conversation_ref": conversa, "text": texto}
        if anexos:
            corpo["attachments"] = anexos
        return self._r("POST", f"/connections/{cid}/send", json=corpo)

    def midia(self, conta: int, cid: str, mxc: str) -> bytes:
        """Baixa a mídia que o cliente mandou (ex.: áudio para transcrever)."""
        if not self.token:
            raise CanalErro(503, "gateway_sem_token")
        try:
            with httpx.Client(transport=self.transport, timeout=60) as h:
                r = h.get(self.url + f"/connections/{cid}/media", params={"account_id": conta, "mxc": mxc},
                          headers={"Authorization": f"Bearer {self.token}"})
        except httpx.HTTPError as e:
            raise CanalErro(503, "gateway_fora") from e
        if r.status_code >= 400:
            raise CanalErro(r.status_code, "midia")
        return r.content


def assinatura_ok(segredo: str, ts: str, assinatura: str, corpo: bytes, tolerancia: int = 300, agora: float | None = None) -> bool:
    """Mesma regra do gateway: HMAC_SHA256(segredo, "<ts>.<corpo>"), janela de 5 minutos."""
    try:
        t = int(ts)
    except (TypeError, ValueError):
        return False
    if abs((agora if agora is not None else time.time()) - t) > tolerancia:
        return False
    esperado = "sha256=" + hmac.new(segredo.encode(), f"{t}.".encode() + corpo, hashlib.sha256).hexdigest()
    return hmac.compare_digest(esperado, assinatura or "")
