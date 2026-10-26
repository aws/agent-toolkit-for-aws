import { GoogleGenAI, Modality } from '@google/genai';

export async function generateBanner(ai: GoogleGenAI, prompt: string) {
  const response = await ai.models.generateContent({
    model: 'gemini-3.1-flash-image',
    contents: [{ role: 'user', parts: [{ text: prompt }] }],
    config: {
      responseModalities: [Modality.IMAGE],
      imageConfig: { aspectRatio: '16:9' },
    },
  });
  return response.candidates?.[0]?.content?.parts;
}
