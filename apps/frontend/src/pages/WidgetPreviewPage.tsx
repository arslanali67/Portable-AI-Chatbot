import { useEffect } from "react";
import { useSearchParams } from "react-router-dom";

import { widgetApiBase, widgetScriptSrc } from "./WidgetConfigPage";

export default function WidgetPreviewPage() {
  const [params] = useSearchParams();
  const publicKey = params.get("key") ?? "";

  useEffect(() => {
    if (!publicKey) {
      return;
    }
    const script = document.createElement("script");
    script.src = widgetScriptSrc();
    script.setAttribute("data-chatbot", publicKey);
    script.setAttribute("data-api", widgetApiBase());
    script.async = true;
    document.body.appendChild(script);
    return () => {
      script.remove();
    };
  }, [publicKey]);

  return (
    <div style={{ fontFamily: "system-ui", color: "#666", padding: 16 }}>
      <p>Preview pane — the launcher appears bottom-right.</p>
      {!publicKey && <p>Missing widget key.</p>}
    </div>
  );
}