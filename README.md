# React + TypeScript + Vite + shadcn/ui

This is a template for a new Vite project with React, TypeScript, and shadcn/ui.

## Adding components

To add components to your app, run the following command:

```bash
npx shadcn@latest add button
```

This will place the ui components in the `src/components` directory.

## Using components

To use the components in your app, import them as follows:

```tsx
import { Button } from "@/components/ui/button";
```

# Setup your local environment

## Prerequisites

- Node.js with npm
- Docker Engine or Docker Desktop
- Python3

1. Clone the repo & `cd` into it

**BACKEND:**

2. Create `venv` and `pip install -r requirements.txt`
3. Ensure Docker is running, then `run npx supabase start`
4. Create a `.env` file from the `.env.example`

..._backend to be continued_

**FRONTEND:**

5. Open a 2nd terminal
6. `cd` into `/frontend`
7. Run `npm install`
8. Run `npm run dev`
