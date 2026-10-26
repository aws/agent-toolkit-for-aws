import { GoogleGenAI } from '@google/genai';

export async function summarize(ai: GoogleGenAI, text: string) {
  const response = await ai.models.generateContent({
    model: 'gemini-2.5-flash',
    contents: text,
  });
  return response.text;
}
