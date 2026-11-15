"""Atende AI ponta a ponta com gateway de canais falso e IA falsa (sem rede, sem WhatsApp)."""
import datetime as dt
import hashlib
import hmac
import json
import os
import sys
import time

sys.path.insert(0, os.path.join(os.path.dirname(__file__), ".."))
os.environ["ATENDEAI_SEM_APP"] = "1"

import httpx  # noqa: E402
import pytest  # noqa: E402
from fastapi.testclient import TestClient  # noqa: E402

from app import atendente  # noqa: E402
from app.canais import Gateway, assinatura_ok  # noqa: E402
from app.config import Config  # noqa: E402
from app.main import criar_app  # noqa: E402


class GatewayFalso:
    def __init__(self):
        self.enviadas, self.entregas, self.n = [], [], 0
        self.estado = "pending_auth"

    def handler(self, req: httpx.Request) -> httpx.Response:
        p = req.url.path.replace("/internal/channels", "")
        corpo = json.loads(req.content or b"{}") if req.content else {}
        assert req.headers["authorization"] == "Bearer tok"
        if req.method == "POST" and p == "/connections":
            self.n += 1
            return httpx.Response(201, json={"connection": {"id": f"c{self.n}", "state": "pending_auth", "external_label": ""},
                                             "step": {"step_id": "s1", "kind": "qr", "qr": {"data": "2@QRFALSO"}, "wait": {"poll_after_s": 3}}})
        if p.endswith("/delivery"):
            self.entregas.append(corpo)
            return httpx.Response(200, json={"ok": True})
        if p.endswith("/send"):
            self.enviadas.append(corpo)
            return httpx.Response(200, json={"status": "queued"})
        if req.method == "GET":
            return httpx.Response(200, json={"connection": {"id": p.split("/")[-1], "state": self.estado, "external_label": "+55 62 9999-0000"}})
        if p.endswith("/step"):
            if corpo["data"].get("password") == "errada":
                return httpx.Response(200, json={"connection": {"state": "pending_auth"}, "step": {"kind": "credentials", "error_code": "wrong_password"}})
            return httpx.Response(200, json={"connection": {"state": "connected"}, "step": {"kind": "complete"}})
        return httpx.Response(200, json={"connection": {"state": "disconnected"}})


def llm_falso(msgs):
    ultimo = msgs[-1]["content"]
    if "Assuntos obrigatórios" in ultimo:
        return json.dumps({"pronta": False, "pergunta": "Quais produtos e preços?", "campos": {"negocio": "Pizzaria"}})
    if "desconto" in ultimo:
        return "[HUMANO]"
    return "A pizza grande custa R$ 59."


@pytest.fixture
def ambiente(tmp_path):
    gf = GatewayFalso()
    cfg = Config(dados=str(tmp_path), segredo_sessao="s", dev=True, canais_token="tok", cakto_segredo="ck",
                 planos_por_produto={"p-whats-pro": "whats:pro"}, demo_email="")
    gw = Gateway("http://gw", "tok", transport=httpx.MockTransport(gf.handler))
    app = criar_app(cfg, gateway=gw, llm=llm_falso, sincrono=True)
    c = TestClient(app, base_url="http://atende-whats.rangeltech.net")
    cod = c.post("/api/entrar/codigo", json={"email": "loja@x.com"}).json()["codigo_dev"]
    assert c.post("/api/entrar", json={"email": "loja@x.com", "codigo": cod}).status_code == 200
    return c, gf, app


def assinar(segredo, corpo, ts=None):
    ts = str(int(ts or time.time()))
    return {"x-luar-timestamp": ts, "x-luar-signature": "sha256=" + hmac.new(segredo.encode(), f"{ts}.".encode() + corpo, hashlib.sha256).hexdigest(),
            "content-type": "application/json"}


def comprar(c, produto="p-whats-pro"):
    r = c.post("/api/cakto", json={"secret": "ck", "event": "purchase_approved", "data": {"id": "ped1", "customer": {"email": "loja@x.com"}, "product": {"id": produto}}})
    assert r.json().get("liberado")


def test_marca_pelo_host(ambiente):
    c, _, _ = ambiente
    assert c.get("/api/marca").json()["marca"]["codigo"] == "whats"
    assert "Atende AI Whats" in c.get("/").text


def test_conectar_exige_plano_e_aceite(ambiente):
    c, _, _ = ambiente
    assert c.post("/api/contas", json={"aceite": True}).status_code == 402
    comprar(c)
    assert c.post("/api/contas", json={}).status_code == 422
    r = c.post("/api/contas", json={"aceite": True}).json()
    assert r["passo"]["qr"] == "2@QRFALSO" and r["estado"] == "pending_auth"
    c.post("/api/contas", json={"aceite": True})
    assert c.post("/api/contas", json={"aceite": True}).status_code == 402  # Pro = 2 contas


