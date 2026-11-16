"""Harness do Atende AI (spec 44 5.4): decide se a IA responde, chama o dono ou fica quieta.

Ordem das regras (o código decide antes do modelo, para não gastar nem arriscar):
  1. conversa assumida por humano -> IA não responde;
  2. palavra que chama humano -> passa para humano e avisa;
  3. fora do horário -> mensagem de fora do horário (uma vez a cada 6 h por conversa);
  4. senão o modelo responde seguindo a skill; se ele disser que não sabe, passa para humano.
Também o construtor de skill por conversa (5.4.1). Puro: o chamador injeta `llm(mensagens) -> str`.
"""
from __future__ import annotations

import datetime as dt
import json
import re
import unicodedata
from typing import Callable

_MARCA_AUDIO = re.compile(r"^\s*\[(?:áudio|audio)\]\s*", re.I)  # marcador interno do histórico (resposta foi em nota de voz)

CAMPOS_SKILL = ["negocio", "produtos_e_precos", "tom", "perguntas_frequentes", "o_que_nunca_responder", "quando_passar_para_humano", "links", "horarios"]

SISTEMA = """Você atende clientes de um negócio pelo {rede}. Use a skill atendente-de-negocio e siga as REGRAS do dono à risca.
REGRAS:
{skill}

Responda à última mensagem do cliente de forma curta, simpática e em português do Brasil, como uma pessoa do time.
Nunca invente preço, prazo, endereço ou política que não esteja nas REGRAS. Não fale que é uma IA a não ser que perguntem.
Se a mensagem tiver várias perguntas e você souber só parte delas: responda a parte que está nas REGRAS, diga que vai confirmar o resto com o time
e termine a mensagem com [CHAMAR].
Se não souber nada com as REGRAS, ou se o cliente quiser negociar, reclamar ou falar com alguém, responda SÓ com: [HUMANO]"""

ENTREVISTA = """Você ajuda o dono de um negócio a montar as REGRAS do atendente automático dele no {rede}.
Assuntos obrigatórios: {campos}. Já respondido (JSON): {ja}.
Conversa até agora: {historico}
Se falta algum assunto, faça UMA pergunta curta e concreta sobre o próximo que falta (dê um exemplo de resposta).
Se tudo foi respondido, escreva as regras finais organizadas em seções com títulos (## Título).
Responda SÓ com JSON: {{"pronta": false, "pergunta": "...", "campos": {{...}}}} ou {{"pronta": true, "skill": "...", "campos": {{...}}}}"""

TZ_BR = dt.timezone(dt.timedelta(hours=-3))


def _sem_acento(s: str) -> str:
    return "".join(c for c in unicodedata.normalize("NFD", s.lower()) if unicodedata.category(c) != "Mn")


def pede_humano(texto: str, palavras: str) -> bool:
    t = _sem_acento(texto or "")
    return any(re.search(r"\b" + re.escape(_sem_acento(p.strip())) + r"\b", t) for p in (palavras or "").split(",") if p.strip())


def dentro_do_horario(horario_json: str, quando: dt.datetime | None = None) -> bool:
    """horario = {"dias":[0..6] (0=segunda), "inicio":"08:00", "fim":"18:00"}; vazio = sempre aberto."""
    if not horario_json:
        return True
    try:
        h = json.loads(horario_json)
    except ValueError:
        return True
    q = (quando or dt.datetime.now(TZ_BR)).astimezone(TZ_BR)
    if h.get("dias") and q.weekday() not in h["dias"]:
        return False
    agora = q.strftime("%H:%M")
    ini, fim = h.get("inicio") or "00:00", h.get("fim") or "23:59"
    return ini <= agora <= fim if ini <= fim else (agora >= ini or agora <= fim)


