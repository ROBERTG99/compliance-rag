/** OIDC settings. The token exchange goes through the same-origin `/oidc/` proxy (nginx and Vite). */
export const oidc = {
  issuer: (import.meta.env.VITE_OIDC_ISSUER as string | undefined) ?? "http://localhost:8612",
  proxy: "/oidc",
  clientId: "compliance-rag-web",
  redirectPath: "/callback",
  /** Dev persona switcher (dev-oidc `/dev/token`): on in `vite dev` and tests; builds opt in with VITE_DEV_PERSONAS=1. */
  devPersonas:
    import.meta.env.DEV || (import.meta.env.VITE_DEV_PERSONAS as string | undefined) === "1",
};

export const PERSONAS = ["analyst", "legal", "support", "admin"] as const;
export type Persona = (typeof PERSONAS)[number];
