"""Atende AI (Whats, Insta, TikTok, Face): atendimento com IA nas redes, sessão 24/7 pelo gateway de canais."""
from __future__ import annotations

import datetime as dt
import hashlib
import re
import hmac
import json
import logging
import os
import secrets
import time
from pathlib import Path

import httpx
from starlette.concurrency import run_in_threadpool
from fastapi import BackgroundTasks, FastAPI, HTTPException, Request
from fastapi.responses import FileResponse, HTMLResponse, JSONResponse, RedirectResponse, Response
from fastapi.staticfiles import StaticFiles

from app import atendente, auth, mailer, senha_rotas
from app import voz as voz_mod
from app.canais import CanalErro, Gateway, assinatura_ok
from app.config import Config, carregar
from app.db import Banco, agora
from app.marcas import MARCAS, PLANOS, por_host, publica

logging.basicConfig(level=logging.INFO, format="%(asctime)s %(levelname)s %(name)s %(message)s")
log = logging.getLogger("atendeai")
ESTATICO = Path(__file__).resolve().parent.parent / "static"
COOKIE = "atendeai_s"
VERSAO_INICIO = str(int(time.time()))
ESTADOS_PT = {"pending_auth": "Aguardando login", "awaiting_2fa": "Aguardando código", "awaiting_challenge": "Aguardando confirmação",
              "connected": "Conectada", "degraded": "Instável", "reauth_required": "Precisa entrar de novo",
              "disconnected": "Desconectada", "revoked": "Removida"}
ERROS_PT = {"wrong_password": "Não deu para entrar. Confira usuário e senha; se estiverem certos, tente de novo em alguns minutos.", "wrong_code": "Código errado.", "account_locked": "A rede bloqueou a conta por segurança. Entre pelo app e libere.",
            "checkpoint_required": "A rede pediu uma confirmação no app. Confirme lá e tente de novo.", "timeout": "Demorou demais. Tente de novo.",
            "too_many_attempts": "Muitas tentativas. Espere alguns minutos.", "provider_unavailable": "A rede não respondeu agora. Tente de novo em instantes.",
            "unsupported_step": "Essa etapa ainda não é suportada.", "consent_required": "Aceite os termos para conectar."}


