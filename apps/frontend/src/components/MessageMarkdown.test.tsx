// Tests for MessageMarkdown: the approved feature set renders as real
// elements (not literal markdown characters), the explicit rehype-sanitize
// allowlist neutralizes anything outside it, and links are gated by an
// http(s)-only scheme check with target="_blank" rel="noopener noreferrer".

import { render, screen } from "@testing-library/react";
import { describe, expect, it } from "vitest";

import MessageMarkdown from "./MessageMarkdown";

describe("MessageMarkdown", () => {
  it("renders **bold** as a real <strong> element, not literal asterisks", () => {
    render(<MessageMarkdown content="This is **bold** text." />);
    const strong = screen.getByText("bold");
    expect(strong.tagName).toBe("STRONG");
    expect(screen.queryByText(/\*\*/)).not.toBeInTheDocument();
  });

  it("renders italics as a real <em> element", () => {
    render(<MessageMarkdown content="This is *italic* text." />);
    const em = screen.getByText("italic");
    expect(em.tagName).toBe("EM");
  });

  it("renders a bullet list as <ul><li> elements", () => {
    const { container } = render(<MessageMarkdown content={"- one\n- two\n- three"} />);
    const ul = container.querySelector("ul");
    expect(ul).not.toBeNull();
    const items = ul!.querySelectorAll("li");
    expect(items).toHaveLength(3);
    expect(items[0].textContent).toBe("one");
    expect(items[2].textContent).toBe("three");
  });

  it("renders a numbered list as <ol><li> elements", () => {
    const { container } = render(<MessageMarkdown content={"1. first\n2. second"} />);
    const ol = container.querySelector("ol");
    expect(ol).not.toBeNull();
    expect(ol!.querySelectorAll("li")).toHaveLength(2);
  });

  it("renders a heading as the correct <hN> element", () => {
    const { container } = render(<MessageMarkdown content="## Section Title" />);
    const h2 = container.querySelector("h2");
    expect(h2).not.toBeNull();
    expect(h2!.textContent).toBe("Section Title");
  });

  it("renders inline code and fenced code blocks", () => {
    const { container } = render(
      <MessageMarkdown content={"Use `inline` code.\n\n```\nblock code\n```"} />,
    );
    const codes = container.querySelectorAll("code");
    expect(codes.length).toBeGreaterThanOrEqual(2);
    expect(container.querySelector("pre")).not.toBeNull();
  });

  it("renders an https link with target=_blank and rel=noopener noreferrer", () => {
    render(<MessageMarkdown content="[docs](https://example.com/docs)" />);
    const link = screen.getByRole("link", { name: "docs" });
    expect(link).toHaveAttribute("href", "https://example.com/docs");
    expect(link).toHaveAttribute("target", "_blank");
    expect(link).toHaveAttribute("rel", "noopener noreferrer");
  });

  it("does not render a javascript: URL as a clickable link", () => {
    const { container } = render(
      <MessageMarkdown content="[click me](javascript:alert(1))" />,
    );
    expect(screen.queryByRole("link")).not.toBeInTheDocument();
    // The link text is preserved as plain content, not dropped.
    expect(screen.getByText("click me")).toBeInTheDocument();
    expect(container.innerHTML).not.toContain("javascript:");
  });

  it("does not render a data: URL as a clickable link", () => {
    render(<MessageMarkdown content="[x](data:text/html,<script>alert(1)</script>)" />);
    expect(screen.queryByRole("link")).not.toBeInTheDocument();
    expect(screen.getByText("x")).toBeInTheDocument();
  });

  it("neutralizes a literal <script> tag embedded in AI-generated text", () => {
    const { container } = render(
      <MessageMarkdown content={'Here is some text <script>alert("xss")</script> after.'} />,
    );
    expect(container.querySelectorAll("script")).toHaveLength(0);
    // The dangerous tag is gone entirely (raw HTML isn't part of the approved
    // feature set, so remark treats it as literal text or strips it) — either
    // way, no live <script> element and no alert-call substring survive as
    // executable markup.
    expect(container.innerHTML).not.toContain("<script>");
  });

  it("neutralizes an onerror= attribute string embedded in AI-generated text", () => {
    const { container } = render(
      <MessageMarkdown content='Check this: <img src=x onerror="alert(1)"> please.' />,
    );
    expect(container.querySelectorAll("[onerror]")).toHaveLength(0);
    expect(container.querySelectorAll("img")).toHaveLength(0);
  });

  it("neutralizes a disallowed tag (style) even though it isn't in the allowlist", () => {
    const { container } = render(
      <MessageMarkdown content={"<style>body{display:none}</style>\n\nSome text after."} />,
    );
    expect(container.querySelectorAll("style")).toHaveLength(0);
    expect(container.innerHTML).not.toContain("display:none");
    expect(screen.getByText("Some text after.")).toBeInTheDocument();
  });

  it("leaves plain text with no markdown syntax completely unaffected", () => {
    render(<MessageMarkdown content="Hi! How can I help?" />);
    expect(screen.getByText("Hi! How can I help?")).toBeInTheDocument();
  });
});
