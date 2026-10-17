/** OIDC settings. The token exchange goes through the same-origin `/oidc/` proxy (nginx and Vite). */
export const oidc = {
  issuer: (import.meta.env.VITE_OIDC_ISSUER as string | undefined) ?? "http://localhost:8612",
  proxy: "/oidc",
  clientId: "compliance-rag-web",
  redirectPath: "/callback",
  /** Dev persona switcher (dev-oidc `/dev/token`); hide with VITE_DEV_PERSONAS=0. */
  devPersonas: (import.meta.env.VITE_DEV_PERSONAS as string | undefined) !== "0",
};

export const PERSONAS = ["analyst", "legal", "support", "admin"] as const;
export type Persona = (typeof PERSONAS)[number];
