import { useCallback, useEffect, useState, type FormEvent } from "react";
import { Link, useParams } from "react-router-dom";

import { api } from "../api/client";
import { errorMessage } from "../auth/AuthContext";
import type { Chatbot, ModelInfo, Provider } from "../api/types";

const LANGUAGE_OPTIONS = ["en", "ur"];

export default function ChatbotsPage() {
  const { organizationId } = useParams<{ organizationId: string }>();
  const orgId = Number(organizationId);

  const [chatbots, setChatbots] = useState<Chatbot[]>([]);
  const [providers, setProviders] = useState<Provider[]>([]);
  const [models, setModels] = useState<ModelInfo[]>([]);
  const [error, setError] = useState<string | null>(null);
  const [loading, setLoading] = useState(true);

  const [showCreate, setShowCreate] = useState(false);
  const [editing, setEditing] = useState<Chatbot | null>(null);

  // Create form state
  const [name, setName] = useState("");
  const [slug, setSlug] = useState("");
  const [description, setDescription] = useState("");
  const [systemPrompt, setSystemPrompt] = useState("");
  const [welcomeMessage, setWelcomeMessage] = useState("");
  const [language, setLanguage] = useState("en");
  const [visibility, setVisibility] = useState<"public" | "private">("private");
  const [providerId, setProviderId] = useState("");
  const [modelId, setModelId] = useState("");
  const [saving, setSaving] = useState(false);

  const load = useCallback(() => {
    setLoading(true);
    Promise.all([api.listChatbots(orgId), api.listProviders()])
      .then(([bots, provs]) => {
        setChatbots(bots);
        setProviders(provs.filter((p) => p.enabled && p.capabilities.includes("text_generation")));
      })
      .catch((err) => setError(errorMessage(err)))
      .finally(() => setLoading(false));
  }, [orgId]);

  useEffect(load, [load]);

  useEffect(() => {
    if (!providerId) {
      setModels([]);
      return;
    }
    api
      .listModels(providerId)
      .then((ms) => setModels(ms.filter((m) => m.enabled)))
      .catch(() => setModels([]));
  }, [providerId]);

  function openCreate() {
    setEditing(null);
    setProviderId(providers[0]?.provider_id ?? "");
    setModelId("");
    setShowCreate(true);
  }

  function openEdit(bot: Chatbot) {
    setEditing(bot);
    setName(bot.name);
    setSlug(bot.slug);
    setDescription(bot.description);
    setSystemPrompt(bot.system_prompt);
    setWelcomeMessage(bot.welcome_message);
    setLanguage(bot.language);
    setVisibility(bot.visibility);
    setProviderId(bot.provider_id);
    setModelId(bot.model_id);
    setShowCreate(true);
  }

  async function onSubmit(e: FormEvent) {
    e.preventDefault();
    if (!providerId || !modelId) {
      setError("Select a provider and a model.");
      return;
    }
    setSaving(true);
    setError(null);
    try {
      if (editing) {
        await api.updateChatbot(orgId, editing.id, {
          name,
          slug,
          description,
          system_prompt: systemPrompt,
          welcome_message: welcomeMessage,
          language,
          visibility,
          provider_id: providerId,
          model_id: modelId,
        });
      } else {
        await api.createChatbot(orgId, {
          name,
          slug,
          description,
          system_prompt: systemPrompt,
          welcome_message: welcomeMessage,
          language,
          visibility,
          provider_id: providerId,
          model_id: modelId,
        });
      }
      setShowCreate(false);
      load();
    } catch (err) {
      setError(errorMessage(err));
    } finally {
      setSaving(false);
    }
  }

  async function changeStatus(bot: Chatbot, status: "activate" | "archive") {
    try {
      if (status === "activate") {
        await api.activateChatbot(orgId, bot.id);
      } else {
        await api.archiveChatbot(orgId, bot.id);
      }
      load();
    } catch (err) {
      setError(errorMessage(err));
    }
  }

  async function remove(bot: Chatbot) {
    if (!window.confirm(`Delete chatbot "${bot.name}"? This cannot be undone.`)) {
      return;
    }
    try {
      await api.deleteChatbot(orgId, bot.id);
      load();
    } catch (err) {
      setError(errorMessage(err));
    }
  }

  if (loading) {
    return <div className="center-screen">Loading…</div>;
  }

  return (
    <section>
      <div className="page-head">
        <h1>Chatbots</h1>
        <button className="button" onClick={openCreate}>
          New chatbot
        </button>
      </div>

      {error && <div className="error-box">{error}</div>}

      {showCreate && (
        <form className="panel" onSubmit={onSubmit}>
          <h2>{editing ? `Edit ${editing.name}` : "New chatbot"}</h2>
          <div className="form-grid">
            <label>
              Name
              <input value={name} onChange={(e) => setName(e.target.value)} required maxLength={255} />
            </label>
            <label>
              Slug
              <input
                value={slug}
                onChange={(e) => setSlug(e.target.value.toLowerCase())}
                required
                pattern="[a-z0-9]+(?:-[a-z0-9]+)*"
                maxLength={100}
              />
            </label>
            <label>
              Description
              <textarea
                value={description}
                onChange={(e) => setDescription(e.target.value)}
                maxLength={5000}
              />
            </label>
            <label className="full">
              System prompt
              <textarea
                value={systemPrompt}
                onChange={(e) => setSystemPrompt(e.target.value)}
                maxLength={20000}
              />
            </label>
            <label>
              Welcome message
              <input
                value={welcomeMessage}
                onChange={(e) => setWelcomeMessage(e.target.value)}
                maxLength={2000}
              />
            </label>
            <label>
              Language
              <select value={language} onChange={(e) => setLanguage(e.target.value)}>
                {LANGUAGE_OPTIONS.map((l) => (
                  <option key={l} value={l}>
                    {l}
                  </option>
                ))}
              </select>
            </label>
            <label>
              Visibility
              <select
                value={visibility}
                onChange={(e) => setVisibility(e.target.value as "public" | "private")}
              >
                <option value="private">Private</option>
                <option value="public">Public</option>
              </select>
            </label>
            <label>
              Provider
              <select
                value={providerId}
                onChange={(e) => {
                  setProviderId(e.target.value);
                  setModelId("");
                }}
              >
                {providers.map((p) => (
                  <option key={p.provider_id} value={p.provider_id}>
                    {p.display_name}
                  </option>
                ))}
              </select>
            </label>
            <label>
              Model
              <select
                value={modelId}
                onChange={(e) => setModelId(e.target.value)}
                disabled={!providerId || models.length === 0}
                required
              >
                {models.length === 0 ? (
                  <option value="">No models available</option>
                ) : (
                  <option value="">Select model</option>
                )}
                {models.map((m) => (
                  <option key={m.model_id} value={m.model_id}>
                    {m.display_name}
                  </option>
                ))}
              </select>
            </label>
          </div>
          <div className="form-actions">
            <button type="submit" disabled={saving}>
              {saving ? "Saving…" : editing ? "Save changes" : "Create"}
            </button>
            <button type="button" className="secondary" onClick={() => setShowCreate(false)}>
              Cancel
            </button>
          </div>
        </form>
      )}

      {chatbots.length === 0 ? (
        <p className="muted">No chatbots yet. Create one to configure a chatbot.</p>
      ) : (
        <table className="table">
          <thead>
            <tr>
              <th>Name</th>
              <th>Slug</th>
              <th>Status</th>
              <th>Provider</th>
              <th>Model</th>
              <th>Actions</th>
            </tr>
          </thead>
          <tbody>
            {chatbots.map((bot) => (
              <tr key={bot.id}>
                <td>
                  <Link to={`/organizations/${orgId}/chatbots/${bot.id}`}>{bot.name}</Link>
                </td>
                <td>/{bot.slug}</td>
                <td>
                  <span className={`badge badge-${bot.status}`}>{bot.status}</span>
                </td>
                <td>{bot.provider_id}</td>
                <td>{bot.model_id}</td>
                <td className="actions">
                  <button className="link-button" onClick={() => openEdit(bot)}>
                    Edit
                  </button>
                  {bot.status === "draft" && (
                    <button className="link-button" onClick={() => changeStatus(bot, "activate")}>
                      Activate
                    </button>
                  )}
                  {bot.status === "active" && (
                    <button className="link-button" onClick={() => changeStatus(bot, "archive")}>
                      Archive
                    </button>
                  )}
                  {bot.status !== "active" && (
                    <button className="link-button danger" onClick={() => remove(bot)}>
                      Delete
                    </button>
                  )}
                </td>
              </tr>
            ))}
          </tbody>
        </table>
      )}
    </section>
  );
}