def decidir(texto: str, historico: list[dict], skill: dict, rede: str, modo: str, ultima_fora_horario: float, agora_ts: float,
            llm: Callable[[list[dict]], str], quando: dt.datetime | None = None) -> dict:
    """Devolve {"acao": "responder|humano|fora_horario|nada", "texto": str, "motivo": str}."""
    if modo == "humano":
        return {"acao": "nada", "texto": "", "motivo": "conversa com humano"}
    if pede_humano(texto, skill.get("palavras_humano") or ""):
        return {"acao": "humano", "texto": "Certo! Vou chamar alguém do time para falar com você. Só um instante.", "motivo": "pediu humano"}
    if not dentro_do_horario(skill.get("horario") or "", quando):
        if agora_ts - (ultima_fora_horario or 0) < 6 * 3600:
            return {"acao": "nada", "texto": "", "motivo": "fora do horário (já avisado)"}
        msg = (skill.get("fora_horario") or "").strip() or "Oi! Agora estamos fora do horário de atendimento. Assim que voltarmos, a gente te responde."
        return {"acao": "fora_horario", "texto": msg, "motivo": "fora do horário"}
    regras = (skill.get("texto") or "").strip()
    if not regras:
        return {"acao": "humano", "texto": "", "motivo": "sem regras escritas"}
    msgs = [{"role": "system", "content": SISTEMA.format(rede=rede, skill=regras[:8000])}]
    for m in historico[-12:]:
        conteudo = m["texto"] if m["direcao"] == "entrada" else _MARCA_AUDIO.sub("", m["texto"])  # o modelo não pode copiar o marcador interno
        msgs.append({"role": "user" if m["direcao"] == "entrada" else "assistant", "content": conteudo[:1500]})
    if not historico or historico[-1]["texto"] != texto:
        msgs.append({"role": "user", "content": texto[:1500]})
    try:
        r = _MARCA_AUDIO.sub("", (llm(msgs) or "")).strip()
    except Exception:  # noqa: BLE001
        return {"acao": "humano", "texto": "", "motivo": "IA indisponível"}
    if not r or "[HUMANO]" in r.upper():
        return {"acao": "humano", "texto": "Vou chamar alguém do time para te responder direitinho. Só um instante.", "motivo": "IA não soube responder"}
    if "[CHAMAR]" in r.upper():  # respondeu o que sabia; o resto fica com o dono
        texto = re.sub(r"\s*\[chamar\]\s*", " ", r, flags=re.I).strip()
        return {"acao": "humano", "texto": texto[:1500], "motivo": "IA respondeu parte e chamou o dono"}
    return {"acao": "responder", "texto": r[:1500], "motivo": ""}


def _json(txt: str) -> dict:
    m = re.search(r"\{.*\}", txt or "", re.S)
    if not m:
        raise ValueError("sem JSON")
    return json.loads(re.sub(r",\s*([}\]])", r"\1", m.group(0)), strict=False)


def entrevistar(historico: list[dict], campos: dict, rede: str, llm: Callable[[list[dict]], str]) -> dict:
    prompt = ENTREVISTA.format(rede=rede, campos=", ".join(CAMPOS_SKILL), ja=json.dumps(campos or {}, ensure_ascii=False)[:4000],
                               historico=json.dumps(historico[-20:], ensure_ascii=False)[:8000])
    j = _json(llm([{"role": "user", "content": prompt}]))
    preenchidos = {**{k: v for k, v in (campos or {}).items() if k in CAMPOS_SKILL},
                   **{k: v for k, v in (j.get("campos") or {}).items() if k in CAMPOS_SKILL and str(v).strip()}}
    faltam = [c for c in CAMPOS_SKILL if c not in preenchidos]
    if j.get("pronta") and not faltam and str(j.get("skill") or "").strip():
        return {"pronta": True, "skill": str(j["skill"]).strip()[:12000], "campos": preenchidos, "faltam": []}
    pergunta = str(j.get("pergunta") or "").strip() or f"Me conta sobre: {faltam[0].replace('_', ' ')}."
    return {"pronta": False, "pergunta": pergunta, "campos": preenchidos, "faltam": faltam}
