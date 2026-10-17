// Promptfoo provider: POST /v1/ask (non-streaming) as the case's persona; the token comes from
// CRAG_TOKEN_<PERSONA>, minted by scripts/redteam.sh from dev-oidc. Returns the whole JSON body.
export default class CragApiProvider {
  id() {
    return "crag-api";
  }

  async callApi(prompt, context) {
    const vars = context?.vars ?? {};
    const persona = String(vars.persona ?? "analyst");
    const token = process.env[`CRAG_TOKEN_${persona.toUpperCase()}`];
    if (!token) return { error: `no token for persona ${persona}` };
    const body = { question: prompt, as_of: vars.as_of, stream: false };
    for (let attempt = 0; ; attempt++) {
      const res = await fetch(`${process.env.CRAG_REDTEAM_API}/v1/ask`, {
        method: "POST",
        headers: { "Content-Type": "application/json", Authorization: `Bearer ${token}` },
        body: JSON.stringify(body),
      });
      // the API allows 30 asks per minute per user: wait as told and try again
      if (res.status === 429 && attempt < 5) {
        const wait = Number(res.headers.get("Retry-After") ?? "5");
        await new Promise((resolve) => setTimeout(resolve, wait * 1000));
        continue;
      }
      const text = await res.text();
      if (!res.ok) return { error: `HTTP ${res.status}: ${text.slice(0, 300)}` };
      return { output: text };
    }
  }
}
