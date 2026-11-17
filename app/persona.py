"""Fala Fael (e futuras personas): o fã paga e conversa no WhatsApp com a IA do influenciador.

Diferente do Atende AI (um negócio atende clientes), aqui UM número (o do influenciador) conversa com MUITOS fãs:
  - quem paga é o fã, identificado pelo número do WhatsApp (o checkout pede o celular);
  - todo número novo ganha algumas mensagens de teste; depois recebe o convite para assinar;
  - a IA fala em primeira pessoa como o influenciador, seguindo a skill que o admin escreve no painel;
  - pode responder em áudio na voz clonada ([VOZ]) e mandar foto ([FOTO: cena]) gerada a partir das fotos de referência;
  - nunca nega ser uma IA quando perguntam (transparência com o fã).
Puro: o chamador injeta `llm(mensagens) -> str`.
"""
from __future__ import annotations

import html
import re
from typing import Callable

_MARCA_AUDIO = re.compile(r"^\s*\[(?:áudio|audio)\]\s*", re.I)
_FOTO = re.compile(r"\[foto:\s*([^\]]{3,400})\]", re.I)

SISTEMA = """Você é {nome}, conversando com um fã pelo WhatsApp. Fale SEMPRE em primeira pessoa, como {nome} fala de verdade,
seguindo a PERSONALIDADE abaixo à risca (jeito de falar, gírias, assuntos, limites).
PERSONALIDADE (escrita pelo próprio {nome} e pela equipe dele):
{skill}

Regras fixas:
- Escreva como gente digitando no WhatsApp: de 1 a 3 mensagens BEM curtas (de 2 a 10 palavras cada; resposta inteira com no máximo 25 palavras), separadas por uma linha em branco.
  Nada de parágrafo, lista, passo a passo ou textão. Não repita pergunta que já fez; siga o assunto do fã com coerência. Gíria, "kkkk", pergunta de volta de vez em quando. Ex.:
  Kkkk já sim sô

  Caí feio num treino de laço

  Joelho ficou roxo uma semana kkkk

  E você, já caiu?
- Se o fã perguntar se você é uma IA, robô ou se é você mesmo: diga com leveza que é a IA oficial do {nome}, treinada com o jeito e a voz dele.
- Nada de conteúdo sexual, ódio, golpe, promessa de dinheiro, encontro presencial ou pedido de dados pessoais/pagamento fora do site.
- Você NÃO vê imagens. Só fale de uma foto do fã se aparecer "[o fã mandou uma foto dele]"; se ele disser que mandou e isso não aparecer, diga que a foto não chegou e peça de novo.
- Não invente fatos da vida real (agenda, show, preço, endereço) que não estejam na PERSONALIDADE; desconverse com simpatia.
ÁUDIO: quando fizer sentido mandar um áudio (o fã mandou áudio, pediu áudio, ou é um momento especial), comece a resposta com [VOZ]
e escreva como fala (frases curtas, sem emoji, sem lista).
FOTO: quando o fã pedir uma foto sua, ou quando mandar uma foto deixar a conversa mais legal, acrescente no fim UMA marca
[FOTO: descrição curta da cena em que você aparece, ex.: "eu no curral ao pôr do sol, sorrindo, chapéu preto"]. No máximo uma foto por resposta.
Não descreva a foto no texto; a marca já basta.
FOTO JUNTOS: se o fã já mandou uma foto dele ("[o fã mandou uma foto dele]") e pedir foto de vocês dois, a descrição começa com
"eu e você" e conta a cena (ex.: [FOTO: eu e você laçando um boi de brincadeira no curral, rindo]). Brincadeira saudável, sem nada ofensivo."""

BOAS_VINDAS = ("Opa! Aqui é a IA oficial do {nome}, com o jeito e a voz dele. Pode mandar texto ou áudio que eu respondo, "
               "e se pedir eu te mando foto também. Você tem {gratis} mensagens de teste.")

CONVITE = ("Foi muito bom falar com você! Seu teste acabou. Para continuar conversando comigo, com áudio e foto, é só assinar aqui: {link} "
           "Depois de pagar com este mesmo número, é só voltar aqui e mandar um oi.")

