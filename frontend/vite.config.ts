import path from "path"
import tailwindcss from "@tailwindcss/vite"
import react from "@vitejs/plugin-react"
import { defineConfig, type Plugin } from "vite"

/** Validated https? origin for meta tags, or "" if unset / invalid. */
function normalizeViteSiteOrigin(value: string | undefined): string {
  const trimmed = value?.trim() ?? ""
  if (!trimmed) return ""

  try {
    const u = new URL(trimmed)
    if (u.protocol !== "http:" && u.protocol !== "https:") {
      console.warn(
        `[vite] VITE_SITE_ORIGIN must use http or https; got "${u.protocol}". Ignoring VITE_SITE_ORIGIN.`,
      )
      return ""
    }
    return u.origin
  } catch {
    console.warn(
      `[vite] VITE_SITE_ORIGIN is not a valid absolute URL (${JSON.stringify(value)}). Ignoring VITE_SITE_ORIGIN.`,
    )
    return ""
  }
}

function injectSiteMeta(): Plugin {
  return {
    name: "inject-site-meta",
    transformIndexHtml(html) {
      const raw = normalizeViteSiteOrigin(process.env.VITE_SITE_ORIGIN)
      if (!raw) {
        return html.replace("<!-- vite:site-meta -->", "")
      }

      const imageUrl = `${raw}/matchpoint-logo.png`
      const ld = {
        "@context": "https://schema.org",
        "@type": "WebSite",
        name: "MatchPoint",
        url: `${raw}/`,
        description:
          "MatchPoint helps you discover jobs that fit what you're looking for.",
      }
      const snippet = `
    <link rel="canonical" href="${raw}/" />
    <meta property="og:url" content="${raw}/" />
    <meta property="og:image" content="${imageUrl}" />
    <meta property="og:image:type" content="image/png" />
    <meta property="og:image:alt" content="MatchPoint" />
    <meta name="twitter:image" content="${imageUrl}" />
    <script type="application/ld+json">${JSON.stringify(ld)}</script>`

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
