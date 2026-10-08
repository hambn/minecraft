/** Build-time syntax highlighting with the same themes as the Markdown docs. */
import { createHighlighter, type BundledLanguage } from "shiki";

export type CodeLang = Extract<BundledLanguage, "sh" | "yaml">;

const highlighter = createHighlighter({ themes: ["github-light", "github-dark"], langs: ["sh", "yaml"] });

export async function highlight(code: string, lang: CodeLang): Promise<string> {
  return (await highlighter).codeToHtml(code, {
    lang,
    themes: { light: "github-light", dark: "github-dark" },
    defaultColor: "light",
  });
}

export interface Snippet {
  value: string;
  label: string;
  code: string;
  html: string;
}

export async function snippet(value: string, label: string, code: string, lang: CodeLang): Promise<Snippet> {
  return { value, label, code, html: await highlight(code, lang) };
}
