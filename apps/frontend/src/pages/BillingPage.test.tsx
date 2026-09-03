// Tests for the real BillingPage: tier rendering, subscription status
// display, invoice history, and the Subscribe button triggering the
// checkout flow. fetch is mocked at the global boundary.

import { render, screen } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import { afterEach, beforeEach, describe, expect, it, vi } from "vitest";
import { MemoryRouter, Route, Routes } from "react-router-dom";

import BillingPage from "./BillingPage";
import { jsonResponse } from "../test/helpers";
import type { InvoiceList, SubscriptionStatus } from "../api/types";

const fetchMock = vi.fn<typeof fetch>();

const NO_SUBSCRIPTION: SubscriptionStatus = { tier: null, status: null, current_period_end: null };
const PRO_SUBSCRIPTION: SubscriptionStatus = {
  tier: "pro",
  status: "active",
  current_period_end: "2026-06-01T00:00:00Z",
};
const EMPTY_INVOICES: InvoiceList = { items: [] };
const SOME_INVOICES: InvoiceList = {
  items: [
    {
      id: "in_1",
      created: "2026-01-01T00:00:00Z",
      amount_paid: 2900,
      currency: "usd",
      status: "paid",
      hosted_invoice_url: "https://stripe.example/in_1",
    },
  ],
};

function renderPage() {
  return render(
    <MemoryRouter initialEntries={["/organizations/5/billing"]}>
      <Routes>
        <Route path="/organizations/:organizationId/billing" element={<BillingPage />} />
      </Routes>
    </MemoryRouter>,
  );
}

beforeEach(() => {
  fetchMock.mockReset();
  vi.stubGlobal("fetch", fetchMock);
});

afterEach(() => {
  vi.unstubAllGlobals();
  vi.restoreAllMocks();
});

describe("BillingPage", () => {
  it("shows a loading state until subscription/invoices settle", async () => {
    fetchMock.mockImplementation(() => new Promise<Response>(() => undefined));
    renderPage();
    expect(screen.getByText("Loading…")).toBeInTheDocument();
  });

  it("renders free plan and no invoices when nothing is set", async () => {
    fetchMock.mockImplementation(async (input) => {
      const path = String(input);
      if (path.endsWith("/billing/subscription")) return jsonResponse(200, NO_SUBSCRIPTION);
      if (path.endsWith("/billing/invoices")) return jsonResponse(200, EMPTY_INVOICES);
      return jsonResponse(404, { detail: "Not found" });
    });

    renderPage();

    await screen.findByText("free", { exact: false });
    expect(screen.getByText("No invoices yet.")).toBeInTheDocument();
    expect(screen.getByText("Pro")).toBeInTheDocument();
    expect(screen.getByText("Enterprise")).toBeInTheDocument();
  });

  it("renders the current plan and invoice history when subscribed", async () => {
    fetchMock.mockImplementation(async (input) => {
      const path = String(input);
      if (path.endsWith("/billing/subscription")) return jsonResponse(200, PRO_SUBSCRIPTION);
      if (path.endsWith("/billing/invoices")) return jsonResponse(200, SOME_INVOICES);
      return jsonResponse(404, { detail: "Not found" });
    });

    renderPage();

    const planLine = await screen.findByText(/Current plan:/);
    expect(planLine.textContent).toBe("Current plan: pro · active");
    expect(screen.getByText("29.00 USD")).toBeInTheDocument();
    expect(screen.getByRole("link", { name: "View" })).toHaveAttribute(
      "href",
      "https://stripe.example/in_1",
    );
    // Already on Pro — its button reflects the current plan, not "Subscribe".
    expect(screen.getByText("Current plan")).toBeInTheDocument();
  });

  it("clicking Subscribe calls the checkout endpoint for the selected tier", async () => {
    const user = userEvent.setup();
    fetchMock.mockImplementation(async (input, init) => {
      const path = String(input);
      const method = (init?.method ?? "GET").toUpperCase();
      if (path.endsWith("/billing/subscription")) return jsonResponse(200, NO_SUBSCRIPTION);
      if (path.endsWith("/billing/invoices")) return jsonResponse(200, EMPTY_INVOICES);
      if (path.endsWith("/billing/checkout") && method === "POST") {
        return jsonResponse(200, { checkout_url: "https://checkout.stripe.com/fake" });
      }
      return jsonResponse(404, { detail: "Not found" });
    });

    renderPage();

    await screen.findByText("Pro");
    const buttons = screen.getAllByRole("button", { name: "Subscribe" });
    await user.click(buttons[0]);

    const checkoutCall = fetchMock.mock.calls.find(
      (c) => String(c[0]).endsWith("/billing/checkout") && c[1]?.method === "POST",
    );
    expect(checkoutCall).toBeDefined();
    expect(JSON.parse(String(checkoutCall?.[1]?.body))).toEqual({ tier: "pro" });
  });

  it("shows an error when loading fails", async () => {
    fetchMock.mockResolvedValue(jsonResponse(500, { detail: "billing unavailable" }));
    renderPage();
    await screen.findByText("billing unavailable");
  });
});
