import path from "path"
import tailwindcss from "@tailwindcss/vite"
import react from "@vitejs/plugin-react"
import { defineConfig, type Plugin } from "vite"

function injectSiteMeta(): Plugin {
  return {
    name: "inject-site-meta",
    transformIndexHtml(html) {
      const raw = process.env.VITE_SITE_ORIGIN?.trim().replace(/\/$/, "") ?? ""
      if (!raw) {
        return html.replace("<!-- vite:site-meta -->", "")
      }

      const imageUrl = `${raw}/matchpoint-logo.png`
      const snippet = `\n    <link rel="canonical" href="${raw}/" />\n    <meta property="og:url" content="${raw}/" />\n    <meta property="og:image" content="${imageUrl}" />\n    <meta property="og:image:type" content="image/png" />\n    <meta property="og:image:alt" content="MatchPoint" />\n    <meta name="twitter:image" content="${imageUrl}" />\n    <script type="application/ld+json">${JSON.stringify({
        "@context": "https://schema.org",
        "@type": "WebSite",
        name: "MatchPoint",
        url: `${raw}/`,
        description:
          "MatchPoint helps you discover jobs that fit what you're looking for.",
      })}</script>`

      return html.replace("<!-- vite:site-meta -->", snippet.trimStart())
    },
  }
}

// https://vite.dev/config/
export default defineConfig({
  plugins: [injectSiteMeta(), react(), tailwindcss()],
  resolve: {
    alias: {
      "@": path.resolve(__dirname, "./src"),
    },
  },
})