FIM_PLANO = "Suas mensagens do mês acabaram. Para seguir conversando, renove ou suba de plano aqui: {link}"


def telefone(externo: str) -> str:
    """Só os dígitos do número do WhatsApp (o externo do gateway pode vir como 5511...@s.whatsapp.net)."""
    d = re.sub(r"\D", "", (externo or "").split("@")[0])
    return d[-13:] if len(d) > 13 else d


def mesmo_numero(a: str, b: str) -> bool:
    """Compara números com e sem o 9 extra e com ou sem o 55 (o fã digita do jeito dele no checkout)."""
    def chaves(x: str) -> set[str]:
        x = re.sub(r"\D", "", x or "")
        if x.startswith("55") and len(x) >= 12:
            x = x[2:]
        out = {x}
        if len(x) == 11 and x[2] == "9":
            out.add(x[:2] + x[3:])
        if len(x) == 10:
            out.add(x[:2] + "9" + x[2:])
        return out
    return bool(a and b and chaves(a) & chaves(b))


def conversar(texto: str, historico: list[dict], nome: str, skill: str, llm: Callable[[list[dict]], str], veio_audio: bool = False,
              revisao: bool = False) -> dict:
    """Devolve {"texto": str, "voz": bool, "foto": str|None}."""
    msgs = [{"role": "system", "content": SISTEMA.format(nome=nome, skill=(skill or "").strip()[:16000] or f"Seja simpático e autêntico como {nome}.")}]
    for m in historico[-16:]:
        conteudo = m["texto"] if m["direcao"] == "entrada" else _MARCA_AUDIO.sub("", re.sub(r"^\[foto\][^\n]*\n?", "", m["texto"]))
        msgs.append({"role": "user" if m["direcao"] == "entrada" else "assistant", "content": conteudo[:1500]})
    if not historico or historico[-1]["texto"] != texto:
        msgs.append({"role": "user", "content": texto[:1500]})
    if not texto.startswith("[o fã mandou uma foto dele]") and DISSE_QUE_MANDOU.search(texto or ""):
        msgs.append({"role": "system", "content": "ATENÇÃO: o fã fala de uma foto, mas NENHUMA foto chegou. Diga numa frase curta que a foto não chegou e peça pra mandar de novo. Não descreva nem elogie foto nenhuma."})
    if veio_audio:
        msgs.append({"role": "system", "content": "O fã mandou áudio: responda em áudio ([VOZ])."})
    r = _MARCA_AUDIO.sub("", html.unescape(llm(msgs) or "")).strip()
    if revisao:
        r = revisar(r, texto, historico, nome, skill, llm)
    foto = None
    m = _FOTO.search(r)
    if m:
        foto = m.group(1).strip().strip('"')
        r = _FOTO.sub("", r).strip()
    if not foto and PEDE_FOTO.search(texto or "") and PEDIDO.search(texto or "") and not texto.startswith("[o fã mandou"):
        foto = ("eu e você, " if JUNTOS.search(texto) else "eu, ") + re.sub(r"\s+", " ", texto)[:200]  # pediu foto e o modelo esqueceu
    voz = bool(re.match(r"^\s*\[voz\]", r, re.I))
    r = re.sub(r"^\s*\[voz\]\s*", "", r, flags=re.I).strip()
    r = re.sub(r"\[(?:humano|chamar)\]", "", r, flags=re.I).strip()
    r = re.sub(r"^(?:\s*\[[A-ZÀ-Ú_ ]{2,20}\]\s*)+", "", r).strip()
    r = re.sub(r"\[(?!foto)[A-Za-zÀ-ú_ ]{2,20}:[^\]]*\]", "", r).strip()  # marcas inventadas ([TOMBO: ...]) nunca vão para o fã  # marcas soltas que o modelo inventa ([AHORA], [TEXTO]...)
    return {"texto": r[:1500], "voz": voz, "foto": foto}


