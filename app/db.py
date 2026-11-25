"""Banco do Atende AI: SQLite num volume (/data). Hora em epoch (s)."""
from __future__ import annotations

import os
import sqlite3
import uuid
import threading
import time
from contextlib import contextmanager

ESQUEMA = """
CREATE TABLE IF NOT EXISTS usuarios (
  id INTEGER PRIMARY KEY,
  email TEXT UNIQUE NOT NULL,
  criado REAL NOT NULL,
  plano TEXT NOT NULL DEFAULT 'teste',
  ativo_ate REAL NOT NULL DEFAULT 0,
  pedido TEXT
);
CREATE TABLE IF NOT EXISTS codigos (
  email TEXT PRIMARY KEY, hash TEXT NOT NULL, expira REAL NOT NULL,
  tentativas INTEGER NOT NULL DEFAULT 0, enviado REAL NOT NULL
);
CREATE TABLE IF NOT EXISTS sessoes (hash TEXT PRIMARY KEY, usuario INTEGER NOT NULL, expira REAL NOT NULL);
CREATE TABLE IF NOT EXISTS eventos_cakto (id TEXT PRIMARY KEY, recebido REAL NOT NULL, corpo TEXT NOT NULL);

-- assinatura por marca (whats/insta/tiktok/face): cada rede é um produto
CREATE TABLE IF NOT EXISTS assinaturas (
  usuario INTEGER NOT NULL, marca TEXT NOT NULL, plano TEXT NOT NULL, ativo_ate REAL NOT NULL, pedido TEXT,
  PRIMARY KEY (usuario, marca)
);

-- conta conectada (uma conexão do gateway de canais)
CREATE TABLE IF NOT EXISTS contas (
  id TEXT PRIMARY KEY,                 -- connection_id do gateway
  usuario INTEGER NOT NULL,
  marca TEXT NOT NULL,
  provider TEXT NOT NULL,              -- whatsapp | instagram | messenger | tiktok
  estado TEXT NOT NULL DEFAULT 'pending_auth',
  rotulo TEXT NOT NULL DEFAULT '',
  segredo_webhook TEXT NOT NULL,
  ia_ligada INTEGER NOT NULL DEFAULT 1,
  criado REAL NOT NULL,
  atualizado REAL NOT NULL
);
CREATE INDEX IF NOT EXISTS contas_usuario ON contas(usuario, marca);

-- regras do atendimento (skill) por usuário e marca
CREATE TABLE IF NOT EXISTS skills (
  usuario INTEGER NOT NULL, marca TEXT NOT NULL,
  texto TEXT NOT NULL DEFAULT '', campos TEXT NOT NULL DEFAULT '{}',
  horario TEXT NOT NULL DEFAULT '',            -- JSON {"dias":[0..6], "inicio":"08:00", "fim":"18:00"} vazio = sempre
  palavras_humano TEXT NOT NULL DEFAULT 'atendente,humano,pessoa,reclamação',
  fora_horario TEXT NOT NULL DEFAULT '',
  PRIMARY KEY (usuario, marca)
);
CREATE TABLE IF NOT EXISTS skill_versoes (id INTEGER PRIMARY KEY, usuario INTEGER NOT NULL, marca TEXT NOT NULL, texto TEXT NOT NULL, autor TEXT NOT NULL, criado REAL NOT NULL);
CREATE TABLE IF NOT EXISTS skill_chat (id INTEGER PRIMARY KEY, usuario INTEGER NOT NULL, marca TEXT NOT NULL, papel TEXT NOT NULL, texto TEXT NOT NULL, criado REAL NOT NULL);

-- conversas e mensagens
CREATE TABLE IF NOT EXISTS conversas (
  id INTEGER PRIMARY KEY,
  conta TEXT NOT NULL,
  externo TEXT NOT NULL,               -- conversation.external_id do gateway
  contato TEXT NOT NULL DEFAULT '',
  modo TEXT NOT NULL DEFAULT 'ia',     -- ia | humano
  ultima REAL NOT NULL,
  nao_lidas INTEGER NOT NULL DEFAULT 0,
  fora_avisado REAL NOT NULL DEFAULT 0,
  UNIQUE (conta, externo)
);
CREATE TABLE IF NOT EXISTS mensagens (
  id INTEGER PRIMARY KEY,
  conversa INTEGER NOT NULL,
  externo TEXT,                         -- message.external_id (idempotência)
  direcao TEXT NOT NULL,                -- entrada | ia | humano | eco
  texto TEXT NOT NULL,
  criado REAL NOT NULL,
  UNIQUE (conversa, externo)
);
CREATE INDEX IF NOT EXISTS msg_conversa ON mensagens(conversa, criado);
CREATE TABLE IF NOT EXISTS eventos_canal (id TEXT PRIMARY KEY, recebido REAL NOT NULL);
-- persona (Fala Fael): fãs pagantes por número e ajustes do admin
CREATE TABLE IF NOT EXISTS fas (
  marca TEXT NOT NULL, telefone TEXT NOT NULL, plano TEXT NOT NULL DEFAULT '', ativo_ate REAL NOT NULL DEFAULT 0,
  email TEXT NOT NULL DEFAULT '', nome TEXT NOT NULL DEFAULT '', pedido TEXT NOT NULL DEFAULT '', criado REAL NOT NULL DEFAULT 0,
  PRIMARY KEY (marca, telefone)
);
CREATE TABLE IF NOT EXISTS ajustes (chave TEXT PRIMARY KEY, valor TEXT NOT NULL);
"""


