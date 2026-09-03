import { useCallback, useEffect, useState } from "react";
import { Link, useParams } from "react-router-dom";

import { api } from "../api/client";
import { errorMessage } from "../auth/AuthContext";
import type { BillingTier, Invoice, SubscriptionStatus } from "../api/types";

const TIERS: { id: BillingTier; label: string }[] = [
  { id: "pro", label: "Pro" },
  { id: "enterprise", label: "Enterprise" },
];

export default function BillingPage() {
  const { organizationId } = useParams<{ organizationId: string }>();
  const orgId = Number(organizationId);

  const [subscription, setSubscription] = useState<SubscriptionStatus | null>(null);
  const [invoices, setInvoices] = useState<Invoice[]>([]);
  const [loading, setLoading] = useState(true);
  const [error, setError] = useState<string | null>(null);
  const [subscribing, setSubscribing] = useState<BillingTier | null>(null);

  const load = useCallback(() => {
    setLoading(true);
    Promise.all([api.getSubscription(orgId), api.listInvoices(orgId)])
      .then(([sub, inv]) => {
        setSubscription(sub);
        setInvoices(inv.items);
      })
      .catch((err) => setError(errorMessage(err)))
      .finally(() => setLoading(false));
  }, [orgId]);

  useEffect(load, [load]);

  async function subscribe(tier: BillingTier) {
    setSubscribing(tier);
    setError(null);
    try {
      const { checkout_url } = await api.createCheckoutSession(orgId, tier);
      window.location.href = checkout_url;
    } catch (err) {
      setError(errorMessage(err));
      setSubscribing(null);
    }
  }

  if (loading) {
    return <div className="center-screen">Loading…</div>;
  }

  const currentTier = subscription?.tier ?? "free";

  return (
    <section>
      <div className="page-head">
        <div>
          <h1>Billing</h1>
          <p className="muted">
            Current plan: <strong>{currentTier}</strong>
            {subscription?.status && ` · ${subscription.status}`}
          </p>
        </div>
        <Link to={`/organizations/${orgId}/settings`} className="button secondary">
          Back
        </Link>
      </div>

      {error && <div className="error-box">{error}</div>}

      <div className="panel">
        <h2>Plans</h2>
        <div className="stat-grid">
          {TIERS.map((tier) => (
            <div key={tier.id} className="stat-card">
              <div className="stat-label">{tier.label}</div>
              <button
                disabled={subscribing !== null || subscription?.tier === tier.id}
                onClick={() => subscribe(tier.id)}
              >
                {subscription?.tier === tier.id
                  ? "Current plan"
                  : subscribing === tier.id
                    ? "Redirecting…"
                    : "Subscribe"}
              </button>
            </div>
          ))}
        </div>
      </div>

      <div className="panel">
        <h2>Invoice History</h2>
        {invoices.length === 0 ? (
          <p className="muted">No invoices yet.</p>
        ) : (
          <table className="table">
            <thead>
              <tr>
                <th>Date</th>
                <th>Amount</th>
                <th>Status</th>
                <th></th>
              </tr>
            </thead>
            <tbody>
              {invoices.map((invoice) => (
                <tr key={invoice.id}>
                  <td>{new Date(invoice.created).toLocaleDateString()}</td>
                  <td>
                    {(invoice.amount_paid / 100).toFixed(2)} {invoice.currency.toUpperCase()}
                  </td>
                  <td>{invoice.status}</td>
                  <td>
                    {invoice.hosted_invoice_url && (
                      <a href={invoice.hosted_invoice_url} target="_blank" rel="noreferrer">
                        View
                      </a>
                    )}
                  </td>
                </tr>
              ))}
            </tbody>
          </table>
        )}
      </div>
    </section>
  );
}
