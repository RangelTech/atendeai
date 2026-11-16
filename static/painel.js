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
    ;({ conversas: carregarConversas, regras: carregarSkill, voz: carregarVoz, contas: carregarContas, plano: carregarPlano })[nome]?.()
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
        <div class="acoes">${c.modo_teste ? (c.liberada ? '<button class="btn btn-ghost sm" id="bloquear">Tirar do teste</button>' : '<button class="btn btn-pri sm" id="liberar">Liberar IA nesta conversa</button>') : ''}
        ${c.modo === 'humano' ? '<button class="btn btn-sec sm" id="devolver">Devolver para a IA</button>' : '<button class="btn btn-sec sm" id="assumir">Assumir conversa</button>'}</div></div>
      <div class="conv-msgs">${c.mensagens.map((m) => `<div class="fala ${m.direcao === 'eco' ? 'humano' : esc(m.direcao)}">${m.audio ? `<audio controls preload="none" src="/api/audios/${esc(m.audio)}"></audio>` : ''}${esc(m.texto)}<span class="quem">${QUEM[m.direcao] || ''} · ${hora(m.criado)}</span></div>`).join('')}</div>
      <form class="conv-env" id="env"><input id="env-txt" placeholder="Escreva como você (a IA para nesta conversa)" autocomplete="off"><button class="btn btn-pri">Enviar</button></form>`
    if (rolarFim) { const m = $('.conv-msgs', d); m.scrollTop = m.scrollHeight }
    $('#liberar', d)?.addEventListener('click', async () => { await post(`/api/conversas/${id}/liberar`); abrirConversa(id) })
    $('#bloquear', d)?.addEventListener('click', async () => { await post(`/api/conversas/${id}/bloquear`); abrirConversa(id) })
    $('#assumir', d)?.addEventListener('click', async () => { await post(`/api/conversas/${id}/assumir`); abrirConversa(id) ; carregarConversas() })
    $('#devolver', d)?.addEventListener('click', async () => { await post(`/api/conversas/${id}/devolver`); abrirConversa(id); carregarConversas() })
    $('#env', d).onsubmit = async (e) => {
      e.preventDefault()
      const t = $('#env-txt').value.trim()
      if (!t) return
      try { await post(`/api/conversas/${id}/enviar`, { texto: t }); $('#env-txt').value = ''; abrirConversa(id) } catch (err) { alert(err.message) }
    }
  }

  // ------------------------------------------------ skills (cada '## Título' do texto é um arquivo de skill)
  const DIAS = ['Seg', 'Ter', 'Qua', 'Qui', 'Sex', 'Sáb', 'Dom']
  $('#sk-dias').innerHTML = DIAS.map((d, i) => `<label><input type="checkbox" value="${i}"><span>${d}</span></label>`).join('')
  const skMsg = (t, tipo = '') => { $('#sk-msg').textContent = t; $('#sk-msg').className = 'msg ' + tipo }
  const MODELOS = [
    ['Sobre o negócio', 'Nome do negócio, cidade e bairro.\nO que vendemos e para quem.\nDiferenciais (por que comprar aqui).'],
    ['Produtos e preços', '- Produto 1: R$ 00,00 (tamanho, sabores)\n- Produto 2: R$ 00,00\nCombos e promoções da semana:'],
    ['Perguntas frequentes', 'P: Vocês entregam?\nR: \nP: Tem estacionamento?\nR: \nP: Aceitam encomenda?\nR: '],
    ['Entrega e retirada', 'Bairros atendidos e taxa de cada um:\nTempo médio de entrega:\nPedido mínimo:\nRetirada no local: endereço e horário.'],
    ['Formas de pagamento', 'Pix (chave):\nCartão na entrega: sim/não\nDinheiro com troco: sim/não\nParcelamento:'],
    ['Trocas e devoluções', 'Prazo para troca:\nComo pedir:\nQuando não trocamos:'],
    ['Tom de voz', 'Fale como o dono: próximo, educado e direto.\nUse o nome do cliente.\nEmojis com moderação.\nRespostas curtas (até 3 frases).'],
    ['Quando chamar o dono', 'Reclamação, pedido de desconto, negociação, cancelamento ou qualquer coisa que não esteja nas skills: responda o que souber e diga que vai chamar o responsável.'],
    ['Nunca fazer', 'Nunca dar desconto sem o dono.\nNunca prometer prazo que não está escrito aqui.\nNunca inventar preço ou produto.'],
    ['Agenda e horários', 'Horário de funcionamento por dia:\nComo agendar:\nAntecedência mínima:'],
  ]
  let SK = [], OFF = new Set(), SEL = 0
  const contar = (t) => `${(t || '').length} caracteres`
  function separar(texto) {
    const partes = (texto || '').split(/^(?=## )/m).map((p) => p.trim()).filter(Boolean)
    const out = []
    for (const p of partes) {
      if (p.startsWith('## ')) { const [t, ...r] = p.slice(3).split('\n'); out.push({ titulo: t.trim(), corpo: r.join('\n').trim() }) }
      else out.push({ titulo: 'Geral', corpo: p })
    }
    return out
  }
  const juntar = () => SK.filter((x) => x.titulo.trim()).map((x) => `## ${x.titulo.trim()}\n${x.corpo.trim()}`).join('\n\n')
  function guardarEditor() { const x = SK[SEL]; if (!x) return; const antigo = x.titulo; x.titulo = $('#sk-titulo').value.trim() || 'Sem nome'; x.corpo = $('#sk-corpo').value
    if (antigo !== x.titulo && OFF.has(antigo)) { OFF.delete(antigo); OFF.add(x.titulo) }
    if ($('#sk-ativa').checked) OFF.delete(x.titulo); else OFF.add(x.titulo) }
  function desenharIndice() {
    const ligadas = SK.filter((x) => !OFF.has(x.titulo)).length
    $('#sk-resumo').textContent = `${SK.length} skills · ${ligadas} ligadas · ${juntar().length} caracteres`
    $('#sk-lista').innerHTML = SK.length ? SK.map((x, i) => `<button class="sk-item ${i === SEL ? 'atual' : ''} ${OFF.has(x.titulo) ? 'off' : ''}" data-sk-i="${i}">
      <span class="sk-arq">${String(i + 1).padStart(2, '0')}</span><span class="sk-nome"><b>${esc(x.titulo)}</b><small>${OFF.has(x.titulo) ? 'desligada' : contar(x.corpo)}</small></span></button>`).join('')
      : '<p class="vazio">Nenhuma skill ainda. Use um modelo ou o chat ao lado.</p>'
    $$('[data-sk-i]').forEach((b) => (b.onclick = () => { guardarEditor(); SEL = +b.dataset.skI; abrirSkill() }))
  }
  function abrirSkill() {
    const x = SK[SEL]
    $('.sk-editor').classList.toggle('vazio-ed', !x)
    $('#sk-titulo').value = x ? x.titulo : ''; $('#sk-corpo').value = x ? x.corpo : ''; $('#sk-ativa').checked = x ? !OFF.has(x.titulo) : false
    $('#sk-cont').textContent = x ? contar(x.corpo) : ''
    desenharIndice()
  }
  $('#sk-corpo').oninput = () => { $('#sk-cont').textContent = contar($('#sk-corpo').value) }
  $('#sk-titulo').onchange = () => { guardarEditor(); desenharIndice() }
  $('#sk-ativa').onchange = () => { guardarEditor(); desenharIndice() }
  $('#sk-nova').onclick = () => { guardarEditor(); SK.push({ titulo: 'Nova skill', corpo: '' }); SEL = SK.length - 1; abrirSkill(); $('#sk-titulo').select() }
  $('#sk-excluir').onclick = () => { if (!SK[SEL] || !confirm(`Excluir a skill "${SK[SEL].titulo}"?`)) return; OFF.delete(SK[SEL].titulo); SK.splice(SEL, 1); SEL = Math.max(0, SEL - 1); abrirSkill() }
  $('#sk-modelos').innerHTML = MODELOS.map(([t], i) => `<button class="sk-modelo" data-mod="${i}">+ ${esc(t)}</button>`).join('')
  $$('[data-mod]').forEach((b) => (b.onclick = () => { guardarEditor(); const [t, c] = MODELOS[+b.dataset.mod]; const j = SK.findIndex((x) => x.titulo === t)
    if (j >= 0) SEL = j; else { SK.push({ titulo: t, corpo: c }); SEL = SK.length - 1 } abrirSkill() }))
  $$('[data-sk]').forEach((b) => (b.onclick = () => { $$('[data-sk]').forEach((x) => x.setAttribute('aria-selected', String(x === b))); $$('[data-skp]').forEach((p) => (p.hidden = p.dataset.skp !== b.dataset.sk)) }))
  function desenharChat(hist) {
    const c = $('#sk-chat')
    c.innerHTML = (hist.length ? '' : `<div class="fala assistant">Vou te fazer algumas perguntas e montar as skills do seu atendente. Para começar: o que você vende e para quem?</div>`) +
      hist.map((h) => `<div class="fala ${h.papel === 'user' ? 'user' : 'assistant'}">${esc(h.texto)}</div>`).join('')
    c.scrollTop = c.scrollHeight
  }
  async function carregarSkill() {
    const s = await api('/api/skill')
    SK = separar(s.texto); OFF = new Set(s.desligadas || []); SEL = Math.min(SEL, Math.max(0, SK.length - 1))
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
    abrirSkill()
    $('#sk-versoes').innerHTML = s.versoes.length ? s.versoes.map((v, i) => `<div class="versao"><div><b>${hora(v.criado)}</b> <span class="dim">${esc(v.autor)}${i === 0 ? ' · atual' : ''}</span><p>${esc(v.inicio)}</p></div>
      ${i ? `<button class="btn btn-ghost sm" data-v="${v.id}">Voltar</button>` : ''}</div>`).join('') : '<p class="vazio">Nenhuma versão salva ainda.</p>'
    $$('[data-v]').forEach((b) => (b.onclick = async () => { if (!confirm('Voltar para esta versão das skills?')) return; await post(`/api/skill/versoes/${b.dataset.v}/restaurar`); carregarSkill() }))
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
      if (r.pronta) skMsg('Skills prontas e salvas. Teste na aba Testar antes de ligar.', 'ok')
    } catch (err) { skMsg(err.message, 'erro') }
    carregarSkill()
  }
  $('#sk-salvar').onclick = async () => {
    guardarEditor()
    const ini = $('#sk-ini').value, fim = $('#sk-fim').value
    const dias = $$('#sk-dias input:checked').map((i) => +i.value)
    const nomes = new Set(SK.map((x) => x.titulo))
    try {
      await api('/api/skill', { method: 'PUT', body: JSON.stringify({ texto: juntar(), desligadas: [...OFF].filter((t) => nomes.has(t)), palavras_humano: $('#sk-palavras').value, fora_horario: $('#sk-fora').value,
        horario: ini && fim ? { inicio: ini, fim, dias } : null }) })
      skMsg('Salvo. A IA já usa as skills ligadas.', 'ok')
      carregarSkill()
    } catch (err) { skMsg(err.message, 'erro') }
  }

  // ------------------------------------------------ minha voz (plano Voz, só WhatsApp)
  if (window.MARCA.codigo === 'whats') $('#aba-voz').hidden = false
  let REC = null, PEDACOS = [], T0 = 0, TIMER = null
  const vozMsg = (t, tipo = '') => { $('#voz-msg').textContent = t; $('#voz-msg').className = 'msg ' + tipo }
  async function carregarVoz() {
    const v = await api('/api/voz')
    const e = v.estado || {}, min = e.minutos || 0
    const ETAPA = { pronta: 'Voz pronta', treinando: 'Treinando a sua voz…', preparando: 'Preparando…', erro: 'O treino falhou' }
    $('#voz-status').innerHTML = `<b>${esc(ETAPA[e.etapa] || (min ? 'Gravações recebidas' : 'Ainda sem gravações'))}</b><span class="dim">${e.amostras || 0} áudios · ${String(min).replace('.', ',')} min</span>`
    $('#voz-barra').style.width = Math.min(100, (min / v.minimo_minutos) * 100) + '%'
    $('#voz-total').textContent = min >= v.minimo_minutos ? 'Já dá para treinar. Mais minutos deixam a voz mais natural.' : `Faltam ${Math.max(0, v.minimo_minutos - min).toFixed(1).replace('.', ',')} min para poder treinar.`
    $('#voz-treinar').disabled = min < v.minimo_minutos || e.etapa === 'treinando'
    $('#voz-ouvir').disabled = !e.pronta
    $('#voz-contas').innerHTML = v.contas.length ? v.contas.map((k) => `<div class="conta-linha"><b>${esc(k.rotulo || 'WhatsApp')}</b>
      <select class="sel-voz" data-voz="${k.id}"><option value="desligado" ${k.voz_modo === 'desligado' ? 'selected' : ''}>Respostas em texto</option>
      <option value="quando_audio" ${k.voz_modo === 'quando_audio' ? 'selected' : ''}>Áudio quando o cliente mandar áudio</option>
      <option value="sempre" ${k.voz_modo === 'sempre' ? 'selected' : ''}>Sempre em áudio</option></select></div>`).join('') : '<p class="vazio">Conecte o WhatsApp para escolher.</p>'
    $$('#voz-contas [data-voz]').forEach((sel) => (sel.onchange = async () => { try { await post(`/api/contas/${sel.dataset.voz}/voz_${sel.value}`); vozMsg('Preferência salva.', 'ok') } catch (err) { vozMsg(err.message, 'erro') } }))
    if (e.etapa === 'treinando') setTimeout(() => { if (!$('[data-painel=voz]').hidden) carregarVoz() }, 15000)
  }
  async function enviarAmostra(blob, nome) {
    vozMsg(`Enviando ${nome}…`)
    const r = await fetch('/api/voz/amostras', { method: 'POST', body: blob, headers: { 'Content-Type': blob.type || 'audio/webm' } })
    if (!r.ok) { let j = {}; try { j = await r.json() } catch {} throw new Error(j.detail || 'Não consegui enviar o áudio.') }
  }
  $('#voz-rec').onclick = async () => {
    if (REC) { REC.stop(); return }
    try {
      const st = await navigator.mediaDevices.getUserMedia({ audio: true })
      REC = new MediaRecorder(st); PEDACOS = []
      REC.ondataavailable = (e) => PEDACOS.push(e.data)
      REC.onstop = async () => { st.getTracks().forEach((t) => t.stop()); clearInterval(TIMER); $('#voz-rec').textContent = '● Gravar'; const b = new Blob(PEDACOS, { type: REC.mimeType }); REC = null
        try { await enviarAmostra(b, 'gravação'); vozMsg('Gravação enviada.', 'ok'); carregarVoz() } catch (err) { vozMsg(err.message, 'erro') } }
      REC.start(); T0 = Date.now(); $('#voz-rec').textContent = '■ Parar e enviar'
      TIMER = setInterval(() => { const s = Math.floor((Date.now() - T0) / 1000); $('#voz-tempo').textContent = `${String(Math.floor(s / 60)).padStart(2, '0')}:${String(s % 60).padStart(2, '0')}` }, 500)
    } catch { vozMsg('Libere o microfone no navegador para gravar.', 'erro') }
  }
  $('#voz-arq').onchange = async (e) => {
    for (const f of e.target.files) { try { await enviarAmostra(f, f.name) } catch (err) { vozMsg(err.message, 'erro'); break } }
    e.target.value = ''; vozMsg('Áudios enviados.', 'ok'); carregarVoz()
  }
  $('#voz-treinar').onclick = async () => { try { await post('/api/voz/treinar'); vozMsg('Treino iniciado. Leva alguns minutos; pode sair desta tela.', 'ok'); carregarVoz() } catch (err) { vozMsg(err.message, 'erro') } }
  $('#voz-ouvir').onclick = async () => {
    vozMsg('Gerando o áudio…')
    const r = await fetch('/api/voz/exemplo', { method: 'POST', headers: { 'Content-Type': 'application/json' }, body: JSON.stringify({ texto: $('#voz-frase').value }) })
    if (!r.ok) { vozMsg('A voz ainda não está pronta.', 'erro'); return }
    const p = $('#voz-player'); p.src = URL.createObjectURL(await r.blob()); p.hidden = false; p.play(); vozMsg('')
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
        <p class="dim" style="font-size:13px">IA ${k.ia_ligada ? 'ligada' : 'desligada'} nesta conta${k.modo_teste ? ' · <b>modo teste</b>: só responde as conversas que você liberar' : ''}</p></div>
      <div class="acoes">
        ${k.estado === 'connected' ? '' : `<button class="btn btn-pri sm" data-k="${k.id}" data-a="${k.estado === 'pending_auth' || k.estado.startsWith('awaiting') ? 'continuar' : 'reconectar'}">${k.estado === 'pending_auth' || k.estado.startsWith('awaiting') ? 'Continuar' : 'Reconectar'}</button>`}
        <button class="btn btn-sec sm" data-k="${k.id}" data-a="${k.ia_ligada ? 'desligar_ia' : 'ligar_ia'}">${k.ia_ligada ? 'Pausar IA' : 'Ligar IA'}</button>
        ${window.MARCA.codigo === 'whats' ? `<select class="sel-voz" data-voz="${k.id}" title="Responder em áudio com a sua voz (plano Voz)">
          <option value="desligado" ${k.voz_modo === 'desligado' ? 'selected' : ''}>Respostas em texto</option>
          <option value="quando_audio" ${k.voz_modo === 'quando_audio' ? 'selected' : ''}>Áudio quando o cliente mandar áudio</option>
          <option value="sempre" ${k.voz_modo === 'sempre' ? 'selected' : ''}>Sempre em áudio</option></select>` : ''}
        <button class="btn btn-ghost sm" data-k="${k.id}" data-a="${k.modo_teste ? 'desligar_teste' : 'ligar_teste'}" title="Com o modo teste, a IA só responde as conversas que você liberar">${k.modo_teste ? 'Sair do modo teste' : 'Modo teste'}</button>
        ${k.estado === 'connected' ? `<button class="btn btn-ghost sm" data-k="${k.id}" data-a="desconectar">Desconectar</button>` : ''}
        <button class="btn btn-ghost sm perigo" data-k="${k.id}" data-a="excluir">Excluir</button></div></div>`).join('')
      : `<p class="vazio">Nenhuma conta conectada. ${esc(window.MARCA.conecta)}</p>`
    $$('[data-voz]').forEach((sel) => (sel.onchange = async () => {
      try { await post(`/api/contas/${sel.dataset.voz}/voz_${sel.value}`) } catch (err) { alert(err.message) }
      carregarContas()
    }))
    $$('[data-k]').forEach((b) => (b.onclick = async () => {
      const id = b.dataset.k, a = b.dataset.a
      if (a === 'desconectar' && !confirm('Desconectar esta conta? A IA para de responder até você conectar de novo.')) return
      if (a === 'excluir' && !confirm('Excluir esta conexão? Ela sai da lista e as conversas dela são apagadas daqui.')) return
      try {
        if (a === 'excluir') { await api('/api/contas/' + id, { method: 'DELETE' }); carregarContas(); carregarConta(); return }
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
  let tentativa = null  // conexão aberta no modal que ainda não conectou: some ao fechar
  async function fecharModal() {
    modal.hidden = true; clearTimeout(poll)
    if (tentativa) { const id = tentativa; tentativa = null; try { await api('/api/contas/' + id, { method: 'DELETE' }) } catch {} }
    carregarContas(); carregarConta()
  }
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
    tentativa = v.estado === 'connected' || v.ja_conectou ? null : v.id
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
      const ROT = { username: 'Usuário ou e-mail', password: 'Senha', '2fa_code': 'Código de verificação', captcha_code: 'Digite os caracteres da imagem', text: 'Resposta', phone_number: 'Telefone com DDD', phone: 'Telefone com DDD', email: 'E-mail', select: 'Escolha' }
      const TIT = { code_2fa: ['Código de verificação', 'A rede mandou um código para o seu celular ou e-mail.'],
        captcha: ['Confirme que é você', 'A rede pediu um desafio. Digite exatamente o que aparece na imagem.'],
        choice: ['Escolha uma opção', 'A rede pediu para você escolher como continuar.'] }
      const [tit, sub] = TIT[p.tipo] || ['Entrar na conta', 'Digitado só aqui, vai direto para a conexão e não fica guardado.']
      const imgs = (p.imagens || []).map((src) => `<img class="desafio" src="${src}" alt="Imagem do desafio">`).join('')
      const campo = (c) => c.type === 'select' && (c.options || []).length
        ? `<select id="f-${esc(c.id)}" name="${esc(c.id)}" required>${c.options.map((o) => `<option value="${esc(o)}">${esc(o)}</option>`).join('')}</select>`
        : `<input id="f-${esc(c.id)}" name="${esc(c.id)}" type="${c.secret ? 'password' : 'text'}" autocomplete="off" required>`
      corpo.innerHTML = `<h3 id="mc-tit">${tit}</h3><p>${sub}</p>${imgs}
        <form id="mc-form">${p.campos.map((c) => `<label for="f-${esc(c.id)}">${esc(ROT[c.type] || c.label || c.id)}</label>${campo(c)}`).join('')}
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
  abrirAba((location.hash || '#conversas').slice(1) in { conversas: 1, regras: 1, voz: 1, contas: 1, plano: 1 } ? location.hash.slice(1) || 'conversas' : 'conversas')
  setInterval(() => { if (!$('[data-painel=conversas]').hidden && !document.hidden) carregarConversas() }, 8000)
})()
