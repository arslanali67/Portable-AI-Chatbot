import { useEffect, useRef, useState } from "react";

import { api } from "../api/client";
import { errorMessage, useAuth } from "../auth/AuthContext";
import type { ModelInfo, Provider } from "../api/types";

export default function ProvidersPage() {
  const { user } = useAuth();
  const isPlatformAdmin = user?.is_platform_admin ?? false;

  const [providers, setProviders] = useState<Provider[]>([]);
  const [modelsByProvider, setModelsByProvider] = useState<Record<string, ModelInfo[]>>({});
  const [error, setError] = useState<string | null>(null);
  const [loading, setLoading] = useState(true);
  const [pendingActions, setPendingActions] = useState<Set<string>>(new Set());
  const pendingRef = useRef<Set<string>>(new Set());

  useEffect(() => {
    let cancelled = false;
    async function load() {
      setLoading(true);
      try {
        const provs = await api.listProviders();
        if (cancelled) return;
        setProviders(provs);
        const modelMap: Record<string, ModelInfo[]> = {};
        await Promise.all(
          provs.map(async (p) => {
            try {
              const models = await api.listModels(p.provider_id);
              modelMap[p.provider_id] = models;
            } catch {
              modelMap[p.provider_id] = [];
            }
          }),
        );
        if (!cancelled) setModelsByProvider(modelMap);
      } catch (err) {
        if (!cancelled) setError(errorMessage(err));
      } finally {
        if (!cancelled) setLoading(false);
      }
    }
    load();
    return () => {
      cancelled = true;
    };
  }, []);

  async function toggleProvider(provider: Provider) {
    const key = `provider:${provider.provider_id}`;
    if (pendingRef.current.has(key)) return;
    pendingRef.current.add(key);
    setPendingActions(new Set(pendingRef.current));
    try {
      const updated = await api.updateProvider(provider.provider_id, {
        disabled: provider.enabled,
      });
      setProviders((prev) =>
        prev.map((p) => (p.provider_id === updated.provider_id ? updated : p)),
      );
    } catch (err) {
      setError(errorMessage(err));
    } finally {
      pendingRef.current.delete(key);
      setPendingActions(new Set(pendingRef.current));
    }
  }

  async function toggleModel(model: ModelInfo) {
    const key = `model:${model.provider_id}:${model.model_id}`;
    if (pendingRef.current.has(key)) return;
    pendingRef.current.add(key);
    setPendingActions(new Set(pendingRef.current));
    try {
      const updated = await api.updateModel(model.provider_id, model.model_id, {
        disabled: model.enabled,
      });
      setModelsByProvider((prev) => ({
        ...prev,
        [model.provider_id]: (prev[model.provider_id] ?? []).map((m) =>
          m.model_id === updated.model_id ? updated : m,
        ),
      }));
    } catch (err) {
      setError(errorMessage(err));
    } finally {
      pendingRef.current.delete(key);
      setPendingActions(new Set(pendingRef.current));
    }
  }

  if (loading) {
    return <div className="center-screen">Loading…</div>;
  }

  return (
    <section>
      <h1>AI Providers</h1>
      <p className="muted">
        Providers and models available to your chatbots. Configured on the platform, not
        per-user.
        {isPlatformAdmin && " As a platform admin, you can enable or disable them below."}
      </p>
      {error && <div className="error-box">{error}</div>}

      {providers.map((provider) => (
        <div key={provider.provider_id} className="panel">
          <div className="page-head">
            <div>
              <h2>{provider.display_name}</h2>
              <p className="muted small">{provider.description}</p>
            </div>
            <div className="meta-row">
              <span className={`badge badge-${provider.enabled ? "active" : "archived"}`}>
                {provider.enabled ? "enabled" : "disabled"}
              </span>
              {isPlatformAdmin && (
                <button
                  type="button"
                  onClick={() => toggleProvider(provider)}
                  disabled={pendingActions.has(`provider:${provider.provider_id}`)}
                >
                  {provider.enabled ? "Disable" : "Enable"}
                </button>
              )}
            </div>
          </div>
          <div className="meta-row">
            <span>
              <strong>Auth:</strong> {provider.authentication_type}
            </span>
            <span>
              <strong>Compatibility:</strong> {provider.compatibility_type}
            </span>
            <span>
              <strong>Capabilities:</strong> {provider.capabilities.join(", ")}
            </span>
          </div>
          <h3>Models</h3>
          {(modelsByProvider[provider.provider_id] ?? []).length === 0 ? (
            <p className="muted">No models.</p>
          ) : (
            <table className="table">
              <thead>
                <tr>
                  <th>Model</th>
                  <th>Context</th>
                  <th>Max output</th>
                  <th>Capabilities</th>
                  <th>Status</th>
                  {isPlatformAdmin && <th></th>}
                </tr>
              </thead>
              <tbody>
                {(modelsByProvider[provider.provider_id] ?? []).map((model) => (
                  <tr key={model.model_id}>
                    <td>
                      {model.display_name} <span className="muted">({model.model_id})</span>
                    </td>
                    <td>{model.context_window.toLocaleString()}</td>
                    <td>{model.max_output_tokens.toLocaleString()}</td>
                    <td>{model.capabilities.join(", ")}</td>
                    <td>
                      <span className={`badge badge-${model.enabled ? "active" : "archived"}`}>
                        {model.enabled ? "enabled" : "disabled"}
                      </span>
                    </td>
                    {isPlatformAdmin && (
                      <td>
                        <button
                          type="button"
                          className="link-button"
                          onClick={() => toggleModel(model)}
                          disabled={pendingActions.has(
                            `model:${model.provider_id}:${model.model_id}`,
                          )}
                        >
                          {model.enabled ? "Disable" : "Enable"}
                        </button>
                      </td>
                    )}
                  </tr>
                ))}
              </tbody>
            </table>
          )}
        </div>
      ))}
    </section>
  );
}
