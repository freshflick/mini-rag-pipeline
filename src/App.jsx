import React, { useEffect, useRef, useState } from 'react'
import { Activity, ArrowRight, BookOpen, Check, ChevronDown, ChevronRight, Database, FileJson, FileText, Layers3, Play, Search, ShieldCheck, Sparkles, UploadCloud } from './icons.jsx'

const STAGES = ['INIT', 'DOCUMENTS_LOADED', 'DOCUMENTS_CHUNKED', 'INDEX_BUILT', 'RETRIEVAL_COMPLETE', 'ANSWERS_GENERATED', 'EVALUATION_COMPLETE', 'VALIDATION_COMPLETE', 'RESULTS_FINALISED']
const stageLabel = { INIT: 'Initialize', DOCUMENTS_LOADED: 'Load documents', DOCUMENTS_CHUNKED: 'Chunk content', INDEX_BUILT: 'Build index', RETRIEVAL_COMPLETE: 'Retrieve evidence', ANSWERS_GENERATED: 'Generate answers', EVALUATION_COMPLETE: 'Evaluate retrieval', VALIDATION_COMPLETE: 'Validate output', RESULTS_FINALISED: 'Finalize results' }

async function api(path, options = {}) {
  const response = await fetch(`/api${path}`, { headers: { 'Content-Type': 'application/json' }, ...options })
  const data = await response.json()
  if (!response.ok) throw new Error(data.error || `Request failed (${response.status})`)
  return data
}

async function readUtf8(file) {
  try { return new TextDecoder('utf-8', { fatal: true }).decode(await file.arrayBuffer()) }
  catch { throw new Error(`${file.name} is not valid UTF-8 text.`) }
}

const pct = value => `${Math.round((value || 0) * 100)}%`

function Stat({ label, value, helper, icon: Icon, accent }) {
  return <div className="stat-card">
    <div className={`stat-icon ${accent || ''}`}><Icon size={18} strokeWidth={2} /></div>
    <div className="stat-value">{value}</div>
    <div className="stat-label">{label}</div>
    <div className="stat-helper">{helper}</div>
  </div>
}

function SectionTitle({ eyebrow, title, aside }) {
  return <div className="section-title"><div><div className="eyebrow">{eyebrow}</div><h2>{title}</h2></div>{aside}</div>
}

