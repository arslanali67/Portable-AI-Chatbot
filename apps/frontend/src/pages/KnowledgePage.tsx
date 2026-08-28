import { useCallback, useEffect, useState, type FormEvent } from "react";
import { useParams } from "react-router-dom";

import { api } from "../api/client";
import { errorMessage } from "../auth/AuthContext";
import type { KnowledgeDocument, RetrievedChunk } from "../api/types";

export default function KnowledgePage() {
  const { organizationId, chatbotId } = useParams<{
    organizationId: string;
    chatbotId: string;
  }>();
  const orgId = Number(organizationId);
  const botId = Number(chatbotId);

  const [documents, setDocuments] = useState<KnowledgeDocument[]>([]);
  const [loading, setLoading] = useState(true);
  const [error, setError] = useState<string | null>(null);

  const [textName, setTextName] = useState("");
  const [textContent, setTextContent] = useState("");
  const [url, setUrl] = useState("");
  const [urlTitle, setUrlTitle] = useState("");
  const [fileTitle, setFileTitle] = useState("");
  const [file, setFile] = useState<File | null>(null);
  const [saving, setSaving] = useState(false);

  const [searchQuery, setSearchQuery] = useState("");
  const [searchResults, setSearchResults] = useState<RetrievedChunk[] | null>(null);
  const [searching, setSearching] = useState(false);

  const load = useCallback(() => {
    setLoading(true);
    api
      .listDocuments(orgId, botId)
      .then((res) => setDocuments(res.items))
      .catch((err) => setError(errorMessage(err)))
      .finally(() => setLoading(false));
  }, [orgId, botId]);

  useEffect(load, [load]);

  async function ingestText(e: FormEvent) {
    e.preventDefault();
    setSaving(true);
    setError(null);
    try {
      await api.ingestText(orgId, botId, { name: textName, content: textContent });
      setTextName("");
      setTextContent("");
      load();
    } catch (err) {
      setError(errorMessage(err));
      // A failed ingestion still persists a "failed" document server-side
      // (KnowledgeService._run_pipeline commits status="failed" before
      // re-raising) — reload so it appears in the table instead of staying
      // invisible until an unrelated action refreshes the list.
      load();
    } finally {
      setSaving(false);
    }
  }

  async function ingestUrl(e: FormEvent) {
    e.preventDefault();
    setSaving(true);
    setError(null);
    try {
      await api.ingestUrl(orgId, botId, url, urlTitle || undefined);
      setUrl("");
      setUrlTitle("");
      load();
    } catch (err) {
      setError(errorMessage(err));
      load();
    } finally {
      setSaving(false);
    }
  }

  async function ingestFile(e: FormEvent) {
    e.preventDefault();
    if (!file) {
      return;
    }
    setSaving(true);
    setError(null);
    try {
      await api.ingestFile(orgId, botId, file, fileTitle || undefined);
      setFile(null);
      setFileTitle("");
      setError(null);
      load();
    } catch (err) {
      setError(errorMessage(err));
      load();
    } finally {
      setSaving(false);
    }
  }

  async function remove(doc: KnowledgeDocument) {
    if (!window.confirm(`Delete document "${doc.name}"?`)) {
      return;
    }
    try {
      await api.deleteDocument(orgId, botId, doc.id);
      load();
    } catch (err) {
      setError(errorMessage(err));
    }
  }

  async function search(e: FormEvent) {
    e.preventDefault();
    const q = searchQuery.trim();
    if (!q) {
      return;
    }
    setSearching(true);
    setError(null);
    try {
      const res = await api.searchKnowledge(orgId, botId, q);
      setSearchResults(res.results);
    } catch (err) {
      setError(errorMessage(err));
    } finally {
      setSearching(false);
    }
  }

  return (
    <div>
      {error && <div className="error-box">{error}</div>}

      <div className="knowledge-grid">
        <form className="panel" onSubmit={ingestText}>
          <h3>Add text</h3>
          <input
            placeholder="Document name"
            value={textName}
            onChange={(e) => setTextName(e.target.value)}
            required
            maxLength={255}
          />
          <textarea
            placeholder="Paste content to index…"
            value={textContent}
            onChange={(e) => setTextContent(e.target.value)}
            required
            rows={6}
          />
          <button type="submit" disabled={saving}>
            Ingest text
          </button>
        </form>

        <form className="panel" onSubmit={ingestUrl}>
          <h3>Ingest URL</h3>
          <input
            placeholder="https://example.com/article"
            value={url}
            onChange={(e) => setUrl(e.target.value)}
            required
            maxLength={2000}
          />
          <input
            placeholder="Optional title"
            value={urlTitle}
            onChange={(e) => setUrlTitle(e.target.value)}
            maxLength={255}
          />
          <button type="submit" disabled={saving}>
            Ingest URL
          </button>
        </form>

        <form className="panel" onSubmit={ingestFile}>
          <h3>Upload file</h3>
          <input
            type="file"
            accept=".txt,.md,.markdown,.pdf,.docx,.html,.htm"
            onChange={(e) => setFile(e.target.files?.[0] ?? null)}
          />
          <input
            placeholder="Optional title"
            value={fileTitle}
            onChange={(e) => setFileTitle(e.target.value)}
            maxLength={255}
          />
          <button type="submit" disabled={saving || !file}>
            Upload
          </button>
        </form>
      </div>

      <form className="inline-form" onSubmit={search}>
        <input
          placeholder="Search knowledge…"
          value={searchQuery}
          onChange={(e) => setSearchQuery(e.target.value)}
        />
        <button type="submit" disabled={searching}>
          {searching ? "Searching…" : "Search"}
        </button>
      </form>

      {searchResults && (
        <div className="panel">
          <h3>
            Search results ({searchResults.length})
          </h3>
          {searchResults.length === 0 && <p className="muted">No matches.</p>}
          {searchResults.map((r, i) => (
            <div key={i} className="search-hit">
              <div className="muted small">
                doc #{r.document_id} · score {r.score.toFixed(4)}
              </div>
              <div>{r.content}</div>
            </div>
          ))}
        </div>
      )}

      <h3>Documents ({documents.length})</h3>
      {loading ? (
        <p className="muted">Loading…</p>
      ) : documents.length === 0 ? (
        <p className="muted">No documents yet. Add text, a URL, or a file above.</p>
      ) : (
        <table className="table">
          <thead>
            <tr>
              <th>Name</th>
              <th>Type</th>
              <th>Status</th>
              <th>Chunks</th>
              <th>Created</th>
              <th></th>
            </tr>
          </thead>
          <tbody>
            {documents.map((doc) => (
              <tr key={doc.id}>
                <td>{doc.name}</td>
                <td>{doc.source_type}</td>
                <td>
                  <span className={`badge badge-${doc.status}`}>{doc.status}</span>
                </td>
                <td>{doc.chunk_count}</td>
                <td>{new Date(doc.created_at).toLocaleString()}</td>
                <td>
                  <button className="link-button danger" onClick={() => remove(doc)}>
                    Delete
                  </button>
                </td>
              </tr>
            ))}
          </tbody>
        </table>
      )}
    </div>
  );
}