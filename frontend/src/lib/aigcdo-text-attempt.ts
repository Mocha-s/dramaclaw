import { generateClientId } from "@/lib/client-id";

export type TextGenerationAttempt = { prompt: string; key: string };

export function textGenerationAttempt(prompt: string, existing: unknown): TextGenerationAttempt {
  if (existing && typeof existing === "object") {
    const attempt = existing as Partial<TextGenerationAttempt>;
    if (attempt.prompt === prompt && typeof attempt.key === "string" &&
        /^[A-Za-z0-9_-]{16,128}$/.test(attempt.key)) return attempt as TextGenerationAttempt;
  }
  return { prompt, key: `text-${generateClientId()}` };
}