def test_passo_com_erro_traduzido_e_conectado(ambiente):
    c, gf, _ = ambiente
    comprar(c)
    cid = c.post("/api/contas", json={"aceite": True}).json()["id"]
    r = c.post(f"/api/contas/{cid}/passo", json={"passo": "s1", "tipo": "credentials", "dados": {"password": "errada"}}).json()
    assert r["passo"]["erro"] == "Usuário ou senha errados."
    gf.estado = "connected"
    assert c.get(f"/api/contas/{cid}").json()["estado"] == "connected"
    assert gf.entregas and gf.entregas[0]["webhook_url"].endswith(f"/hooks/canal/{cid}")


def preparar_conta(c, app):
    comprar(c)
    cid = c.post("/api/contas", json={"aceite": True}).json()["id"]
    app.state.db.exec("UPDATE contas SET estado='connected' WHERE id=?", (cid,))
    c.put("/api/skill", json={"texto": "## Pizzaria\nGrande R$ 59.", "palavras_humano": "atendente,humano"})
    segredo = app.state.db.um("SELECT segredo_webhook FROM contas WHERE id=?", (cid,))["segredo_webhook"]
    return cid, segredo


def evento(eid, texto, conversa="5562988880000@s.whatsapp.net"):
    return json.dumps({"event_id": eid, "type": "message.created", "conversation": {"external_id": conversa, "contact": {"name": "Ana"}},
                       "message": {"external_id": "m" + eid, "direction": "incoming", "text": texto}}).encode()


def test_webhook_assinado_e_ia_responde(ambiente):
    c, gf, app = ambiente
    cid, seg = preparar_conta(c, app)
    corpo = evento("e1", "quanto custa a pizza grande?")
    assert c.post(f"/hooks/canal/{cid}", content=corpo, headers=assinar("errado", corpo)).status_code == 401
    assert c.post(f"/hooks/canal/{cid}", content=corpo, headers=assinar(seg, corpo, time.time() - 900)).status_code == 401
    assert c.post(f"/hooks/canal/{cid}", content=corpo, headers=assinar(seg, corpo)).json()["ok"]
    assert gf.enviadas[-1]["text"] == "A pizza grande custa R$ 59."
    assert c.post(f"/hooks/canal/{cid}", content=corpo, headers=assinar(seg, corpo)).json().get("repetido")
    assert len(gf.enviadas) == 1
    conv = c.get("/api/conversas").json()["conversas"][0]
    assert conv["contato"] == "Ana" and conv["nao_lidas"] == 1
    msgs = c.get(f"/api/conversas/{conv['id']}").json()["mensagens"]
    assert [m["direcao"] for m in msgs] == ["entrada", "ia"]


def test_pede_humano_e_ia_para(ambiente):
    c, gf, app = ambiente
    cid, seg = preparar_conta(c, app)
    corpo = evento("e2", "quero falar com um atendente")
    c.post(f"/hooks/canal/{cid}", content=corpo, headers=assinar(seg, corpo))
    assert "chamar alguém" in gf.enviadas[-1]["text"]
    corpo = evento("e3", "oi?")
    c.post(f"/hooks/canal/{cid}", content=corpo, headers=assinar(seg, corpo))
    assert len(gf.enviadas) == 1  # conversa ficou com humano
    conv = c.get("/api/conversas").json()["conversas"][0]
    assert conv["modo"] == "humano"
    c.post(f"/api/conversas/{conv['id']}/devolver")
    corpo = evento("e4", "e a média?")
    c.post(f"/hooks/canal/{cid}", content=corpo, headers=assinar(seg, corpo))
    assert len(gf.enviadas) == 2


def test_ia_nao_sabe_passa_para_humano(ambiente):
    c, gf, app = ambiente
    cid, seg = preparar_conta(c, app)
    corpo = evento("e5", "me dá desconto?")
    c.post(f"/hooks/canal/{cid}", content=corpo, headers=assinar(seg, corpo))
    assert "chamar alguém" in gf.enviadas[-1]["text"]
    assert c.get("/api/conversas").json()["conversas"][0]["modo"] == "humano"


