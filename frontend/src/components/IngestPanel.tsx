import { useEffect, useRef, useState } from 'react';
import { apiFetch } from '../api';
import type { Source } from '../types';

interface Props {
  selectedIds: Set<string>;
  onSelectionChange: (ids: Set<string>) => void;
}

function formatWhen(s: Source): string {
  const raw = s.ingested_at ?? s.scraped_at;
  if (!raw) return '';
  const d = new Date(raw);
  if (isNaN(d.getTime())) return '';
  return d.toLocaleDateString(undefined, { month: 'short', day: 'numeric' })
    + ' ' + d.toLocaleTimeString(undefined, { hour: '2-digit', minute: '2-digit' });
}

function sourceLabel(s: Source): string {
  return s.filename ?? s.title ?? s.url ?? s.source_id;
}

const TYPE_ORDER: Source['source_type'][] = ['pdf', 'youtube', 'web'];
const TYPE_LABEL: Record<Source['source_type'], string> = {
  pdf: 'PDF',
  youtube: 'YouTube',
  web: 'Web',
};

export default function IngestPanel({ selectedIds, onSelectionChange }: Props) {
  const [open, setOpen] = useState(false);
  const [activeTab, setActiveTab] = useState<'pdf' | 'youtube' | 'web'>('pdf');
  const [sources, setSources] = useState<Source[]>([]);
  const [pdfFeedback, setPdfFeedback] = useState<{ msg: string; cls: string } | null>(null);
  const [ytUrl, setYtUrl] = useState('');
  const [ytFeedback, setYtFeedback] = useState<{ msg: string; cls: string } | null>(null);
  const [webUrl, setWebUrl] = useState('');
  const [webFeedback, setWebFeedback] = useState<{ msg: string; cls: string } | null>(null);
  const [dragOver, setDragOver] = useState(false);
  const fileInputRef = useRef<HTMLInputElement>(null);

  useEffect(() => { loadSources(); }, []);

  async function loadSources() {
    try {
      const res = await apiFetch('/sources');
      if (res.ok) {
        const data = await res.json() as { sources: Source[] };
        setSources(data.sources ?? []);
      }
    } catch { /* silent */ }
  }

  async function ingestPdf(file: File) {
    setPdfFeedback({ msg: 'Ingesting…', cls: 'busy' });
    const fd = new FormData();
    fd.append('file', file);
    try {
      const res = await apiFetch('/ingest/pdf', { method: 'POST', body: fd });
      const d = await res.json() as { message?: string; detail?: string };
      if (res.ok) {
        setPdfFeedback({ msg: d.message ?? 'Ingested successfully', cls: 'ok' });
        loadSources();
      } else {
        setPdfFeedback({ msg: d.detail ?? 'Error', cls: 'err' });
      }
    } catch {
      setPdfFeedback({ msg: 'Network error', cls: 'err' });
    }
  }

  async function ingestUrl(type: 'youtube' | 'web', url: string) {
    const setFb = type === 'youtube' ? setYtFeedback : setWebFeedback;
    setFb({ msg: 'Ingesting…', cls: 'busy' });
    try {
      const res = await apiFetch(`/ingest/${type}`, {
        method: 'POST',
        headers: { 'Content-Type': 'application/json' },
        body: JSON.stringify({ url }),
      });
      const d = await res.json() as { message?: string; detail?: string };
      if (res.ok) {
        setFb({ msg: d.message ?? 'Ingested successfully', cls: 'ok' });
        if (type === 'youtube') setYtUrl(''); else setWebUrl('');
        loadSources();
      } else {
        setFb({ msg: d.detail ?? 'Error', cls: 'err' });
      }
    } catch {
      setFb({ msg: 'Network error', cls: 'err' });
    }
  }

  async function deleteSource(id: string) {
    await apiFetch(`/sources/${id}`, { method: 'DELETE' });
    setSources(s => s.filter(x => x.source_id !== id));
    if (selectedIds.has(id)) {
      const next = new Set(selectedIds);
      next.delete(id);
      onSelectionChange(next);
    }
  }

  function toggleSelect(id: string) {
    const next = new Set(selectedIds);
    next.has(id) ? next.delete(id) : next.add(id);
    onSelectionChange(next);
  }

  const grouped = TYPE_ORDER.map(type => ({
    type,
    items: sources.filter(s => s.source_type === type),
  })).filter(g => g.items.length > 0);

  const selectionHint = selectedIds.size > 0
    ? `${selectedIds.size} selected`
    : 'all';

  return (
    <div className={`ingest-panel ${open ? 'open' : ''}`}>
      <div className="ingest-summary" onClick={() => setOpen(o => !o)}>
        <svg width="14" height="14" viewBox="0 0 16 16" fill="none" stroke="currentColor" strokeWidth="1.5">
          <path d="M8 11V3M8 3L5 6M8 3l3 3M2 12v1a1 1 0 001 1h10a1 1 0 001-1v-1"/>
        </svg>
        Ingest Source
        <span className="sources-count-badge">{sources.length}</span>
        {sources.length > 0 && (
          <span className="sources-count-badge" style={{ background: selectedIds.size > 0 ? 'var(--accent-dim)' : undefined, color: selectedIds.size > 0 ? 'var(--accent)' : undefined }}>
            {selectionHint}
          </span>
        )}
        <svg className="chevron" width="12" height="12" viewBox="0 0 16 16" fill="none" stroke="currentColor" strokeWidth="1.5">
          <path d="M4 6l4 4 4-4"/>
        </svg>
      </div>

      {open && (
        <div className="ingest-body">
          <div className="tab-strip">
            {(['pdf', 'youtube', 'web'] as const).map(t => (
              <button key={t} className={`tab ${activeTab === t ? 'active' : ''}`} onClick={() => setActiveTab(t)}>
                {TYPE_LABEL[t]}
              </button>
            ))}
          </div>

          {activeTab === 'pdf' && (
            <div className="tab-pane active">
              <div
                className={`drop-zone ${dragOver ? 'drag-over' : ''}`}
                onClick={() => fileInputRef.current?.click()}
                onDragOver={e => { e.preventDefault(); setDragOver(true); }}
                onDragLeave={() => setDragOver(false)}
                onDrop={e => {
                  e.preventDefault();
                  setDragOver(false);
                  const file = e.dataTransfer.files[0];
                  if (file?.type === 'application/pdf') ingestPdf(file);
                }}
              >
                <svg className="drop-icon" viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="1.25">
                  <path d="M12 15V3M12 3L8 7M12 3L16 7"/>
                  <path d="M3 17v2a2 2 0 002 2h14a2 2 0 002-2v-2"/>
                </svg>
                <p className="drop-label">Drop PDF here</p>
                <p className="drop-sub">or <span className="text-link">browse</span></p>
                <input
                  ref={fileInputRef}
                  type="file"
                  accept=".pdf"
                  hidden
                  onChange={e => {
                    const f = e.target.files?.[0];
                    if (f) ingestPdf(f);
                    e.target.value = '';
                  }}
                />
              </div>
              {pdfFeedback && <div className={`ingest-feedback ${pdfFeedback.cls}`}>{pdfFeedback.msg}</div>}
            </div>
          )}

          {activeTab === 'youtube' && (
            <div className="tab-pane active">
              <div className="url-row">
                <input
                  className="url-input"
                  type="url"
                  placeholder="youtube.com/watch?v=…"
                  value={ytUrl}
                  onChange={e => setYtUrl(e.target.value)}
                  onKeyDown={e => { if (e.key === 'Enter' && ytUrl) ingestUrl('youtube', ytUrl); }}
                />
                <button className="pill-btn" onClick={() => ytUrl && ingestUrl('youtube', ytUrl)}>Go</button>
              </div>
              {ytFeedback && <div className={`ingest-feedback ${ytFeedback.cls}`}>{ytFeedback.msg}</div>}
            </div>
          )}

          {activeTab === 'web' && (
            <div className="tab-pane active">
              <div className="url-row">
                <input
                  className="url-input"
                  type="url"
                  placeholder="https://…"
                  value={webUrl}
                  onChange={e => setWebUrl(e.target.value)}
                  onKeyDown={e => { if (e.key === 'Enter' && webUrl) ingestUrl('web', webUrl); }}
                />
                <button className="pill-btn" onClick={() => webUrl && ingestUrl('web', webUrl)}>Go</button>
              </div>
              {webFeedback && <div className={`ingest-feedback ${webFeedback.cls}`}>{webFeedback.msg}</div>}
            </div>
          )}

          <div className="sources-list" style={{ marginTop: 16 }}>
            {sources.length === 0
              ? <p className="empty-hint" style={{ padding: 0 }}>Nothing ingested yet.</p>
              : grouped.map(({ type, items }) => (
                <div key={type} className="source-group">
                  <div className="source-group-header">
                    <span className={`source-type-badge badge-${type}`}>{TYPE_LABEL[type]}</span>
                    <span className="source-group-count">{items.length}</span>
                  </div>
                  {items.map(s => (
                    <div key={s.source_id} className={`source-card ${selectedIds.has(s.source_id) ? 'source-selected' : ''}`}>
                      <input
                        type="checkbox"
                        className="source-checkbox"
                        checked={selectedIds.has(s.source_id)}
                        onChange={() => toggleSelect(s.source_id)}
                        title={selectedIds.size === 0 ? 'Select to restrict search to this source' : 'Toggle source'}
                      />
                      <div className="source-meta">
                        <div className="source-title">{sourceLabel(s)}</div>
                        <div className="source-when">{formatWhen(s)}</div>
                      </div>
                      <button className="source-delete" onClick={() => deleteSource(s.source_id)}>×</button>
                    </div>
                  ))}
                </div>
              ))
            }
          </div>

          {selectedIds.size > 0 && (
            <button
              className="clear-selection-btn"
              onClick={() => onSelectionChange(new Set())}
            >
              Clear selection — search all
            </button>
          )}
        </div>
      )}
    </div>
  );
}