export default function App() {
  const [state, setState] = useState(null)
  const [loading, setLoading] = useState(false)
  const [uploading, setUploading] = useState(false)
  const [error, setError] = useState('')
  const [notice, setNotice] = useState('')
  const [question, setQuestion] = useState('')
  const [answer, setAnswer] = useState(null)
  const [asking, setAsking] = useState(false)
  const [activeTab, setActiveTab] = useState('evaluation')
  const [activeQuery, setActiveQuery] = useState(0)
  const [replace, setReplace] = useState(false)
  const [dragging, setDragging] = useState(false)
  const docsInput = useRef(null)
  const queriesInput = useRef(null)

  async function refresh() {
    try { setState(await api('/state')) } catch (err) { setError(err.message) }
  }
  useEffect(() => { refresh() }, [])

  async function run() {
    setLoading(true); setError(''); setNotice('')
    try { await api('/run', { method: 'POST', body: '{}' }); await refresh(); setNotice('Pipeline replayed. All artifacts were regenerated and validated.') }
    catch (err) { setError(err.message) }
    finally { setLoading(false) }
  }

  async function ask(event) {
    event.preventDefault()
    if (!question.trim()) return
    setAsking(true); setError(''); setAnswer(null)
    try { setAnswer(await api('/ask', { method: 'POST', body: JSON.stringify({ question }) })) }
    catch (err) { setError(err.message) }
    finally { setAsking(false) }
  }

  async function uploadDocs(files) {
    const picked = Array.from(files || [])
    if (!picked.length) return
    setUploading(true); setError(''); setNotice('')
    try {
      const items = await Promise.all(picked.map(async file => ({ name: file.name, content: await readUtf8(file) })))
      await api('/documents', { method: 'POST', body: JSON.stringify({ files: items, replace }) })
      await refresh(); setNotice(`${items.length} document${items.length === 1 ? '' : 's'} saved. Replay the pipeline to update results.`)
    } catch (err) { setError(err.message) }
    finally { setUploading(false); setDragging(false); if (docsInput.current) docsInput.current.value = '' }
  }

  async function uploadQueries(file) {
    if (!file) return
    setUploading(true); setError(''); setNotice('')
    try {
      const queries = JSON.parse(await readUtf8(file))
      await api('/queries', { method: 'POST', body: JSON.stringify({ queries }) })
      setNotice(`${queries.length} evaluation queries saved. Replay the pipeline to update results.`)
    } catch (err) { setError(err.message) }
    finally { setUploading(false); if (queriesInput.current) queriesInput.current.value = '' }
  }

  const summary = state?.stale ? null : state?.evaluation?.summary
  const manifest = state?.stale ? null : state?.manifest
  const records = state?.stale ? [] : state?.evaluation?.records || []
  const answers = state?.stale ? [] : state?.answers || []
  const retrieval = state?.stale ? [] : state?.retrieval || []
  const selected = records[activeQuery]
  const selectedAnswer = answers.find(row => row.query_id === selected?.query_id)
  const selectedRetrieval = retrieval.find(row => row.query_id === selected?.query_id)
  const completed = manifest?.stages || []

  return <div className="app-shell">
    <aside className="sidebar">
      <div className="brand"><div className="brand-mark"><Layers3 size={22} /></div><div><strong>mini<span>RAG</span></strong><small>REPLAY LAB</small></div></div>
      <div className="side-group"><div className="side-heading">WORKSPACE</div><a className="side-link active" href="#overview"><Activity size={17} /> Overview</a><a className="side-link" href="#knowledge"><Database size={17} /> Knowledge base</a><a className="side-link" href="#ask"><Search size={17} /> Ask a question</a><a className="side-link" href="#evaluation"><ShieldCheck size={17} /> Evaluation</a></div>
      <div className="side-group stages"><div className="side-heading">PIPELINE STAGES</div>{STAGES.slice(1).map((stage, i) => <div className="stage" key={stage}><span className={`stage-dot ${completed.includes(stage) ? 'done' : ''}`}>{completed.includes(stage) ? <Check size={10} strokeWidth={3} /> : i + 1}</span><span>{stageLabel[stage]}</span></div>)}</div>
      <div className="sidebar-bottom"><div className="status-light" /> <span>Local & deterministic</span><span className="version">v1.0</span></div>
    </aside>

    <main className="main">
      <header className="topbar"><div className="breadcrumbs"><span>Workspace</span><ChevronRight size={14} /><strong>Overview</strong></div><div className="topbar-right"><span className="top-badge"><span /> LOCAL PIPELINE</span></div></header>
      <div className="content">
        <section id="overview" className="hero"><div className="hero-copy"><div className="hero-kicker"><Sparkles size={14} /> REPLAYABLE MINI-RAG</div><h1>From product knowledge<br />to answers you can trust.</h1><p>Ingest your documents, trace every answer to its source, and measure retrieval quality in one transparent workspace.</p><div className="hero-actions"><button className="primary-button" onClick={run} disabled={loading || uploading}><Play size={16} fill="currentColor" />{loading ? 'Running pipeline…' : 'Run pipeline'}<ArrowRight size={16} /></button><a className="text-link" href="#knowledge">Explore sources <ArrowRight size={15} /></a></div></div><div className="hero-art" aria-hidden="true"><div className="orbit orbit-one"/><div className="orbit orbit-two"/><div className="node node-a"><FileText size={17} /></div><div className="node node-b"><Search size={17} /></div><div className="node node-c"><ShieldCheck size={17} /></div><div className="center-node"><Layers3 size={32} /></div><div className="flow-line line-a"/><div className="flow-line line-b"/><div className="flow-line line-c"/></div></section>

        {(error || notice) && <div className={`message ${error ? 'error' : 'success'}`} role="status">{error || notice}<button onClick={() => { setError(''); setNotice('') }}>×</button></div>}
        {state?.stale && <div className="message pending" role="status">Inputs changed since the last replay. Run the pipeline to refresh evaluation and validation.</div>}

        <section className="metrics"><Stat icon={BookOpen} label="Documents indexed" value={manifest?.documents_loaded ?? state?.documents?.length ?? '—'} helper="Knowledge sources" /><Stat icon={Layers3} label="Evidence chunks" value={manifest?.chunks_created ?? '—'} helper="Deterministic slices" accent="violet" /><Stat icon={Activity} label="Top-3 hit rate" value={summary ? pct(summary.top3_hit_rate) : '—'} helper={summary ? `${summary.hits} of ${summary.total_queries} queries` : 'Run to calculate'} accent="orange" /><Stat icon={ShieldCheck} label="Validation" value={manifest?.validation?.passed ? 'Passed' : 'Pending'} helper={manifest?.validation?.passed ? 'All checks complete' : 'Awaiting pipeline run'} accent="green" /></section>

        <section id="knowledge" className="knowledge-section"><SectionTitle eyebrow="01 / INPUTS" title="Knowledge base" aside={<span className="section-note">Files on disk · UTF-8 text</span>} /><div className="knowledge-grid"><div className="panel documents-panel"><div className="panel-head"><div><h3>Source documents</h3><p>{state?.documents?.length || 0} files ready for processing</p></div><span className="soft-count">{state?.documents?.length || 0} files</span></div><div className="doc-list">{state?.documents?.map((doc, i) => <div className="doc-item" key={`${doc.path}-${i}`}><div className="doc-icon"><FileText size={18} /></div><div className="doc-info"><strong>{doc.title}</strong><span>{doc.section} <i>·</i> {doc.path}</span></div><Check className="doc-check" size={16} /></div>)}</div></div><div className="panel upload-panel"><div className="upload-head"><div className="upload-icon"><UploadCloud size={22} /></div><h3>Bring your own knowledge</h3><p>Drop product docs here to reindex. Every file goes through the same parser, chunker, and retriever.</p></div><div className={`drop-zone ${dragging ? 'dragging' : ''}`} onDragOver={e => { e.preventDefault(); setDragging(true) }} onDragLeave={() => setDragging(false)} onDrop={e => { e.preventDefault(); uploadDocs(e.dataTransfer.files) }} onClick={() => docsInput.current?.click()} role="button" tabIndex={0} onKeyDown={e => { if (e.key === 'Enter' || e.key === ' ') docsInput.current?.click() }}><UploadCloud size={23} /><strong>{uploading ? 'Uploading…' : 'Click to browse or drag files here'}</strong><span>.txt, .md, .markdown · up to 5 MB per request</span></div><input ref={docsInput} type="file" multiple accept=".txt,.md,.markdown" hidden onChange={e => uploadDocs(e.target.files)} /><label className="replace-row"><input type="checkbox" checked={replace} onChange={e => setReplace(e.target.checked)} /> Replace existing documents on upload</label><div className="upload-footer"><button className="secondary-button" onClick={() => queriesInput.current?.click()}><FileJson size={16} /> Upload queries.json</button><input ref={queriesInput} type="file" accept=".json" hidden onChange={e => uploadQueries(e.target.files?.[0])} /></div></div></div></section>

        <section id="ask" className="ask-section"><SectionTitle eyebrow="02 / EXPLORE" title="Ask your knowledge base" aside={<span className="section-note">Answers cite retrieved chunks</span>} /><div className="ask-card"><div className="ask-intro"><div className="ask-spark"><Sparkles size={19} /></div><div><h3>What would you like to know?</h3><p>Ask a question or enter a specific topic. Responses are selected from evidence in your documents.</p></div></div><form onSubmit={ask} className="question-form"><Search size={19} /><input value={question} onChange={e => setQuestion(e.target.value)} placeholder="e.g. How long does a bank withdrawal take after approval?" aria-label="Question" /><button type="submit" disabled={asking || !question.trim()}>{asking ? 'Searching…' : 'Ask'} <ArrowRight size={16} /></button></form>{answer && <div className="answer-result"><div className="answer-top"><span className={`answer-label ${answer.answer_label}`}>{answer.answer_reason === 'underspecified_question' ? 'More detail needed' : answer.answer_reason === 'topic_overview' ? 'Topic overview' : answer.answer_label.replaceAll('_', ' ')}</span><span>{answer.retrieval?.length || 0} chunks retrieved</span></div><p>{answer.answer}</p><details><summary>Inspect retrieved evidence <ChevronDown size={15} /></summary><div className="evidence-list">{answer.retrieval?.map(hit => <div className="evidence" key={hit.chunk_id}><div><strong>#{hit.rank} {hit.doc_title}</strong><span>score {hit.score.toFixed(3)}</span></div><p>{hit.chunk_text.trim()}</p></div>)}</div></details></div>}</div></section>

        <section id="evaluation" className="evaluation-section"><SectionTitle eyebrow="03 / VERIFY" title="Pipeline results" aside={<span className="section-note">Generated from queries.json</span>} /><div className="results-panel"><div className="tabs" role="tablist"><button role="tab" aria-selected={activeTab === 'evaluation'} className={activeTab === 'evaluation' ? 'selected' : ''} onClick={() => setActiveTab('evaluation')}>Retrieval evaluation</button><button role="tab" aria-selected={activeTab === 'comparison'} className={activeTab === 'comparison' ? 'selected' : ''} onClick={() => setActiveTab('comparison')}>Chunking comparison</button><button role="tab" aria-selected={activeTab === 'trace'} className={activeTab === 'trace' ? 'selected' : ''} onClick={() => setActiveTab('trace')}>Pipeline trace</button></div>
          {activeTab === 'evaluation' && <div className="evaluation-content">{records.length ? <><div className="eval-summary"><div className="rate-ring" style={{ '--progress': `${summary.top3_hit_rate * 100}%` }}><div><strong>{pct(summary.top3_hit_rate)}</strong><span>hit rate</span></div></div><div className="eval-copy"><strong>Retrieval quality at a glance</strong><p>{summary.hits} hit{summary.hits !== 1 ? 's' : ''}, {summary.partial_hits} partial hit{summary.partial_hits !== 1 ? 's' : ''}, and {summary.misses} miss{summary.misses !== 1 ? 'es' : ''} across {summary.total_queries} evaluation queries.</p><div className="legend"><span><i className="green-dot" /> Hit</span><span><i className="yellow-dot" /> Partial</span><span><i className="red-dot" /> Miss</span></div></div></div><div className="query-grid"><div className="query-list">{records.map((row, i) => <button key={row.query_id} className={`query-row ${i === activeQuery ? 'active' : ''}`} onClick={() => setActiveQuery(i)}><span className="query-id">{row.query_id}</span><span className="query-name">{retrieval[i]?.question || row.query_id}</span><span className={`status-pill ${row.retrieval_status}`}>{row.retrieval_status.replace('_', ' ')}</span><ChevronRight size={15} /></button>)}</div><div className="query-detail"><span className="detail-kicker">QUERY DETAIL · {selected?.query_id}</span><h3>{selectedRetrieval?.question}</h3><div className="detail-label">ANSWER</div><p className="detail-answer">{selectedAnswer?.answer}</p><div className="detail-label">TOP RETRIEVED DOCUMENTS</div>{selectedRetrieval?.top_k?.slice(0, 3).map(hit => <div className="rank-row" key={hit.chunk_id}><span>{hit.rank}</span><strong>{hit.doc_title}</strong><em>{hit.score.toFixed(2)}</em></div>)}<div className="detail-explanation"><Check size={15} /> {selected?.explanation}</div></div></div></> : <div className="empty-state"><Activity size={28} /><h3>No evaluation yet</h3><p>Run the pipeline to score your retrieval results against queries.json.</p></div>}</div>}
          {activeTab === 'comparison' && <div className="comparison-content">{!state?.stale && state?.comparison ? <><p className="comparison-intro">Two deterministic chunkers are replayed against the same queries and ranked with the same BM25 index.</p><div className="compare-grid">{Object.entries(state.comparison.strategies).map(([name, metrics]) => <div className="compare-card" key={name}><div className="compare-name"><Layers3 size={18} /> {name === 'paragraph' ? 'Paragraph-aware' : 'Fixed-size'}</div><strong>{pct(metrics.top3_hit_rate)}</strong><span>top-3 hit rate</span><div className="compare-foot">{metrics.chunk_count} chunks created</div></div>)}</div><p className="compare-note">{state.comparison.explanation}</p></> : <div className="empty-state"><Layers3 size={28} /><h3>No comparison yet</h3><p>Run the pipeline to compare chunking strategies.</p></div>}</div>}
          {activeTab === 'trace' && <div className="trace-content">{manifest ? <><p>Every stage completed in order. Artifacts were written and checked before finalization.</p><div className="trace-list">{manifest.stages.map((stage, i) => <div key={stage}><span className="trace-index">{String(i + 1).padStart(2, '0')}</span><span>{stageLabel[stage]}</span><code>{stage}</code><Check size={16} /></div>)}</div>{manifest.warnings?.length > 0 && <div className="warnings"><strong>Ingestion notes</strong>{manifest.warnings.map((warning, i) => <p key={i}>{warning}</p>)}</div>}</> : <div className="empty-state"><Play size={28} /><h3>No run recorded</h3><p>Run the pipeline to see its ordered stages.</p></div>}</div>}</div></section>
        <footer><span>miniRAG Replay Lab</span><span>Deterministic retrieval · Citation-strict answers · Local files</span></footer>
      </div>
    </main>
  </div>
}
