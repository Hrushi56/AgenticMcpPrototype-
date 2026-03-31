import type { Metadata } from "next";
import "./globals.css";

export const metadata: Metadata = {
  title: "Bug Router · Agentic MCP Gateway PoC",
  description: "2-tool MCP demo: Jira + Slack orchestrated by an LLM",
};

export default function RootLayout({ children }: { children: React.ReactNode }) {
  return (
    <html lang="en">
      <body>{children}</body>
    </html>
  );
}
