import { useEffect, useState } from "react";

import { api } from "../api/client";
import { errorMessage } from "../auth/AuthContext";
import type { ModelInfo, Provider } from "../api/types";

export default function ProvidersPage() {
  const [providers, setProviders] = useState<Provider[]>([]);
  const [modelsByProvider, setModelsByProvider] = useState<Record<string, ModelInfo[]>>({});
  const [error, setError] = useState<string | null>(null);
  const [loading, setLoading] = useState(true);

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

  if (loading) {
    return <div className="center-screen">Loading…</div>;
  }

  return (
    <section>
      <h1>AI Providers</h1>
      <p className="muted">
        Read-only view of providers and models available to your chatbots. Configured on the
        platform, not per-user.
      </p>
      {error && <div className="error-box">{error}</div>}

      {providers.map((provider) => (
        <div key={provider.provider_id} className="panel">
          <div className="page-head">
            <div>
              <h2>{provider.display_name}</h2>
              <p className="muted small">{provider.description}</p>
            </div>
            <span className={`badge badge-${provider.enabled ? "active" : "archived"}`}>
              {provider.enabled ? "enabled" : "disabled"}
            </span>
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