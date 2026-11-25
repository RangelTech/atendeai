"""Fala Fael: fã por número, teste grátis, convite, Cakto pelo celular, foto e painel do admin (gateway e IA falsos)."""
from produtos_core.teste import entrar
import io
import json
import os
import sys
import time

sys.path.insert(0, os.path.join(os.path.dirname(__file__), ".."))
os.environ["ATENDEAI_SEM_APP"] = "1"

import httpx  # noqa: E402
import pytest  # noqa: E402
from fastapi.testclient import TestClient  # noqa: E402
from PIL import Image  # noqa: E402

from app import persona as pers  # noqa: E402
from app.canais import Gateway  # noqa: E402
from app.config import Config  # noqa: E402
from app.main import criar_app  # noqa: E402
from tests.test_atendeai import GatewayFalso, assinar  # noqa: E402

FONE = "5562988880000@s.whatsapp.net"


def _jpg(cor="red"):
    b = io.BytesIO(); Image.new("RGB", (40, 40), cor).save(b, "JPEG"); return b.getvalue()


class GatewayFoto(GatewayFalso):
    def handler(self, req):
        if req.url.path.endswith("/media") and str(req.url.params.get("mxc", "")).startswith("mxc://img"):
            self.midias.append(dict(req.url.params))
            return httpx.Response(200, content=_jpg("blue"), headers={"content-type": "image/jpeg"})
        return super().handler(req)


def llm_fael(msgs):
    ultimo = msgs[-1]["content"]
    if "nós dois" in ultimo:
        return "Bora! [FOTO: eu e você montando no mesmo cavalo, rindo]"
    if "foto" in ultimo:
        return "Toma uma minha agora! [FOTO: eu no curral ao pôr do sol, chapéu preto]"
    return "Opa, tudo certo por aqui, e com você?"


@pytest.fixture
def fael(tmp_path):
    gf = GatewayFoto()
    cfg = Config(dados=str(tmp_path), segredo_sessao="s", dev=True, canais_token="tok", cakto_segredo="ck",
                 planos_por_produto={"p-fa": "fael:fa", "p-vip": "fael:vip"}, checkouts={"fael:fa": "https://pay.cakto.com.br/fa"})
    gw = Gateway("http://gw", "tok", transport=httpx.MockTransport(gf.handler))
    app = criar_app(cfg, gateway=gw, llm=llm_fael, sincrono=True)
    c = TestClient(app, base_url="http://fala-fael.rangeltech.net")
    entrar(c, "admin@fael.com")
    db = app.state.db
    uid = db.um("SELECT id FROM usuarios WHERE email='admin@fael.com'")["id"]
    db.exec("INSERT INTO assinaturas(usuario,marca,plano,ativo_ate) VALUES(?,?,?,?)", (uid, "fael", "turbo", time.time() + 86400))
    cid = c.post("/api/contas", json={"aceite": True}).json()["id"]
    db.exec("UPDATE contas SET estado='connected' WHERE id=?", (cid,))
    c.put("/api/skill", json={"texto": "## Jeito\nFala uai, sô, trem bão.", "palavras_humano": ""})
    seg = db.um("SELECT segredo_webhook FROM contas WHERE id=?", (cid,))["segredo_webhook"]
    return c, gf, app, cid, seg


def msg(c, cid, seg, eid, texto, conversa=FONE):
    corpo = json.dumps({"event_id": eid, "type": "message.created", "conversation": {"external_id": conversa, "contact": {"name": "Fã"}},
                        "message": {"external_id": "m" + eid, "direction": "incoming", "text": texto}}).encode()
    assert c.post(f"/hooks/canal/{cid}", content=corpo, headers=assinar(seg, corpo)).status_code == 200


def test_landing_e_marca(fael):
    c, *_ = fael
    m = c.get("/api/marca").json()
    assert m["marca"]["tipo"] == "persona" and m["marca"]["arroba"] == "@faelgomeess"
    assert all(o["codigo"] != "fael" for o in c.get("/api/marca").json()["outras"])
    assert "Fael" in c.get("/").text
    p = c.get("/api/publico/persona").json()
    assert p["gratis"] == 5 and p["planos"][0]["checkout"] == "https://pay.cakto.com.br/fa"


def test_teste_gratis_depois_convite(fael):
    c, gf, app, cid, seg = fael
    c.post("/api/persona/ajustes", json={"teste_gratis": 2, "numero": "+55 62 9 9999-0000"})
    for i in range(4):
        msg(c, cid, seg, f"e{i}", f"oi {i}")
    textos = [e.get("text", "") for e in gf.enviadas]
    assert "IA oficial do Fael" in textos[0]              # boas-vindas transparente
    assert sum("tudo certo" in t for t in textos) == 2    # 2 respostas de teste
    assert sum("Seu teste acabou" in t for t in textos) == 1  # convite uma vez só (não repete em 12 h)
    assert "fala-fael.rangeltech.net/#planos" in textos[-1]
    assert c.get("/api/publico/persona").json()["whatsapp"].startswith("https://wa.me/5562999990000")


