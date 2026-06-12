import { defineConfig } from "vite";
import react from "@vitejs/plugin-react";

// En dev (`npm run dev`), le serveur Vite (port 5173) proxy /api vers le
// backend FastAPI (port 8000, `uvicorn src.api.app:app`) : pas de CORS a
// gerer en local. En production, le frontend buildé (`npm run build`,
// `frontend/dist/`) est servi par FastAPI lui-meme (`src/api/app.py`), donc
// /api est toujours same-origin.
export default defineConfig({
  plugins: [react()],
  server: {
    proxy: {
      "/api": "http://127.0.0.1:8000",
    },
  },
});