def test_humano_responde_pelo_painel(ambiente):
    c, gf, app = ambiente
    cid, seg = preparar_conta(c, app)
    corpo = evento("e6", "oi")
    c.post(f"/hooks/canal/{cid}", content=corpo, headers=assinar(seg, corpo))
    conv = c.get("/api/conversas").json()["conversas"][0]["id"]
    assert c.post(f"/api/conversas/{conv}/enviar", json={"texto": "Oi Ana, aqui é o João"}).json()["ok"]
    assert gf.enviadas[-1]["text"] == "Oi Ana, aqui é o João"


def test_ia_desligada_nao_responde(ambiente):
    c, gf, app = ambiente
    cid, seg = preparar_conta(c, app)
    c.post(f"/api/contas/{cid}/desligar_ia")
    corpo = evento("e7", "quanto custa?")
    c.post(f"/hooks/canal/{cid}", content=corpo, headers=assinar(seg, corpo))
    assert gf.enviadas == []


def test_outro_usuario_nao_ve_conta(ambiente, tmp_path):
    c, _, app = ambiente
    cid, _ = preparar_conta(c, app)
    c2 = TestClient(app, base_url="http://atende-whats.rangeltech.net")
    cod = c2.post("/api/entrar/codigo", json={"email": "outro@x.com"}).json()["codigo_dev"]
    c2.post("/api/entrar", json={"email": "outro@x.com", "codigo": cod})
    assert c2.get(f"/api/contas/{cid}").status_code == 404
    assert c2.get("/api/contas").json()["contas"] == []


def test_skill_construtor_versoes_e_teste(ambiente):
    c, _, _ = ambiente
    r = c.post("/api/skill/chat", json={"texto": "tenho uma pizzaria"}).json()
    assert r["pronta"] is False and r["pergunta"] == "Quais produtos e preços?"
    c.put("/api/skill", json={"texto": "v1"})
    c.put("/api/skill", json={"texto": "v2"})
    s = c.get("/api/skill").json()
    assert len(s["versoes"]) == 2 and s["historico"][0]["papel"] == "user"
    assert c.post(f"/api/skill/versoes/{s['versoes'][-1]['id']}/restaurar").json()["texto"] == "v1"
    t = c.post("/api/skill/testar", json={"texto": "quanto custa?"}).json()
    assert t["acao"] == "responder"


def test_horario_e_palavras():
    seg_10h = dt.datetime(2026, 11, 16, 10, 0, tzinfo=atendente.TZ_BR)  # segunda
    dom_10h = dt.datetime(2026, 11, 15, 10, 0, tzinfo=atendente.TZ_BR)
    h = json.dumps({"dias": [0, 1, 2, 3, 4], "inicio": "08:00", "fim": "18:00"})
    assert atendente.dentro_do_horario(h, seg_10h) and not atendente.dentro_do_horario(h, dom_10h)
    assert atendente.dentro_do_horario("", dom_10h)
    assert atendente.pede_humano("Quero um ATENDENTE agora", "atendente,humano")
    assert atendente.pede_humano("tenho uma reclamacao", "reclamação")
    assert not atendente.pede_humano("atendimento rápido", "atendente")
    skill = {"texto": "x", "horario": h, "palavras_humano": "", "fora_horario": ""}
    d = atendente.decidir("oi", [], skill, "WhatsApp", "ia", 0, time.time(), lambda m: "oi", dom_10h)
    assert d["acao"] == "fora_horario"
    d = atendente.decidir("oi", [], skill, "WhatsApp", "ia", time.time(), time.time(), lambda m: "oi", dom_10h)
    assert d["acao"] == "nada"


def test_sem_regras_nao_inventa():
    d = atendente.decidir("oi", [], {"texto": "", "horario": "", "palavras_humano": ""}, "WhatsApp", "ia", 0, time.time(), lambda m: "resposta")
    assert d["acao"] == "humano" and d["texto"] == ""


def test_assinatura_gateway():
    corpo = b'{"a":1}'
    ts = str(int(time.time()))
    sig = "sha256=" + hmac.new(b"k", f"{ts}.".encode() + corpo, hashlib.sha256).hexdigest()
    assert assinatura_ok("k", ts, sig, corpo)
    assert not assinatura_ok("k", ts, sig, corpo + b" ")
    assert not assinatura_ok("k", "x", sig, corpo)


def test_cakto_reembolso_revoga(ambiente):
    c, _, _ = ambiente
    comprar(c)
    assert c.get("/api/conta").json()["assinante"]
    c.post("/api/cakto", json={"secret": "ck", "event": "refund", "data": {"id": "ped1", "customer": {"email": "loja@x.com"}, "product": {"id": "p-whats-pro"}}})
    assert not c.get("/api/conta").json()["assinante"]
    assert c.post("/api/cakto", json={"secret": "errado", "event": "x"}).status_code == 401
