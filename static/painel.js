// Painel do Atende AI: conversas, regras (construtor + teste + versões), conta conectada e plano.
;(() => {
  const $ = (q, r = document) => r.querySelector(q)
  const $$ = (q, r = document) => [...r.querySelectorAll(q)]
  const esc = (s) => String(s ?? '').replace(/[&<>"']/g, (c) => ({ '&': '&amp;', '<': '&lt;', '>': '&gt;', '"': '&quot;', "'": '&#39;' })[c])
  const hora = (ts) => new Date(ts * 1000).toLocaleString('pt-BR', { day: '2-digit', month: '2-digit', hour: '2-digit', minute: '2-digit' })
  async function api(url, op = {}) {
    const r = await fetch(url, { ...op, headers: { 'Content-Type': 'application/json', ...(op.headers || {}) } })
    let j = {}
    try { j = await r.json() } catch {}
    if (r.status === 401) { location.href = '/?entrar=1'; throw new Error('entre de novo') }
    if (!r.ok) throw new Error(typeof j.detail === 'string' ? j.detail : 'Não deu certo. Tente de novo.')
    return j
  }
  const post = (url, corpo) => api(url, { method: 'POST', body: JSON.stringify(corpo || {}) })
  let CONTA = null

  // ------------------------------------------------ abas
  function abrirAba(nome) {
    $$('[data-aba]').forEach((b) => b.setAttribute('aria-selected', String(b.dataset.aba === nome)))
    $$('[data-painel]').forEach((p) => (p.hidden = p.dataset.painel !== nome))
    history.replaceState(null, '', '#' + nome)
    ;({ conversas: carregarConversas, regras: carregarSkill, contas: carregarContas, plano: carregarPlano })[nome]?.()
  }
  $$('[data-aba]').forEach((b) => (b.onclick = () => abrirAba(b.dataset.aba)))
  $('#sair').onclick = async () => { await post('/api/sair'); location.href = '/' }

  async function carregarConta() {
    CONTA = await api('/api/conta')
    const av = $('#aviso')
    if (!CONTA.assinante) {
      av.hidden = false
      av.innerHTML = `<span>Escolha um plano para conectar sua conta e ligar o atendimento.</span><button class="btn btn-pri sm" data-ir="plano">Ver planos</button>`
    } else if (!CONTA.contas) {
      av.hidden = false
      av.innerHTML = `<span>Falta conectar a sua conta do ${esc(window.MARCA.rede)}.</span><button class="btn btn-pri sm" data-ir="contas">Conectar agora</button>`
    } else if (CONTA.usadas >= CONTA.limite_msgs) {
      av.hidden = false
      av.innerHTML = `<span>As respostas da IA deste mês acabaram. As conversas seguem chegando para você responder.</span><button class="btn btn-pri sm" data-ir="plano">Subir de plano</button>`
    } else av.hidden = true
    $$('[data-ir]', av).forEach((b) => (b.onclick = () => abrirAba(b.dataset.ir)))
  }

  // ------------------------------------------------ conversas
  let convAtual = null
  async function carregarConversas() {
    const j = await api('/api/conversas')
    const n = j.conversas.reduce((s, c) => s + (c.nao_lidas || 0), 0)
    $('#b-nao-lidas').hidden = !n
    $('#b-nao-lidas').textContent = n
    $('#conv-lista').innerHTML = j.conversas.length ? j.conversas.map((c) => `<button class="conv-item ${c.id === convAtual ? 'ativo' : ''}" data-c="${c.id}">
      <b><span>${esc(c.contato || 'Contato')}</span>${c.modo === 'humano' ? '<span class="tag humano">com você</span>' : '<span class="tag">IA</span>'}</b>
      <p>${c.nao_lidas ? `<strong style="color:var(--ac)">${c.nao_lidas} nova(s) · </strong>` : ''}${esc(c.previa || '')}</p></button>`).join('')
      : '<p class="vazio">Nenhuma conversa ainda. Quando alguém mandar mensagem, ela aparece aqui.</p>'
    $$('[data-c]').forEach((b) => (b.onclick = () => abrirConversa(+b.dataset.c)))
    if (convAtual) abrirConversa(convAtual, true)
  }
  const QUEM = { entrada: 'cliente', ia: 'IA', humano: 'você', eco: 'enviado pelo celular' }
  async function abrirConversa(id, silencioso) {
    convAtual = id
    const c = await api('/api/conversas/' + id)
    $$('.conv-item').forEach((b) => b.classList.toggle('ativo', +b.dataset.c === id))
    if (!silencioso) { const it = $(`.conv-item[data-c="${id}"] p strong`); if (it) it.outerHTML = ''; $('#b-nao-lidas').hidden = !$$('.conv-item p strong').length }
    const d = $('#conv-detalhe')
    const rolarFim = !silencioso || (() => { const m = $('.conv-msgs', d); return !m || m.scrollTop + m.clientHeight >= m.scrollHeight - 40 })()
    d.innerHTML = `<div class="conv-cab"><div><b>${esc(c.contato || 'Contato')}</b> ${c.modo === 'humano' ? '<span class="tag humano">você está atendendo</span>' : '<span class="tag">IA atendendo</span>'}</div>
        ${c.modo === 'humano' ? '<button class="btn btn-sec sm" id="devolver">Devolver para a IA</button>' : '<button class="btn btn-sec sm" id="assumir">Assumir conversa</button>'}</div>
      <div class="conv-msgs">${c.mensagens.map((m) => `<div class="fala ${m.direcao === 'eco' ? 'humano' : esc(m.direcao)}">${esc(m.texto)}<span class="quem">${QUEM[m.direcao] || ''} · ${hora(m.criado)}</span></div>`).join('')}</div>
      <form class="conv-env" id="env"><input id="env-txt" placeholder="Escreva como você (a IA para nesta conversa)" autocomplete="off"><button class="btn btn-pri">Enviar</button></form>`
    if (rolarFim) { const m = $('.conv-msgs', d); m.scrollTop = m.scrollHeight }
    $('#assumir', d)?.addEventListener('click', async () => { await post(`/api/conversas/${id}/assumir`); abrirConversa(id) ; carregarConversas() })
    $('#devolver', d)?.addEventListener('click', async () => { await post(`/api/conversas/${id}/devolver`); abrirConversa(id); carregarConversas() })
    $('#env', d).onsubmit = async (e) => {
      e.preventDefault()
      const t = $('#env-txt').value.trim()
      if (!t) return
      try { await post(`/api/conversas/${id}/enviar`, { texto: t }); $('#env-txt').value = ''; abrirConversa(id) } catch (err) { alert(err.message) }
    }
  }

  // ------------------------------------------------ regras
  const DIAS = ['Seg', 'Ter', 'Qua', 'Qui', 'Sex', 'Sáb', 'Dom']
  $('#sk-dias').innerHTML = DIAS.map((d, i) => `<label><input type="checkbox" value="${i}"><span>${d}</span></label>`).join('')
  const skMsg = (t, tipo = '') => { $('#sk-msg').textContent = t; $('#sk-msg').className = 'msg ' + tipo }
  function desenharChat(hist) {
    const c = $('#sk-chat')
    c.innerHTML = (hist.length ? '' : `<div class="fala assistant">Vou te fazer algumas perguntas para montar as regras do seu atendente. Para começar: o que você vende e para quem?</div>`) +
      hist.map((h) => `<div class="fala ${h.papel === 'user' ? 'user' : 'assistant'}">${esc(h.texto)}</div>`).join('')
    c.scrollTop = c.scrollHeight
  }
  async function carregarSkill() {
    const s = await api('/api/skill')
    $('#sk-texto').value = s.texto || ''
    $('#sk-palavras').value = s.palavras_humano || ''
    $('#sk-fora').value = s.fora_horario || ''
    $('#sk-ini').value = s.horario?.inicio || ''
    $('#sk-fim').value = s.horario?.fim || ''
    $$('#sk-dias input').forEach((i) => (i.checked = (s.horario?.dias || []).includes(+i.value)))
    const n = Object.keys(s.campos || {}).length
    $('#sk-prog').textContent = `${n}/8 assuntos`
    $('#sk-barra').style.width = `${(n / 8) * 100}%`
    desenharChat(s.historico || [])
    $('#sk-versoes').innerHTML = s.versoes.length ? s.versoes.map((v, i) => `<div class="versao"><div><b>${hora(v.criado)}</b> <span class="dim">${esc(v.autor)}${i === 0 ? ' · atual' : ''}</span><p>${esc(v.inicio)}</p></div>
      ${i ? `<button class="btn btn-ghost sm" data-v="${v.id}">Voltar</button>` : ''}</div>`).join('') : '<p class="vazio">Nenhuma versão salva ainda.</p>'
    $$('[data-v]').forEach((b) => (b.onclick = async () => { if (!confirm('Voltar para esta versão das regras?')) return; await post(`/api/skill/versoes/${b.dataset.v}/restaurar`); carregarSkill() }))
  }
  $('#sk-form').onsubmit = async (e) => {
    e.preventDefault()
    const t = $('#sk-txt').value.trim()
    if (!t) return
    $('#sk-txt').value = ''
    const c = $('#sk-chat')
    c.insertAdjacentHTML('beforeend', `<div class="fala user">${esc(t)}</div><div class="fala assistant dim" id="pensando">Pensando…</div>`)
    c.scrollTop = c.scrollHeight
    try {
      const r = await post('/api/skill/chat', { texto: t })
      if (r.pronta) skMsg('Regras prontas e salvas. Teste abaixo antes de ligar.', 'ok')
    } catch (err) { skMsg(err.message, 'erro') }
    carregarSkill()
  }
  $('#sk-salvar').onclick = async () => {
    const ini = $('#sk-ini').value, fim = $('#sk-fim').value
    const dias = $$('#sk-dias input:checked').map((i) => +i.value)
    try {
      await api('/api/skill', { method: 'PUT', body: JSON.stringify({ texto: $('#sk-texto').value, palavras_humano: $('#sk-palavras').value, fora_horario: $('#sk-fora').value,
        horario: ini && fim ? { inicio: ini, fim, dias } : null }) })
      skMsg('Salvo.', 'ok')
      carregarSkill()
    } catch (err) { skMsg(err.message, 'erro') }
  }
  const teste = []
  $('#ts-form').onsubmit = async (e) => {
    e.preventDefault()
    const t = $('#ts-txt').value.trim()
    if (!t) return
    $('#ts-txt').value = ''
    const c = $('#ts-chat')
    c.insertAdjacentHTML('beforeend', `<div class="fala entrada">${esc(t)}</div>`)
    c.scrollTop = c.scrollHeight
    try {
      const r = await post('/api/skill/testar', { texto: t, historico: teste.slice(-10) })
      teste.push({ de: 'cliente', texto: t })
      const nota = { responder: '', humano: 'passaria para você', fora_horario: 'fora do horário', nada: 'não responderia' }[r.acao]
      if (r.texto) teste.push({ de: 'ia', texto: r.texto })
      c.insertAdjacentHTML('beforeend', `<div class="fala ia">${esc(r.texto || '(sem resposta)')}${nota ? `<span class="quem">${esc(nota)}</span>` : ''}</div>`)
    } catch (err) { c.insertAdjacentHTML('beforeend', `<div class="fala ia">${esc(err.message)}</div>`) }
    c.scrollTop = c.scrollHeight
  }

  // ------------------------------------------------ contas conectadas
  const TAG = { connected: 'ok', degraded: 'erro', reauth_required: 'erro', disconnected: 'erro' }
  async function carregarContas() {
    const j = await api('/api/contas')
    $('#lista-contas').innerHTML = j.contas.length ? j.contas.map((k) => `<div class="conta-linha"><div><b>${esc(k.rotulo || window.MARCA.rede)}</b> <span class="tag ${TAG[k.estado] || ''}">${esc(k.estado_pt)}</span>
        <p class="dim" style="font-size:13px">IA ${k.ia_ligada ? 'ligada' : 'desligada'} nesta conta</p></div>
      <div class="acoes">
        ${k.estado === 'connected' ? '' : `<button class="btn btn-pri sm" data-k="${k.id}" data-a="${k.estado === 'pending_auth' || k.estado.startsWith('awaiting') ? 'continuar' : 'reconectar'}">${k.estado === 'pending_auth' || k.estado.startsWith('awaiting') ? 'Continuar' : 'Reconectar'}</button>`}
        <button class="btn btn-sec sm" data-k="${k.id}" data-a="${k.ia_ligada ? 'desligar_ia' : 'ligar_ia'}">${k.ia_ligada ? 'Pausar IA' : 'Ligar IA'}</button>
        <button class="btn btn-ghost sm" data-k="${k.id}" data-a="desconectar">Desconectar</button></div></div>`).join('')
      : `<p class="vazio">Nenhuma conta conectada. ${esc(window.MARCA.conecta)}</p>`
    $$('[data-k]').forEach((b) => (b.onclick = async () => {
      const id = b.dataset.k, a = b.dataset.a
      if (a === 'desconectar' && !confirm('Desconectar esta conta? A IA para de responder até você conectar de novo.')) return
      try {
        if (a === 'continuar') return abrirLogin(await api('/api/contas/' + id))
        const r = await post(`/api/contas/${id}/${a}`)
        if (a === 'reconectar') return abrirLogin(r)
        carregarContas(); carregarConta()
      } catch (err) { alert(err.message) }
    }))
  }

  // modal de conexão: aceite -> QR / código / senha -> conectado
  const modal = $('#m-conectar')
  modal.addEventListener('click', (e) => { if (e.target === modal || e.target.closest('[data-fechar]')) fecharModal() })
  let poll = null
  function fecharModal() { modal.hidden = true; clearTimeout(poll); carregarContas(); carregarConta() }
  $('#nova-conta').onclick = () => {
    modal.hidden = false
    $('#mc-corpo').innerHTML = `<h3 id="mc-tit">Conectar ${esc(window.MARCA.rede)}</h3><p>${esc(window.MARCA.conecta)}</p>
      <label class="check"><input type="checkbox" id="mc-aceite"> <span>Entendo que a conexão funciona como um aparelho conectado à minha conta, não é a API oficial, e que a rede pode pedir para eu entrar de novo. Li os <a href="/termos" target="_blank">termos</a>.</span></label>
      ${window.MARCA.codigo === 'whats' ? `<label class="check"><input type="checkbox" id="mc-par"> <span>Prefiro código de pareamento (sem QR)</span></label>` : ''}
      <button class="btn btn-pri" style="width:100%" id="mc-ir">Continuar</button><div class="msg" id="mc-msg"></div>`
    $('#mc-ir').onclick = async () => {
      if (!$('#mc-aceite').checked) return ($('#mc-msg').textContent = 'Marque o aceite para continuar.', $('#mc-msg').className = 'msg erro')
      try { abrirLogin(await post('/api/contas', window.MARCA.codigo === 'whats' ? { aceite: true, fluxo: $('#mc-par')?.checked ? 'phone' : 'qr' } : { aceite: true })) } catch (err) { $('#mc-msg').textContent = err.message; $('#mc-msg').className = 'msg erro' }
    }
  }
  function svgQR(dado) {
    const q = qrcode(0, 'M'); q.addData(dado); q.make()
    return q.createSvgTag({ cellSize: 5, margin: 2, scalable: false })
  }
  function abrirLogin(v) {
    modal.hidden = false
    clearTimeout(poll)
    const corpo = $('#mc-corpo')
    if (v.estado === 'connected') {
      corpo.innerHTML = `<h3 id="mc-tit">Conectado!</h3><p>${esc(v.rotulo || '')} está pronto. Agora escreva ou revise as regras e teste antes de deixar a IA atender.</p>
        <button class="btn btn-pri" style="width:100%" id="mc-fim">Ir para as regras</button>`
      $('#mc-fim').onclick = () => { fecharModal(); abrirAba('regras') }
      return
    }
    const p = v.passo || {}
    const erro = p.erro ? `<div class="msg erro">${esc(p.erro)}</div>` : ''
    if (p.qr) {
      corpo.innerHTML = `<h3 id="mc-tit">Leia o QR</h3><p>${esc(window.MARCA.conecta)}</p><div class="qr">${svgQR(p.qr)}</div><p class="dim" style="text-align:center;font-size:13px">O código se renova sozinho. Esta janela fecha quando conectar.</p>${erro}`
    } else if (p.codigo_pareamento) {
      corpo.innerHTML = `<h3 id="mc-tit">Código de pareamento</h3><p>No WhatsApp: Aparelhos conectados → Conectar com número de telefone. Digite:</p><div class="cod-par">${esc(p.codigo_pareamento)}</div>${erro}`
    } else if ((p.campos || []).length) {
      const ROT = { username: 'Usuário ou e-mail', password: 'Senha', '2fa_code': 'Código de verificação', text: 'Resposta', phone: 'Telefone com DDD' }
      corpo.innerHTML = `<h3 id="mc-tit">${p.tipo === 'code_2fa' ? 'Código de verificação' : 'Entrar na conta'}</h3>
        <p>${p.tipo === 'code_2fa' ? 'A rede mandou um código para o seu celular ou e-mail.' : 'Digitado só aqui, vai direto para a conexão e não fica guardado.'}</p>
        <form id="mc-form">${p.campos.map((c) => `<label for="f-${esc(c.id)}">${esc(ROT[c.type] || c.label_key || c.id)}</label><input id="f-${esc(c.id)}" name="${esc(c.id)}" type="${c.secret ? 'password' : 'text'}" autocomplete="off" required>`).join('')}
        <button class="btn btn-pri" style="width:100%;margin-top:16px">Continuar</button></form>${erro}`
      $('#mc-form').onsubmit = async (e) => {
        e.preventDefault()
        const dados = Object.fromEntries(new FormData(e.target).entries())
        e.target.querySelector('button').disabled = true
        try { abrirLogin(await post(`/api/contas/${v.id}/passo`, { passo: p.id, tipo: p.tipo, dados })) } catch (err) { alert(err.message); e.target.querySelector('button').disabled = false }
      }
      return
    } else {
      corpo.innerHTML = `<h3 id="mc-tit">Conectando…</h3><p>${p.tipo === 'await_approval' ? 'Confirme o acesso no app do seu celular.' : 'Aguarde alguns segundos.'}</p>${erro}`
    }
    poll = setTimeout(async () => { try { abrirLogin(await api('/api/contas/' + v.id)) } catch {} }, Math.max(2, p.espera_s || 3) * 1000)
  }

  // ------------------------------------------------ plano
  async function carregarPlano() {
    await carregarConta()
    const c = CONTA
    $('#meu-plano').innerHTML = c.assinante ? `<h3>Plano ${esc(c.planos.find((p) => p.codigo === c.plano)?.nome || c.plano)}</h3>
      <p class="dim">Vale até ${new Date(c.ativo_ate * 1000).toLocaleDateString('pt-BR')} · ${c.contas}/${c.limite_contas} conta(s) · ${c.usadas.toLocaleString('pt-BR')}/${c.limite_msgs.toLocaleString('pt-BR')} respostas da IA neste mês</p>`
      : `<h3>Sem plano ativo</h3><p class="dim">Escolha um plano para conectar e ligar a IA.</p>`
    $('#lista-planos').innerHTML = c.planos.map((p) => `<div class="plano ${p.codigo === c.plano ? 'destaque' : ''}"><h3>${esc(p.nome)}</h3><div class="preco">R$ ${p.preco.toFixed(2).replace('.', ',')}<small>/mês</small></div>
      <ul>${p.itens.map((x) => `<li>${esc(x)}</li>`).join('')}</ul>${p.codigo === c.plano ? '<button class="btn btn-sec" disabled>Seu plano</button>' : p.checkout ? `<a class="btn btn-pri" href="${esc(p.checkout)}">Assinar</a>` : '<button class="btn btn-sec" disabled>Em breve</button>'}</div>`).join('')
  }

  carregarConta().catch(() => {})
  abrirAba((location.hash || '#conversas').slice(1) in { conversas: 1, regras: 1, contas: 1, plano: 1 } ? location.hash.slice(1) || 'conversas' : 'conversas')
  setInterval(() => { if (!$('[data-painel=conversas]').hidden && !document.hidden) carregarConversas() }, 8000)
})()
