import Markdown from "react-markdown";
import remarkGfm from "remark-gfm";
import rehypeSanitize, { type Options as Schema } from "rehype-sanitize";
import type { ComponentPropsWithoutRef } from "react";
import type { ExtraProps } from "react-markdown";

// Explicit allowlist — built from scratch, not extending rehype-sanitize's
// own defaultSchema, so every permitted tag/attribute is named here. `p` is
// the one deliberate addition beyond the approved list: remark-rehype wraps
// every paragraph in <p> by default, and without it in tagNames every
// multi-paragraph reply collapses into one run-on block (hast-util-sanitize
// unwraps disallowed tags rather than dropping their content, so nothing is
// lost, but the paragraph structure is). <p> carries no attributes here and
// is not security-relevant. No script/style/iframe/img — AI-generated
// content should never be able to load an image from an arbitrary URL, and
// nothing in the approved feature set needs one.
const schema: Schema = {
  tagNames: [
    "p",
    "strong",
    "em",
    "h1",
    "h2",
    "h3",
    "h4",
    "h5",
    "h6",
    "ul",
    "ol",
    "li",
    "a",
    "code",
    "pre",
    "br",
    // remark-gfm extras within the approved feature set (lists/links/etc.);
    // no table/image/raw-html support is added.
    "del",
  ],
  attributes: {
    a: ["href"],
  },
  protocols: {
    href: ["http", "https"],
  },
};

type LinkProps = ComponentPropsWithoutRef<"a"> & ExtraProps;

function SafeLink({ href, children, node: _node, ...rest }: LinkProps) {
  const isSafeUrl = typeof href === "string" && /^https?:\/\//i.test(href);
  if (!isSafeUrl) {
    // Scheme check failed (javascript:, data:, relative, malformed, ...) —
    // render the link text as plain content, never as a clickable anchor.
    return <>{children}</>;
  }
  return (
    <a {...rest} href={href} target="_blank" rel="noopener noreferrer">
      {children}
    </a>
  );
}

export default function MessageMarkdown({ content }: { content: string }) {
  return (
    <Markdown
      remarkPlugins={[remarkGfm]}
      rehypePlugins={[[rehypeSanitize, schema]]}
      components={{ a: SafeLink }}
    >
      {content}
    </Markdown>
  );
}