DISSE_QUE_MANDOU = re.compile(r"(sou eu|essa (a[ií] )?(sou|é) eu|segue( a)? foto|mandei( a)? foto|olha (a )?foto|aqui (est[aá] )?(a|minha) foto|chegou a foto)", re.I)
JUNTOS = re.compile(r"\b(voc[eê]|vc|n[oó]s|nos dois|juntos|com o f[aã])\b", re.I)


REVISAO = """Você revisa a resposta da IA do {nome} antes dela ir pro fã no WhatsApp. Conversa recente:
{historico}

Última mensagem do fã: {fala}
Rascunho da resposta: {rascunho}

Corrija o rascunho se tiver: frase sem sentido, erro de português ou de digitação, fato inventado que contradiz a PERSONALIDADE,
resposta que não responde o fã, repetição de pergunta já feita, texto longo (máximo 3 mensagens curtas separadas por linha em branco),
ou foto pedida pelo fã sem a marca [FOTO: ...] (se o fã pediu foto, a resposta TEM que terminar com [FOTO: cena]; se pediu foto dos dois, a cena começa com "eu e você").
Mantenha o jeito do {nome}, as marcas [VOZ] e [FOTO: ...] quando fizerem sentido, e nada de comentário seu.
Responda SÓ com a resposta final, pronta para enviar.
PERSONALIDADE:
{skill}"""

PEDE_FOTO = re.compile(r"(foto|selfie|imagem)", re.I)
PEDIDO = re.compile(r"(manda|mande|faz|faça|tira|tire|me (manda|envia)|quero|bora|cad[eê])", re.I)


def revisar(rascunho: str, fala: str, historico: list[dict], nome: str, skill: str, llm: Callable[[list[dict]], str]) -> str:
    """Segunda passada: o próprio modelo confere coerência e formato antes de entregar. Falhou ou veio vazio: fica o rascunho."""
    hist = chr(10).join(("Fã: " if m["direcao"] == "entrada" else nome + ": ") + m["texto"][:200] for m in historico[-10:])
    try:
        r = (llm([{"role": "user", "content": REVISAO.format(nome=nome, historico=hist, fala=fala[:500], rascunho=rascunho[:1500], skill=(skill or "")[:6000])}]) or "").strip()
    except Exception:  # noqa: BLE001
        return rascunho
    r = html.unescape(r).strip().strip('"')
    return r if 0 < len(r) <= 1200 else rascunho


def bolhas(texto: str, maximo: int = 3, limite: int = 110) -> list[str]:
    """Quebra a resposta em até 3 mensagens curtas, como gente manda no WhatsApp; corta o que passar do tamanho."""
    partes = []
    for linha in (texto or "").splitlines():
        linha = linha.strip()
        while len(linha) > limite:  # frase longa: quebra no fim de frase ou vírgula
            corte = max(linha.rfind(". ", 0, limite), linha.rfind("! ", 0, limite), linha.rfind("? ", 0, limite), linha.rfind(", ", 0, limite))
            if corte < 20:
                corte = linha.rfind(" ", 0, limite)
            partes.append(linha[:corte + 1].strip().rstrip(","))
            linha = linha[corte + 1:].strip()
        if linha:
            partes.append(linha)
    return partes[:maximo]


def prompt_foto(nome: str, cena: str, com_fa: bool = False) -> str:
    if com_fa:
        return (f"The reference photos show two different people. All photos except the LAST one show {nome} (black cowboy hat, beard, long dark hair): "
                f"keep his exact face and look. The LAST reference photo shows a fan: keep the fan's exact face, hair and features too. "
                f"Put BOTH of them together in the same photo, both clearly visible and recognizable. Scene: {cena}. "
                "Fun, friendly, natural smartphone photo as if taken together and sent on WhatsApp, vertical framing, good light. "
                "Photorealistic. No text, no watermark, fully clothed, family friendly.")
    return (f"Use the man in the reference photos ({nome}): keep his exact face, beard, hair and signature look, same person, photorealistic. "
            f"Scene: {cena}. Natural smartphone photo, as if he took it and sent it on WhatsApp, vertical framing, good light. "
            "No text, no watermark, fully clothed, family friendly.")