def test_cakto_libera_pelo_celular_sem_o_9(fael):
    c, gf, app, cid, seg = fael
    c.post("/api/persona/ajustes", json={"teste_gratis": 0})
    r = c.post("/api/cakto", json={"secret": "ck", "event": "purchase_approved",
                                   "data": {"id": "p1", "customer": {"email": "fa@x.com", "phone": "(62) 8888-0000"}, "product": {"id": "p-fa"}}}).json()
    assert r["liberado_fa"]
    msg(c, cid, seg, "a1", "e aí Fael")
    assert any("tudo certo" in e.get("text", "") for e in gf.enviadas)
    painel = c.get("/api/persona").json()
    assert painel["ativos"] == 1 and painel["fas"][0]["plano"] == "fa"
    c.post("/api/cakto", json={"secret": "ck", "event": "refund", "data": {"id": "p1", "customer": {"phone": "62988880000"}, "product": {"id": "p-fa"}}})
    assert c.get("/api/persona").json()["ativos"] == 0


def test_foto_gerada_vai_como_imagem(fael, monkeypatch):
    c, gf, app, cid, seg = fael
    b = io.BytesIO(); Image.new("RGB", (40, 40), "red").save(b, "JPEG")
    assert c.post("/api/persona/fotos", content=b.getvalue(), headers={"content-type": "image/jpeg"}).json()["ok"]
    jpg = b.getvalue()
    real = httpx.post

    def falso(url, **kw):
        if url.endswith("/images/generations"):
            assert kw["json"]["images"] and "curral" in kw["json"]["prompt"]
            import base64
            return httpx.Response(200, json={"data": [{"b64_json": base64.b64encode(jpg).decode()}]}, request=httpx.Request("POST", url))
        return real(url, **kw)
    monkeypatch.setattr(httpx, "post", falso)
    msg(c, cid, seg, "f1", "me manda uma foto sua")
    anexos = [a for e in gf.enviadas for a in e.get("attachments") or []]
    assert anexos and anexos[0]["kind"] == "image" and anexos[0]["url"].startswith("data:image/jpeg;base64,")


def test_painel_so_para_admin(fael):
    c, gf, app, *_ = fael
    c2 = TestClient(app, base_url="http://fala-fael.rangeltech.net")
    entrar(c2, "curioso@x.com")
    assert c2.get("/api/persona").status_code == 403
    assert c.post("/api/persona/fas", json={"telefone": "11 91234-5678", "plano": "vip", "dias": 30}).json()["ok"]
    assert c.get("/api/persona").json()["ativos"] == 1


def test_numeros_iguais_com_e_sem_9_e_55():
    assert pers.mesmo_numero("5562988880000", "6288880000")
    assert pers.mesmo_numero("62988880000", "+55 (62) 98888-0000")
    assert not pers.mesmo_numero("62988880000", "62988880001")
    assert pers.telefone("5562988880000@s.whatsapp.net") == "5562988880000"


def test_persona_tira_marcas_e_detecta_foto_e_voz():
    r = pers.conversar("manda áudio", [], "Fael", "", lambda m: "[VOZ] Opa, trem bão! [FOTO: selfie no rodeio]")
    assert r == {"texto": "Opa, trem bão!", "voz": True, "foto": "selfie no rodeio"}


def test_foto_do_fa_entra_na_foto_dos_dois(fael, monkeypatch):
    c, gf, app, cid, seg = fael
    c.post("/api/persona/fotos", content=_jpg(), headers={"content-type": "image/jpeg"})
    c.post("/api/persona/fas", json={"telefone": "62988880000", "plano": "vip", "dias": 30})
    pedidos = []
    real = httpx.post

    def falso(url, **kw):
        if url.endswith("/images/generations"):
            pedidos.append(kw["json"])
            import base64
            return httpx.Response(200, json={"data": [{"b64_json": base64.b64encode(_jpg()).decode()}]}, request=httpx.Request("POST", url))
        return real(url, **kw)
    monkeypatch.setattr(httpx, "post", falso)
    corpo = json.dumps({"event_id": "i1", "type": "message.created", "conversation": {"external_id": FONE, "contact": {"name": "Fã"}},
                        "message": {"external_id": "mi1", "direction": "incoming", "text": "",
                                    "attachments": [{"kind": "image", "mime": "image/jpeg", "name": "eu.jpg", "url": "mxc://img/1"}]}}).encode()
    assert c.post(f"/hooks/canal/{cid}", content=corpo, headers=assinar(seg, corpo)).status_code == 200
    db = app.state.db
    assert db.um("SELECT texto FROM mensagens WHERE externo='mi1'")["texto"].startswith("[o fã mandou uma foto dele]")
    msg(c, cid, seg, "i2", "faz uma foto de nós dois")
    assert pedidos and "LAST reference photo shows a fan" in pedidos[-1]["prompt"] and len(pedidos[-1]["images"]) == 2


def test_bolhas_quebra_em_mensagens_curtas():
    nl = chr(10)
    assert pers.bolhas("Kkkk já sim sô" + nl + nl + "Caí feio" + nl + "E você?") == ["Kkkk já sim sô", "Caí feio", "E você?"]
    assert len(pers.bolhas(nl.join(str(i) for i in range(9)))) == 3
    assert all(len(b) <= 110 for b in pers.bolhas("palavra " * 60))