def criar_app(cfg: Config | None = None, gateway: Gateway | None = None, llm=None, sincrono: bool = False, voz: voz_mod.Voz | None = None) -> FastAPI:
    cfg = cfg or carregar()
    Path(cfg.dados).mkdir(parents=True, exist_ok=True)
    db = Banco(os.path.join(cfg.dados, "atendeai.db"))
    AUDIOS = Path(cfg.dados) / "audios"   # respostas em voz e áudios dos clientes, para tocar no painel
    AUDIOS.mkdir(parents=True, exist_ok=True)
    gw = gateway or Gateway(cfg.canais_url, cfg.canais_token)
    vz = voz or voz_mod.Voz(cfg.voz_base, cfg.voz_token)
    app = FastAPI(title="Atende AI", docs_url=None, redoc_url=None, openapi_url=None)
    app.state.cfg, app.state.db, app.state.gw = cfg, db, gw

    def chamar_llm(mensagens: list[dict]) -> str:
        if llm:
            return llm(mensagens)
        r = httpx.post(cfg.llm_base + "/chat/completions", headers={"Authorization": f"Bearer {cfg.llm_key}"}, timeout=120,
                       json={"model": cfg.llm_modelo, "messages": mensagens, "temperature": 0.4, "max_tokens": 700})
        r.raise_for_status()
        return r.json()["choices"][0]["message"]["content"] or ""

    if cfg.demo_email:  # conta de demonstração: Top ativo nas 4 marcas
        u = auth.usuario_por_email(db, cfg.demo_email.lower())
        for m in MARCAS:
            db.exec("INSERT INTO assinaturas(usuario,marca,plano,ativo_ate) VALUES(?,?,?,?) ON CONFLICT(usuario,marca) DO UPDATE SET plano=excluded.plano, ativo_ate=excluded.ativo_ate",
                    (u["id"], m, "turbo", agora() + 3650 * 86400))

    # ------------------------------------------------ helpers
    def usuario(request: Request, obrigatorio: bool = True) -> dict | None:
        u = auth.usuario_da_sessao(db, cfg.segredo_sessao, request.cookies.get(COOKIE))
        if not u and obrigatorio:
            raise HTTPException(401, "entre na sua conta")
        return u

    def marca_de(request: Request) -> str:
        q = request.query_params.get("marca")
        return q if q in MARCAS else por_host(request.headers.get("host", ""))

    def conta_gw(u: dict) -> int:
        return cfg.conta_base + int(u["id"])

    def assinatura(u: dict, marca: str) -> dict | None:
        a = db.um("SELECT * FROM assinaturas WHERE usuario=? AND marca=?", (u["id"], marca))
        return a if a and a["ativo_ate"] > agora() else None

    def inicio_mes() -> float:
        h = dt.datetime.now(dt.timezone.utc)
        return dt.datetime(h.year, h.month, 1, tzinfo=dt.timezone.utc).timestamp()

    def usadas_mes(uid: int, marca: str) -> int:
        return db.um("""SELECT COUNT(*) n FROM mensagens m JOIN conversas c ON c.id=m.conversa JOIN contas k ON k.id=c.conta
                        WHERE k.usuario=? AND k.marca=? AND m.direcao='ia' AND m.criado>=?""", (uid, marca, inicio_mes()))["n"]

    def resumo(u: dict, marca: str) -> dict:
        a = assinatura(u, marca)
        pl = PLANOS.get(a["plano"]) if a else None
        contas = db.um("SELECT COUNT(*) n FROM contas WHERE usuario=? AND marca=? AND estado!='revoked' AND ja_conectou=1", (u["id"], marca))["n"]
        return {"email": u["email"], "marca": publica(marca), "assinante": bool(a), "plano": a["plano"] if a else None,
                "ativo_ate": a["ativo_ate"] if a else 0, "limite_contas": pl["contas"] if pl else 0, "contas": contas,
                "limite_msgs": pl["msgs_mes"] if pl else 0, "usadas": usadas_mes(u["id"], marca), "planos": planos_publicos(marca),
                "tem_senha": bool(u.get("senha_hash"))}

    def planos_publicos(marca: str) -> list[dict]:
        return [{"codigo": k, **v, "checkout": cfg.checkouts.get(f"{marca}:{k}") or "", "lancamento_ate": cfg.lancamento_ate} for k, v in PLANOS.items()]

    def minha_conta(u: dict, cid: str) -> dict:
        k = db.um("SELECT * FROM contas WHERE id=? AND usuario=?", (cid, u["id"]))
        if not k:
            raise HTTPException(404, "conta não encontrada")
        return k

    def vista_conta(k: dict, view: dict | None = None) -> dict:
        out = {"id": k["id"], "marca": k["marca"], "provider": k["provider"], "estado": k["estado"], "estado_pt": ESTADOS_PT.get(k["estado"], k["estado"]),
               "rotulo": k["rotulo"], "ia_ligada": bool(k["ia_ligada"]), "criado": k["criado"], "ja_conectou": bool(k.get("ja_conectou")),
               "modo_teste": bool(k.get("so_liberadas")), "voz_modo": k.get("voz_modo") or "desligado", "voz_pronta": bool(k.get("voz_id"))}
        if view:
            passo = view.get("step") or {}
            if passo:
                out["passo"] = {"id": passo.get("step_id"), "tipo": passo.get("kind"), "campos": passo.get("fields") or [],
                                "qr": (passo.get("qr") or {}).get("data"), "codigo_pareamento": passo.get("pairing_code"),
                                "erro": ERROS_PT.get(passo.get("error_code") or "", passo.get("error_code")), "espera_s": (passo.get("wait") or {}).get("poll_after_s"),
                                # captcha e afins: a imagem que a própria rede mostra (não é segredo) e o texto dela
                                "imagens": [f"data:{a.get('mime') or 'image/png'};base64,{a['data']}" for a in (passo.get("attachments") or [])
                                            if a.get("kind") == "image" and a.get("data")][:2],
                                "instrucoes": (passo.get("instructions") or "")[:400]}
        return out

    def atualizar_de_view(k: dict, view: dict) -> dict:
        con = view.get("connection") or view
        estado = con.get("state") or k["estado"]
        rotulo = con.get("external_label") or k["rotulo"]
        if estado != k["estado"] or rotulo != k["rotulo"]:
            ja = 1 if estado == "connected" else int(k.get("ja_conectou") or 0)
            db.exec("UPDATE contas SET estado=?, rotulo=?, ja_conectou=?, atualizado=? WHERE id=?", (estado, rotulo or "", ja, agora(), k["id"]))
            k = {**k, "estado": estado, "rotulo": rotulo or "", "ja_conectou": ja}
        return k

    def apagar_conta(u: dict, k: dict) -> None:
        """Encerra no gateway (sem travar se já sumiu lá) e apaga conta, conversas e mensagens daqui."""
        for f in (lambda: gw.cancelar(conta_gw(u), k["id"]), lambda: gw.desconectar(conta_gw(u), k["id"], str(u["id"]))):
            try:
                f()
            except Exception as e:  # noqa: BLE001
                log.info("encerrar %s no gateway: %s", k["id"], e)
        for c in db.todos("SELECT id FROM conversas WHERE conta=?", (k["id"],)):
            db.exec("DELETE FROM mensagens WHERE conversa=?", (c["id"],))
        db.exec("DELETE FROM conversas WHERE conta=?", (k["id"],))
        db.exec("DELETE FROM contas WHERE id=?", (k["id"],))

    def limpar_tentativas(u: dict, marca: str) -> None:
        """Tentativa que nunca conectou não fica guardada: some ao começar outra."""
        for k in db.todos("SELECT * FROM contas WHERE usuario=? AND marca=? AND ja_conectou=0", (u["id"], marca)):
            apagar_conta(u, k)

    def erro_canal(e: CanalErro):
        raise HTTPException(e.status if 400 <= e.status < 600 else 502, ERROS_PT.get(e.codigo, "A conexão não respondeu agora. Tente de novo."))

    @app.exception_handler(json.JSONDecodeError)
    @app.exception_handler(UnicodeDecodeError)
    async def corpo_invalido(request: Request, exc: Exception):
        return JSONResponse({"detail": "corpo inválido (envie JSON em UTF-8)"}, status_code=400)

    @app.get("/health")
    def health():
        return {"ok": True}

    # ------------------------------------------------ login
    def _login(u: dict) -> JSONResponse:
        token = auth.criar_sessao(db, cfg.segredo_sessao, u["id"])
        resp = JSONResponse({"ok": True})
        resp.set_cookie(COOKIE, token, max_age=auth.SESSAO_S, httponly=True, secure=not cfg.dev, samesite="lax", path="/")
        return resp

    @app.post("/api/entrar/codigo")
    async def pedir_codigo(request: Request):
        b = await request.json()
        email = auth.normalizar_email(b.get("email"))
        if not email:
            raise HTTPException(422, "e-mail inválido")
        cod, motivo = auth.novo_codigo(db, cfg.segredo_sessao, email)
        if motivo == "espere":
            raise HTTPException(429, "acabamos de mandar um código; espere alguns segundos")
        out = {"ok": True, "enviado": mailer.codigo(cfg, email, cod)}
        if cfg.dev:
            out["codigo_dev"] = cod
        return out

    @app.post("/api/entrar")
    async def entrar(request: Request):
        b = await request.json()
        email = auth.normalizar_email(b.get("email"))
        if not email:
            raise HTTPException(422, "e-mail inválido")
        r = auth.conferir_codigo(db, cfg.segredo_sessao, email, str(b.get("codigo") or ""))
        if r != "ok":
            raise HTTPException(400, {"invalido": "código errado", "expirado": "código vencido; peça outro", "tentativas": "muitas tentativas; peça outro código"}[r])
        return _login(auth.usuario_por_email(db, email))

    senha_rotas.registrar(app, db, cfg, mailer, _login, usuario)

    @app.post("/api/sair")
    def sair(request: Request):
        auth.encerrar_sessao(db, cfg.segredo_sessao, request.cookies.get(COOKIE))
        resp = JSONResponse({"ok": True})
        resp.delete_cookie(COOKIE, path="/")
        return resp

    @app.get("/api/marca")
    def marca(request: Request):
        m = marca_de(request)
        return {"marca": publica(m), "planos": planos_publicos(m), "outras": [publica(k) | {"url": "https://" + MARCAS[k]["hosts"][0]} for k in MARCAS if k != m]}

    @app.get("/api/conta")
    def conta(request: Request):
        return resumo(usuario(request), marca_de(request))

    # ------------------------------------------------ contas conectadas
    @app.get("/api/contas")
    def contas(request: Request):
        u = usuario(request)
        return {"contas": [vista_conta(k) for k in db.todos("SELECT * FROM contas WHERE usuario=? AND marca=? AND estado!='revoked' AND ja_conectou=1 ORDER BY criado", (u["id"], marca_de(request)))]}

    @app.post("/api/contas")
    async def conectar(request: Request):
        u = usuario(request)
        m = marca_de(request)
        b = await request.json() if (request.headers.get("content-type") or "").startswith("application/json") else {}
        r = resumo(u, m)
        if not r["assinante"]:
            raise HTTPException(402, "escolha um plano para conectar sua conta")
        if r["contas"] >= r["limite_contas"]:
            raise HTTPException(402, f"seu plano permite {r['limite_contas']} conta(s) conectada(s); suba de plano para conectar outra")
        if not b.get("aceite"):
            raise HTTPException(422, "aceite os termos de conexão para continuar")
        # QR/código de pareamento só existem no WhatsApp; Instagram e Facebook entram por usuário e senha (fluxo padrão do gateway)
        limpar_tentativas(u, m)
        fluxo = b.get("fluxo") if MARCAS[m]["provider"] == "whatsapp" and b.get("fluxo") in ("qr", "phone") else None
        try:
            view = gw.conectar(conta_gw(u), MARCAS[m]["provider"], str(u["id"]), fluxo)
        except CanalErro as e:
            erro_canal(e)
        con = view.get("connection") or view
        segredo = secrets.token_urlsafe(32)
        db.exec("INSERT INTO contas(id,usuario,marca,provider,estado,rotulo,segredo_webhook,criado,atualizado) VALUES(?,?,?,?,?,?,?,?,?)",
                (con["id"], u["id"], m, MARCAS[m]["provider"], con.get("state") or "pending_auth", con.get("external_label") or "", segredo, agora(), agora()))
        try:
            gw.entrega(conta_gw(u), con["id"], f"{cfg.webhook_base}/hooks/canal/{con['id']}", segredo)
        except CanalErro as e:
            log.warning("entrega nao registrada para %s: %s", con["id"], e)
        return vista_conta(db.um("SELECT * FROM contas WHERE id=?", (con["id"],)), view)

    @app.get("/api/contas/{cid}")
    def conta_status(cid: str, request: Request):
        u = usuario(request)
        k = minha_conta(u, cid)
        try:
            view = gw.status(conta_gw(u), cid)
        except CanalErro as e:
            erro_canal(e)
        return vista_conta(atualizar_de_view(k, view), view)

    @app.delete("/api/contas/{cid}")
    def conta_excluir(cid: str, request: Request):
        u = usuario(request)
        apagar_conta(u, minha_conta(u, cid))
        return {"ok": True}

    @app.post("/api/contas/{cid}/passo")
    async def conta_passo(cid: str, request: Request):
        u = usuario(request)
        k = minha_conta(u, cid)
        b = await request.json()
        dados = {str(x): str(y)[:200] for x, y in (b.get("dados") or {}).items()}
        try:
            view = gw.passo(conta_gw(u), cid, str(b.get("passo") or ""), str(b.get("tipo") or ""), dados)
        except CanalErro as e:
            erro_canal(e)
        return vista_conta(atualizar_de_view(k, view), view)

    @app.post("/api/contas/{cid}/{acao}")
    def conta_acao(cid: str, acao: str, request: Request):
        u = usuario(request)
        k = minha_conta(u, cid)
        try:
            if acao == "cancelar":
                view = gw.cancelar(conta_gw(u), cid)
            elif acao == "desconectar":
                view = gw.desconectar(conta_gw(u), cid, str(u["id"]))
            elif acao == "reconectar":
                view = gw.reconectar(conta_gw(u), cid, str(u["id"]))
            elif acao.startswith("voz_"):  # voz_desligado | voz_quando_audio | voz_sempre
                modo = acao[4:]
                if modo not in ("desligado", "quando_audio", "sempre"):
                    raise HTTPException(404, "modo de voz desconhecido")
                db.exec("UPDATE contas SET voz_modo=? WHERE id=?", (modo, cid))
                return vista_conta(db.um("SELECT * FROM contas WHERE id=?", (cid,)))
            elif acao in ("ligar_teste", "desligar_teste"):
                db.exec("UPDATE contas SET so_liberadas=? WHERE id=?", (1 if acao == "ligar_teste" else 0, cid))
                return vista_conta(db.um("SELECT * FROM contas WHERE id=?", (cid,)))
            elif acao in ("ligar_ia", "desligar_ia"):
                db.exec("UPDATE contas SET ia_ligada=? WHERE id=?", (1 if acao == "ligar_ia" else 0, cid))
                return vista_conta(db.um("SELECT * FROM contas WHERE id=?", (cid,)))
            else:
                raise HTTPException(404, "ação desconhecida")
        except CanalErro as e:
            erro_canal(e)
        return vista_conta(atualizar_de_view(k, view), view)

    # ------------------------------------------------ webhook do gateway (mensagens e estado)
    def skill_de(uid: int, marca: str) -> dict:
        """Regras do atendente. Cada seção '## Título' é uma skill; as desligadas no painel não vão para a IA."""
        s = db.um("SELECT * FROM skills WHERE usuario=? AND marca=?", (uid, marca)) or {"texto": "", "horario": "", "palavras_humano": "atendente,humano,pessoa,reclamação", "fora_horario": ""}
        off = set(json.loads(s.get("desligadas") or "[]"))
        if off and s.get("texto"):
            partes = re.split(r"(?m)^(?=## )", s["texto"])
            s = {**s, "texto": "".join(p for p in partes if not (p.startswith("## ") and p[3:].split("\n", 1)[0].strip() in off))}
        return s

    def responder(conversa_id: int, texto: str, veio_audio: bool = False) -> None:
        c = db.um("SELECT c.*, k.usuario, k.marca, k.ia_ligada, k.estado, k.so_liberadas, k.voz_modo, k.voz_id FROM conversas c JOIN contas k ON k.id=c.conta WHERE c.id=?", (conversa_id,))
        if not c or not c["ia_ligada"] or c["estado"] != "connected" and not cfg.dev:
            return
        if c["so_liberadas"] and not c["liberada"]:
            return  # modo teste: só as conversas que o dono liberou
        u = db.um("SELECT * FROM usuarios WHERE id=?", (c["usuario"],))
        r = resumo(u, c["marca"])
        if not r["assinante"] or r["usadas"] >= r["limite_msgs"]:
            return  # sem plano ou limite do mês: fica para o humano
        hist = db.todos("SELECT direcao, texto FROM mensagens WHERE conversa=? ORDER BY criado DESC, id DESC LIMIT 12", (conversa_id,))[::-1]
        d = atendente.decidir(texto, hist, skill_de(c["usuario"], c["marca"]), MARCAS[c["marca"]]["rede"], c["modo"], c["fora_avisado"], agora(), chamar_llm)
        if d["acao"] == "humano":
            db.exec("UPDATE conversas SET modo='humano' WHERE id=?", (conversa_id,))
        if d["acao"] == "fora_horario":
            db.exec("UPDATE conversas SET fora_avisado=? WHERE id=?", (agora(), conversa_id))
        if not d["texto"]:
            return
        chave = hashlib.sha256(f"{conversa_id}:{texto}:{time.time_ns()}".encode()).hexdigest()[:32]
        anexos, registro, audio_nome = None, d["texto"], ""
        if vz.ligada and (d.get("voz") or c["voz_modo"] == "sempre" or (c["voz_modo"] == "quando_audio" and veio_audio)):
            try:  # nota de voz na voz do dono (rt-voz, GPU própria); se falhar, vai em texto
                ogg, ms = vz.falar(d["texto"], c["voz_id"] or voz_do({"id": c["usuario"]}))
                anexos, registro = [voz_mod.anexo_voz(ogg, ms)], "[áudio] " + d["texto"]
                audio_nome = chave + ".ogg"
                (AUDIOS / audio_nome).write_bytes(ogg)
            except Exception as e:  # noqa: BLE001
                log.warning("voz falhou na conversa %s (vai texto): %s", conversa_id, e)
        try:
            gw.enviar(cfg.conta_base + int(c["usuario"]), c["conta"], c["externo"], "" if anexos else d["texto"], chave, anexos)
        except CanalErro as e:
            log.warning("envio falhou na conversa %s: %s", conversa_id, e)
            return
        db.exec("INSERT INTO mensagens(conversa,externo,direcao,texto,criado,audio) VALUES(?,?,?,?,?,?)", (conversa_id, "ia:" + chave, "ia", registro, agora(), audio_nome))

    @app.post("/hooks/canal/{cid}")
    async def webhook_canal(cid: str, request: Request, tarefas: BackgroundTasks):
        k = db.um("SELECT * FROM contas WHERE id=?", (cid,))
        corpo = await request.body()
        if not k or not assinatura_ok(k["segredo_webhook"], request.headers.get("x-luar-timestamp", ""), request.headers.get("x-luar-signature", ""), corpo):
            raise HTTPException(401, "assinatura")
        ev = json.loads(corpo)
        eid = str(ev.get("event_id") or request.headers.get("x-luar-event-id") or "")
        if eid:
            if db.um("SELECT 1 FROM eventos_canal WHERE id=?", (eid,)):
                return {"ok": True, "repetido": True}
            db.exec("INSERT INTO eventos_canal(id,recebido) VALUES(?,?)", (eid, agora()))
        tipo = ev.get("type")
        if tipo == "connection.state":
            st = (ev.get("state") or {}).get("state")
            if st:
                db.exec("UPDATE contas SET estado=?, atualizado=? WHERE id=?", (st, agora(), cid))
                if st in ("reauth_required", "disconnected", "degraded"):
                    u = db.um("SELECT email FROM usuarios WHERE id=?", (k["usuario"],))
                    mailer.enviar(cfg, u["email"], f"{MARCAS[k['marca']]['nome']}: sua conta precisa de atenção",
                                  f"A conta conectada ficou: {ESTADOS_PT.get(st, st)}. Entre no painel e reconecte.",
                                  f"<p>A conta conectada ficou <b>{ESTADOS_PT.get(st, st)}</b>.</p><p><a href='{cfg.base_url}/painel'>Abrir o painel</a></p>")
            return {"ok": True}
        if tipo != "message.created":
            return {"ok": True, "ignorado": tipo}
        conv, msg = ev.get("conversation") or {}, ev.get("message") or {}
        externo = str(conv.get("external_id") or "")
        texto = str(msg.get("text") or "").strip()
        if not externo:
            return {"ok": True, "ignorado": "sem conversa"}
        contato = (conv.get("contact") or {}).get("name") or (conv.get("contact") or {}).get("username") or ""
        db.exec("INSERT INTO conversas(conta,externo,contato,ultima) VALUES(?,?,?,?) ON CONFLICT(conta,externo) DO UPDATE SET ultima=excluded.ultima, contato=CASE WHEN excluded.contato!='' THEN excluded.contato ELSE contato END",
                (cid, externo, contato, agora()))
        c = db.um("SELECT * FROM conversas WHERE conta=? AND externo=?", (cid, externo))
        direcao = "eco" if msg.get("direction") == "outgoing_echo" else "entrada"
        if msg.get("attachments") and not texto:
            texto = "[anexo: " + ", ".join(a.get("kind", "arquivo") for a in msg["attachments"]) + "]"
        try:
            db.exec("INSERT INTO mensagens(conversa,externo,direcao,texto,criado) VALUES(?,?,?,?,?)", (c["id"], str(msg.get("external_id") or eid), direcao, texto[:4000], agora()))
        except Exception:  # noqa: BLE001  (mensagem repetida)
            return {"ok": True, "repetido": True}
        if direcao == "entrada":
            db.exec("UPDATE conversas SET nao_lidas=nao_lidas+1 WHERE id=?", (c["id"],))
            audio = next((a for a in msg.get("attachments") or [] if a.get("kind") == "audio" and a.get("url")), None)
            ext = str(msg.get("external_id") or eid)
            if sincrono:
                processar_entrada(k, c["id"], ext, texto, audio)
            else:
                tarefas.add_task(processar_entrada, k, c["id"], ext, texto, audio)
        return {"ok": True}

    def processar_entrada(k: dict, conversa_id: int, ext: str, texto: str, audio: dict | None) -> None:
        """Áudio do cliente vira texto (Whisper na GPU própria) ou é reconhecido como música antes da IA decidir."""
        if audio and vz.ligada:
            try:
                dados = gw.midia(cfg.conta_base + int(k["usuario"]), k["id"], audio["url"])
                nome_a = hashlib.sha256(f"{conversa_id}:{ext}".encode()).hexdigest()[:32] + ".ogg"
                (AUDIOS / nome_a).write_bytes(dados)
                db.exec("UPDATE mensagens SET audio=? WHERE conversa=? AND externo=?", (nome_a, conversa_id, ext))
                texto = voz_mod.texto_da_entrada(vz.ouvir(dados, audio.get("name") or "audio.ogg"))
                db.exec("UPDATE mensagens SET texto=? WHERE conversa=? AND externo=?", (texto[:4000], conversa_id, ext))
            except Exception as e:  # noqa: BLE001
                log.warning("não consegui ouvir o áudio da conversa %s: %s", conversa_id, e)
        responder(conversa_id, texto, veio_audio=bool(audio))

    # ------------------------------------------------ conversas (painel)
    @app.get("/api/conversas")
    def conversas(request: Request):
        u = usuario(request)
        return {"conversas": db.todos("""SELECT c.id, c.contato, c.modo, c.ultima, c.nao_lidas, c.liberada, k.so_liberadas AS modo_teste, k.rotulo AS conta,
                                         (SELECT texto FROM mensagens m WHERE m.conversa=c.id ORDER BY criado DESC, id DESC LIMIT 1) AS previa
                                    FROM conversas c JOIN contas k ON k.id=c.conta WHERE k.usuario=? AND k.marca=? ORDER BY c.ultima DESC LIMIT 200""",
                                      (u["id"], marca_de(request)))}

    def minha_conversa(u: dict, conv: int) -> dict:
        c = db.um("SELECT c.*, k.usuario, k.so_liberadas FROM conversas c JOIN contas k ON k.id=c.conta WHERE c.id=? AND k.usuario=?", (conv, u["id"]))
        if not c:
            raise HTTPException(404, "conversa não encontrada")
        return c

    @app.get("/api/conversas/{conv}")
    def conversa(conv: int, request: Request):
        u = usuario(request)
        c = minha_conversa(u, conv)
        db.exec("UPDATE conversas SET nao_lidas=0 WHERE id=?", (conv,))
        return {"id": c["id"], "contato": c["contato"], "modo": c["modo"], "modo_teste": bool(c["so_liberadas"]), "liberada": bool(c["liberada"]),
                "mensagens": db.todos("SELECT direcao, texto, criado, audio FROM mensagens WHERE conversa=? ORDER BY criado, id LIMIT 500", (conv,))}

    @app.get("/api/audios/{nome}")
    def tocar_audio(nome: str, request: Request):
        u = usuario(request)
        if not re.fullmatch(r"[0-9a-f]{32}\.ogg", nome):
            raise HTTPException(404, "áudio não encontrado")
        dono = db.um("""SELECT 1 FROM mensagens m JOIN conversas c ON c.id=m.conversa JOIN contas k ON k.id=c.conta
                        WHERE m.audio=? AND k.usuario=?""", (nome, u["id"]))
        if not dono or not (AUDIOS / nome).exists():
            raise HTTPException(404, "áudio não encontrado")
        cab = (AUDIOS / nome).open("rb").read(12)
        tipo = "audio/mp4" if cab[4:8] == b"ftyp" else "audio/mpeg" if cab[:3] == b"ID3" or cab[:2] == bytes([0xFF, 0xFB]) else "audio/webm" if cab[:4] == bytes([0x1A, 0x45, 0xDF, 0xA3]) else "audio/ogg"
        return FileResponse(AUDIOS / nome, media_type=tipo)

    # ------------------------------------------------ minha voz (clonagem, plano Voz, só WhatsApp)
    ESTADO_VOZ: dict = {}  # cache de 60 s do estado da voz (o rt-voz na GPU demora para responder)

    def voz_do(u: dict) -> str:
        k = db.um("SELECT voz_id FROM contas WHERE usuario=? AND voz_id!='' LIMIT 1", (u["id"],))
        return (k or {}).get("voz_id") or f"u{u['id']}"

    @app.get("/api/voz")
    def minha_voz(request: Request):
        u = usuario(request)
        vid = voz_do(u)
        guardado = ESTADO_VOZ.get(vid)
        if guardado and time.time() - guardado[0] < 60:
            e = guardado[1]
        else:
            try:
                e = vz.estado(vid) if vz.ligada else {}
                ESTADO_VOZ[vid] = (time.time(), e)
            except Exception:  # noqa: BLE001
                e = {"erro": "o servidor de voz não respondeu agora"}
        if e.get("pronta"):
            db.exec("UPDATE contas SET voz_id=? WHERE usuario=? AND marca IN ('whats','insta') AND voz_id=''", (vid, u["id"]))
        contas = db.todos("SELECT id, rotulo, marca, voz_modo FROM contas WHERE usuario=? AND marca IN ('whats','insta') AND ja_conectou=1", (u["id"],))
        return {"ligada": vz.ligada, "voz": vid, "estado": e, "contas": contas, "minimo_minutos": 10}

    @app.post("/api/voz/amostras")
    async def voz_amostra(request: Request):
        u = usuario(request)
        corpo = await request.body()
        if not corpo or len(corpo) > 60 * 1024 * 1024:
            raise HTTPException(422, "áudio vazio ou grande demais (até 60 MB)")
        tipo = (request.headers.get("content-type") or "audio/webm").split(";")[0]
        nome = "amostra." + {"audio/ogg": "ogg", "audio/mpeg": "mp3", "audio/wav": "wav", "audio/x-wav": "wav", "audio/mp4": "m4a", "audio/x-m4a": "m4a"}.get(tipo, "webm")
        try:
            ESTADO_VOZ.pop(voz_do(u), None)
            return await run_in_threadpool(vz.amostra, voz_do(u), corpo, nome)
        except Exception as e:  # noqa: BLE001
            log.warning("amostra de voz falhou: %s", e)
            raise HTTPException(502, "não consegui guardar esse áudio agora; tente de novo")

    @app.post("/api/voz/treinar")
    def voz_treinar(request: Request):
        u = usuario(request)
        try:
            ESTADO_VOZ.pop(voz_do(u), None)
            return vz.treinar(voz_do(u))
        except Exception as e:  # noqa: BLE001
            raise HTTPException(502, f"o treino não começou: {str(e)[:120]}")

    @app.post("/api/voz/exemplo")
    async def voz_exemplo(request: Request):
        u = usuario(request)
        b = await request.json()
        texto = str(b.get("texto") or "Oi! Tudo bem? Aqui é do atendimento. Como posso te ajudar hoje?")[:400]
        try:
            ogg, _ = await run_in_threadpool(vz.falar, texto, voz_do(u))
        except Exception:  # noqa: BLE001
            raise HTTPException(502, "a voz ainda não está pronta ou o servidor não respondeu")
        return Response(content=ogg, media_type="audio/ogg")

    def para_nota_de_voz(dados: bytes) -> tuple[bytes, int]:
        """Qualquer áudio do navegador (webm/opus, mp4...) vira ogg/opus mono, o formato de nota de voz."""
        import subprocess
        import tempfile
        with tempfile.TemporaryDirectory() as d:
            ent, sai = os.path.join(d, "ent"), os.path.join(d, "sai.ogg")
            open(ent, "wb").write(dados)
            subprocess.run(["ffmpeg", "-loglevel", "error", "-y", "-i", ent, "-ac", "1", "-ar", "48000", "-c:a", "libopus", "-b:a", "32k", sai], check=True, timeout=120)
            dur = subprocess.run(["ffprobe", "-v", "error", "-show_entries", "format=duration", "-of", "csv=p=0", sai], capture_output=True, text=True).stdout.strip()
            return open(sai, "rb").read(), int(float(dur or 0) * 1000)

    def enviar_voz(u: dict, conv: int, ogg: bytes, ms: int, registro: str) -> dict:
        c = minha_conversa(u, conv)
        chave = hashlib.sha256(f"{conv}:voz:{time.time_ns()}".encode()).hexdigest()[:32]
        try:
            gw.enviar(conta_gw(u), c["conta"], c["externo"], "", chave, [voz_mod.anexo_voz(ogg, ms)])
        except CanalErro as e:
            raise HTTPException(502, f"não consegui enviar o áudio: {e}")
        (AUDIOS / (chave + ".ogg")).write_bytes(ogg)
        db.exec("UPDATE conversas SET modo='humano', ultima=? WHERE id=?", (agora(), conv))
        db.exec("INSERT INTO mensagens(conversa,externo,direcao,texto,criado,audio) VALUES(?,?,?,?,?,?)",
                (conv, "humano:" + chave, "humano", registro, agora(), chave + ".ogg"))
        return {"ok": True}

    @app.post("/api/conversas/{conv}/audio")
    async def responder_gravado(conv: int, request: Request):
        """O dono grava no painel e manda como nota de voz (a IA para nesta conversa)."""
        u = usuario(request)
        dados = await request.body()
        if not dados or len(dados) > 25 * 1024 * 1024:
            raise HTTPException(422, "áudio vazio ou grande demais")
        try:
            ogg, ms = await run_in_threadpool(para_nota_de_voz, dados)
        except Exception as e:  # noqa: BLE001
            log.warning("conversão de áudio falhou: %s", e)
            raise HTTPException(422, "não consegui ler esse áudio")
        return await run_in_threadpool(enviar_voz, u, conv, ogg, ms, "[áudio gravado por você]")

    @app.post("/api/conversas/{conv}/minha-voz")
    async def responder_na_voz(conv: int, request: Request):
        """O dono digita e o texto vai como nota de voz na voz clonada dele."""
        u = usuario(request)
        texto = str((await request.json()).get("texto") or "").strip()[:800]
        if not texto:
            raise HTTPException(422, "escreva o que quer falar")
        try:
            ogg, ms = await run_in_threadpool(vz.falar, texto, voz_do(u))
        except Exception:  # noqa: BLE001
            raise HTTPException(502, "a sua voz ainda não está pronta ou o servidor de voz não respondeu")
        return await run_in_threadpool(enviar_voz, u, conv, ogg, ms, "[áudio na sua voz] " + texto)

    @app.post("/api/conversas/{conv}/{acao}")
    async def conversa_acao(conv: int, acao: str, request: Request):
        u = usuario(request)
        c = minha_conversa(u, conv)
        if acao in ("assumir", "devolver"):
            db.exec("UPDATE conversas SET modo=? WHERE id=?", ("humano" if acao == "assumir" else "ia", conv))
            return {"ok": True, "modo": "humano" if acao == "assumir" else "ia"}
        if acao in ("liberar", "bloquear"):
            db.exec("UPDATE conversas SET liberada=? WHERE id=?", (1 if acao == "liberar" else 0, conv))
            return {"ok": True, "liberada": acao == "liberar"}
        if acao != "enviar":
            raise HTTPException(404, "ação desconhecida")
        texto = str((await request.json()).get("texto") or "").strip()[:1500]
        if not texto:
            raise HTTPException(422, "escreva a mensagem")
        chave = secrets.token_hex(16)
        try:
            gw.enviar(conta_gw(u), c["conta"], c["externo"], texto, chave)
        except CanalErro as e:
            erro_canal(e)
        db.exec("UPDATE conversas SET modo='humano', ultima=? WHERE id=?", (agora(), conv))
        db.exec("INSERT INTO mensagens(conversa,externo,direcao,texto,criado) VALUES(?,?,?,?,?)", (conv, "humano:" + chave, "humano", texto, agora()))
        return {"ok": True}

    # ------------------------------------------------ regras (skill), construtor por conversa, teste, versões
    def salvar_versao(uid: int, m: str, texto: str, autor: str) -> None:
        ult = db.um("SELECT texto FROM skill_versoes WHERE usuario=? AND marca=? ORDER BY id DESC LIMIT 1", (uid, m))
        if texto.strip() and (not ult or ult["texto"] != texto):
            db.exec("INSERT INTO skill_versoes(usuario,marca,texto,autor,criado) VALUES(?,?,?,?,?)", (uid, m, texto, autor, agora()))

    def garantir_skill(uid: int, m: str) -> None:
        db.exec("INSERT OR IGNORE INTO skills(usuario,marca) VALUES(?,?)", (uid, m))

    @app.get("/api/skill")
    def skill_get(request: Request):
        u = usuario(request)
        m = marca_de(request)
        s = skill_de(u["id"], m)
        s = db.um("SELECT * FROM skills WHERE usuario=? AND marca=?", (u["id"], m)) or s
        return {"texto": s["texto"], "desligadas": json.loads(s.get("desligadas") or "[]"), "horario": json.loads(s["horario"]) if s.get("horario") else None, "palavras_humano": s["palavras_humano"],
                "fora_horario": s["fora_horario"], "campos": json.loads(s.get("campos") or "{}"),
                "historico": db.todos("SELECT papel, texto FROM skill_chat WHERE usuario=? AND marca=? ORDER BY id", (u["id"], m)),
                "versoes": db.todos("SELECT id, autor, criado, substr(texto,1,160) AS inicio FROM skill_versoes WHERE usuario=? AND marca=? ORDER BY id DESC LIMIT 30", (u["id"], m))}

    @app.put("/api/skill")
    async def skill_put(request: Request):
        u = usuario(request)
        m = marca_de(request)
        b = await request.json()
        garantir_skill(u["id"], m)
        horario = b.get("horario")
        if horario:
            if not isinstance(horario, dict) or not all(isinstance(horario.get(x, ""), str) for x in ("inicio", "fim")):
                raise HTTPException(422, "horário inválido")
            horario = json.dumps({"dias": [int(d) for d in horario.get("dias") or [] if 0 <= int(d) <= 6], "inicio": horario.get("inicio") or "08:00", "fim": horario.get("fim") or "18:00"})
        off = [str(x)[:120] for x in (b.get("desligadas") or [])][:60]
        db.exec("UPDATE skills SET texto=?, horario=?, palavras_humano=?, fora_horario=?, desligadas=? WHERE usuario=? AND marca=?",
                (str(b.get("texto") or "")[:30000], horario or "", str(b.get("palavras_humano") or "")[:400], str(b.get("fora_horario") or "")[:600],
                 json.dumps(off, ensure_ascii=False), u["id"], m))
        salvar_versao(u["id"], m, str(b.get("texto") or "")[:30000], "você")
        return {"ok": True}

    @app.post("/api/skill/chat")
    async def skill_chat(request: Request):
        u = usuario(request)
        m = marca_de(request)
        fala = str((await request.json()).get("texto") or "").strip()[:4000]
        if not fala:
            raise HTTPException(422, "escreva sua resposta")
        garantir_skill(u["id"], m)
        db.exec("INSERT INTO skill_chat(usuario,marca,papel,texto,criado) VALUES(?,?,?,?,?)", (u["id"], m, "user", fala, agora()))
        hist = [{"role": "user" if h["papel"] == "user" else "assistant", "content": h["texto"]}
                for h in db.todos("SELECT papel, texto FROM skill_chat WHERE usuario=? AND marca=? ORDER BY id", (u["id"], m))]
        s = skill_de(u["id"], m)
        try:
            r = atendente.entrevistar(hist, json.loads(s.get("campos") or "{}"), MARCAS[m]["rede"], chamar_llm)
        except Exception:  # noqa: BLE001
            raise HTTPException(502, "a IA não respondeu agora; tente de novo")
        db.exec("INSERT INTO skill_chat(usuario,marca,papel,texto,criado) VALUES(?,?,?,?,?)", (u["id"], m, "assistant", r["skill"] if r["pronta"] else r["pergunta"], agora()))
        db.exec("UPDATE skills SET campos=? WHERE usuario=? AND marca=?", (json.dumps(r["campos"], ensure_ascii=False), u["id"], m))
        if r["pronta"]:
            db.exec("UPDATE skills SET texto=? WHERE usuario=? AND marca=?", (r["skill"], u["id"], m))
            salvar_versao(u["id"], m, r["skill"], "construtor")
        return r

    @app.post("/api/skill/testar")
    async def skill_testar(request: Request):
        u = usuario(request)
        m = marca_de(request)
        b = await request.json()
        texto = str(b.get("texto") or "").strip()[:1500]
        if not texto:
            raise HTTPException(422, "escreva a mensagem do cliente")
        hist = [{"direcao": "entrada" if x.get("de") == "cliente" else "ia", "texto": str(x.get("texto") or "")[:1500]} for x in (b.get("historico") or [])[-10:]]
        s = {**skill_de(u["id"], m), "horario": ""}  # teste ignora o horário
        return await run_in_threadpool(atendente.decidir, texto, hist + [{"direcao": "entrada", "texto": texto}], s, MARCAS[m]["rede"], "ia", 0, agora(), chamar_llm)

    @app.post("/api/skill/versoes/{vid}/restaurar")
    def skill_restaurar(vid: int, request: Request):
        u = usuario(request)
        m = marca_de(request)
        v = db.um("SELECT texto FROM skill_versoes WHERE id=? AND usuario=? AND marca=?", (vid, u["id"], m))
        if not v:
            raise HTTPException(404, "versão não encontrada")
        garantir_skill(u["id"], m)
        db.exec("UPDATE skills SET texto=? WHERE usuario=? AND marca=?", (v["texto"], u["id"], m))
        salvar_versao(u["id"], m, v["texto"], "você")
        return {"ok": True, "texto": v["texto"]}

    # ------------------------------------------------ Cakto
    @app.post("/api/cakto")
    async def cakto(request: Request):
        cru = await request.body()
        try:
            b = json.loads(cru)
        except ValueError:
            raise HTTPException(400, "json")
        if not cfg.cakto_segredo or not hmac.compare_digest(str(b.get("secret") or ""), cfg.cakto_segredo):
            raise HTTPException(401, "segredo")
        evento = str(b.get("event") or "")
        dados = b.get("data") or {}
        if isinstance(dados, list):
            dados = dados[0] if dados else {}
        eid = str(dados.get("id") or hashlib.sha256(cru).hexdigest()[:24]) + ":" + evento
        if db.um("SELECT 1 FROM eventos_cakto WHERE id=?", (eid,)):
            return {"ok": True, "repetido": True}
        db.exec("INSERT INTO eventos_cakto(id,recebido,corpo) VALUES(?,?,?)", (eid, agora(), cru.decode("utf-8", "replace")[:20000]))
        email = auth.normalizar_email((dados.get("customer") or {}).get("email"))
        alvo = cfg.planos_por_produto.get(str((dados.get("product") or {}).get("id") or ""))
        if not email or not alvo or ":" not in alvo:
            return {"ok": True, "ignorado": "sem email ou produto desconhecido"}
        marca, plano = alvo.split(":", 1)
        u = auth.usuario_por_email(db, email)
        a = db.um("SELECT * FROM assinaturas WHERE usuario=? AND marca=?", (u["id"], marca))
        if evento in ("purchase_approved", "subscription_renewed", "subscription_created"):
            base = max(agora(), a["ativo_ate"] if a else 0)
            db.exec("INSERT INTO assinaturas(usuario,marca,plano,ativo_ate,pedido) VALUES(?,?,?,?,?) ON CONFLICT(usuario,marca) DO UPDATE SET plano=excluded.plano, ativo_ate=excluded.ativo_ate, pedido=excluded.pedido",
                    (u["id"], marca, plano, base + 32 * 86400, str(dados.get("id") or "")))
            return {"ok": True, "liberado": email, "marca": marca}
        if evento in ("refund", "chargeback", "subscription_canceled", "subscription_cancelled"):
            db.exec("UPDATE assinaturas SET ativo_ate=? WHERE usuario=? AND marca=?", (agora(), u["id"], marca))
            return {"ok": True, "revogado": email}
        return {"ok": True, "ignorado": evento}

    # ------------------------------------------------ admin (painel do ecossistema)
    def exigir_admin(request: Request):
        chave = request.headers.get("x-admin-key") or ""
        if not cfg.admin_key or not hmac.compare_digest(chave, cfg.admin_key):
            raise HTTPException(401, "chave de admin")

    @app.get("/api/admin/resumo")
    def admin_resumo(request: Request):
        exigir_admin(request)
        ativos = db.todos("SELECT marca, plano, COUNT(*) n FROM assinaturas WHERE ativo_ate>? GROUP BY marca, plano", (agora(),))
        return {"produto": "atendeai", "nome": "Atende AI", "url": cfg.base_url, "assinantes": sum(r["n"] for r in ativos),
                "por_plano": {f"{r['marca']}:{r['plano']}": r["n"] for r in ativos},
                "receita_mensal": round(sum(r["n"] * PLANOS[r["plano"]]["preco"] for r in ativos if r["plano"] in PLANOS), 2),
                "cadastros": db.um("SELECT COUNT(*) n FROM usuarios")["n"],
                "contas_conectadas": db.um("SELECT COUNT(*) n FROM contas WHERE estado='connected'")["n"],
                "contas_com_problema": db.um("SELECT COUNT(*) n FROM contas WHERE estado IN ('degraded','reauth_required','disconnected')")["n"],
                "respostas_ia_30d": db.um("SELECT COUNT(*) n FROM mensagens WHERE direcao='ia' AND criado>?", (agora() - 30 * 86400,))["n"]}

    @app.post("/api/admin/cortesia")
    async def admin_cortesia(request: Request):
        exigir_admin(request)
        b = await request.json()
        email = auth.normalizar_email(b.get("email"))
        marca = b.get("marca") if b.get("marca") in MARCAS else "whats"
        plano = b.get("plano") if b.get("plano") in PLANOS else "pro"
        dias = max(0, min(400, int(b.get("dias") or 32)))
        if not email:
            raise HTTPException(422, "e-mail inválido")
        u = auth.usuario_por_email(db, email)
        db.exec("INSERT INTO assinaturas(usuario,marca,plano,ativo_ate) VALUES(?,?,?,?) ON CONFLICT(usuario,marca) DO UPDATE SET plano=excluded.plano, ativo_ate=MAX(ativo_ate, excluded.ativo_ate)",
                (u["id"], marca, plano, agora() + dias * 86400))
        return {"ok": True, "email": email, "marca": marca, "plano": plano}

    # ------------------------------------------------ páginas
    def pagina(nome: str, request: Request) -> HTMLResponse:
        m = marca_de(request)
        mk = MARCAS[m]
        html = (ESTATICO / nome).read_text(encoding="utf-8")
        for chave, valor in {"{{NOME}}": mk["nome"], "{{REDE}}": mk["rede"], "{{COR}}": mk["cor"], "{{ATENDE}}": mk["atende"], "{{MARCA}}": m,
                             "{{MARCA_JSON}}": json.dumps(publica(m), ensure_ascii=False)}.items():
            html = html.replace(chave, valor)
        v = os.environ.get("GIT_COMMIT") or VERSAO_INICIO
        html = html.replace('.css"', f'.css?v={v}"').replace('.js"', f'.js?v={v}"')  # cache novo a cada release
        return HTMLResponse(html)

    @app.get("/", response_class=HTMLResponse)
    def inicio(request: Request):
        return pagina("index.html", request)

    @app.get("/painel", response_class=HTMLResponse)
    def painel(request: Request):
        if not usuario(request, obrigatorio=False):
            return RedirectResponse("/?entrar=1", status_code=303)
        return pagina("painel.html", request)

    @app.get("/termos", response_class=HTMLResponse)
    def termos(request: Request):
        return pagina("termos.html", request)

    app.mount("/s", StaticFiles(directory=ESTATICO), name="estatico")
    return app


app = criar_app() if os.environ.get("ATENDEAI_SEM_APP") != "1" else None