class BancoSQLite:
    def __init__(self, caminho: str):
        self._trava = threading.Lock()
        self.con = sqlite3.connect(caminho, check_same_thread=False, isolation_level=None)
        self.con.row_factory = sqlite3.Row
        self.con.execute("PRAGMA journal_mode=WAL")
        self.con.executescript(ESQUEMA)
        _migrar_esquema(self)

    @contextmanager
    def tx(self):
        with self._trava:
            self.con.execute("BEGIN IMMEDIATE")
            try:
                yield self.con
                self.con.execute("COMMIT")
            except BaseException:
                self.con.execute("ROLLBACK")
                raise

    def um(self, sql: str, args=()):
        with self._trava:
            r = self.con.execute(sql, args).fetchone()
        return dict(r) if r else None

    def todos(self, sql: str, args=()):
        with self._trava:
            return [dict(r) for r in self.con.execute(sql, args).fetchall()]

    def exec(self, sql: str, args=()):
        with self._trava:
            return self.con.execute(sql, args)


def agora() -> float:
    return time.time()


def Banco(caminho: str):
    """Postgres central (banco `produtos`, schema do produto) quando PRODUTOS_DATABASE_URL existe; senão o SQLite de antes
    (plano de volta). Spec 57, seção 8. PRODUTOS_SCHEMA_TESTE=1 dá um schema novo por instância (testes isolados)."""
    dsn = os.environ.get("PRODUTOS_DATABASE_URL")
    if not dsn:
        return BancoSQLite(caminho)
    from produtos_core.banco_pg import Banco as BancoPG
    schema = os.environ.get("PRODUTOS_SCHEMA", "atendeai")
    if os.environ.get("PRODUTOS_SCHEMA_TESTE"):
        schema = "teste_" + uuid.uuid4().hex[:10]
    b = BancoPG(dsn, schema, ESQUEMA)
    _migrar_esquema(b)
    return b


def _migrar_esquema(self):
    """Migrações de coluna e tabela (rodam no SQLite e no Postgres; spec 57)."""
    cols = {r[1] for r in self.con.execute("PRAGMA table_info(contas)")}
    if "ja_conectou" not in cols:  # só entra na lista a conta que conectou ao menos uma vez (16/11)
        self.con.execute("ALTER TABLE contas ADD COLUMN ja_conectou INTEGER NOT NULL DEFAULT 0")
        self.con.execute("UPDATE contas SET ja_conectou=1 WHERE estado IN ('connected','degraded','reauth_required')")
    if "so_liberadas" not in cols:  # modo teste: a IA só responde conversas liberadas uma a uma (16/11)
        self.con.execute("ALTER TABLE contas ADD COLUMN so_liberadas INTEGER NOT NULL DEFAULT 0")
    if "voz_modo" not in cols:  # resposta em áudio: desligado | quando_audio | sempre (plano Voz, 16/11)
        self.con.execute("ALTER TABLE contas ADD COLUMN voz_modo TEXT NOT NULL DEFAULT 'desligado'")
        self.con.execute("ALTER TABLE contas ADD COLUMN voz_id TEXT NOT NULL DEFAULT ''")
    scols = {r[1] for r in self.con.execute("PRAGMA table_info(skills)")}
    if scols and "desligadas" not in scols:  # skills (seções ## do texto) desligadas pelo dono (16/11)
        self.con.execute("ALTER TABLE skills ADD COLUMN desligadas TEXT NOT NULL DEFAULT '[]'")
    mcols = {r[1] for r in self.con.execute("PRAGMA table_info(mensagens)")}
    if "audio" not in mcols:  # nome do arquivo de áudio (resposta em voz ou áudio do cliente) para tocar no painel
        self.con.execute("ALTER TABLE mensagens ADD COLUMN audio TEXT NOT NULL DEFAULT ''")
    ccols = {r[1] for r in self.con.execute("PRAGMA table_info(conversas)")}
    if "liberada" not in ccols:
        self.con.execute("ALTER TABLE conversas ADD COLUMN liberada INTEGER NOT NULL DEFAULT 0")
