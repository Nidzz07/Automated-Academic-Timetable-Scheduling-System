/// <reference types="vite/client" />

interface ImportMetaEnv {
  /** 'static' serves the bundled files; 'http' (the default) calls the backend */
  readonly VITE_API_MODE?: string;
  /** Backend base URL; default '/api' (the dev-server proxy) */
  readonly VITE_API_BASE_URL?: string;
  /** Bearer token until a login screen exists (S13b) */
  readonly VITE_API_TOKEN?: string;
}
