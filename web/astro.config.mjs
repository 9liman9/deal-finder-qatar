// @ts-check
import { defineConfig } from 'astro/config';

import tailwindcss from '@tailwindcss/vite';

// GitHub Pages config is auto-derived in CI (see .github/workflows/deploy.yml),
// which injects BASE_PATH=/<repo-name>/ and SITE_URL=https://<owner>.github.io.
// Locally these are unset, so the site builds at "/" — `npm run dev` just works.
//   Edge cases: if your repo is named <user>.github.io OR you use a custom domain,
//   set BASE_PATH=/ in the workflow.
const base = process.env.BASE_PATH || '/';
const site = process.env.SITE_URL || undefined;

// https://astro.build/config
export default defineConfig({
  site,
  base,
  vite: {
    plugins: [tailwindcss()]
  }
});
