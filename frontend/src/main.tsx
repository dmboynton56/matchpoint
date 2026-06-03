import { StrictMode } from "react"
import { createRoot } from "react-dom/client"
import { BrowserRouter } from "react-router-dom"

import "./index.css"
import App from "./App.tsx"
import { ThemeProvider } from "@/components/theme-provider.tsx"
import { Toaster } from "@/components/ui/sonner"
import { AuthProvider } from "@/context/AuthContext"
import Footer from "@/components/Footer"

createRoot(document.getElementById("root")!).render(
  <StrictMode>
    <BrowserRouter>
      <ThemeProvider>
        <AuthProvider>
          <App />
          <Footer />
          <Toaster richColors closeButton />
        </AuthProvider>
      </ThemeProvider>
    </BrowserRouter>
  </StrictMode>
)
