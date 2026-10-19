import { screen, waitFor, within } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import { afterEach, beforeEach, expect, test, vi } from "vitest";
import { fakeToken, mockFetch, renderApp, signInAs } from "../../test/render";

const QUESTION = "What is the maximum age of a proof-of-address document?";
const enc = new TextEncoder();
const sse = (id: number, event: string, data: unknown) =>
  enc.encode(`id: ${id}\nevent: ${event}\ndata: ${JSON.stringify(data)}\n\n`);

const CLAIM = {
  index: 0,
  text: "A proof-of-address document must not be older than 90 days at the date of onboarding.",
  citations: [
    {
      n: 1,
      chunk_id: "c".repeat(32),
      document_id: "KYC-0042",
      version: 3,
      quote: "must not be older than 90 days",
      char_start: 10,
      char_end: 40,
    },
  ],
};

const FINAL = {
  run_id: "r1",
  conversation_id: "c1",
  answer: CLAIM.text,
  claims: [CLAIM],
  abstained: false,
  message: null,
  as_of: "2026-10-16",
  versions: [
    {
      document_id: "KYC-0042",
      version: 3,
      title: "Proof of Address",
      valid_from: "2026-03-01",
      valid_to: null,
      superseded: false,
    },
  ],
  confidence: 0.91,
  degraded: [],
  cost_usd: 0,
  latency_ms: 120,
  label: "AI-generated",
};

/** A controllable event stream: push events from the test, then close. */
function controlledStream() {
  let ctrl!: ReadableStreamDefaultController<Uint8Array>;
  const body = new ReadableStream<Uint8Array>({ start: (c) => void (ctrl = c) });
  return {
    response: new Response(body, { status: 200, headers: { "Content-Type": "text/event-stream" } }),
    push: (chunk: Uint8Array) => ctrl.enqueue(chunk),
    close: () => ctrl.close(),
  };
}

beforeEach(() => {
  sessionStorage.clear();
  signInAs("analyst");
});
afterEach(() => vi.unstubAllGlobals());

async function ask(user: ReturnType<typeof userEvent.setup>) {
  await user.type(screen.getByLabelText(/question/i), QUESTION);
  await user.click(screen.getByRole("button", { name: /^ask$/i }));
}

test("verified claims render before final, with keyboard-reachable citation chips", async () => {
  const stream = controlledStream();
  const calls = mockFetch((url) => {
    if (url === "/v1/ask")
      return { status: 202, body: { run_id: "r1", events_url: "/v1/runs/r1/events" } };
    if (url === "/v1/runs/r1/events") return stream.response;
    return { status: 404, body: {} };
  });
  renderApp("/");
  const user = userEvent.setup();
  await ask(user);

  stream.push(
    sse(1, "run_started", {
      run_id: "r1",
      conversation_id: "c1",
      as_of: "2026-10-16",
      role: "analyst",
    }),
  );
  stream.push(sse(2, "node", { node: "retrieve", status: "finished", latency_ms: 40 }));
  stream.push(sse(3, "claim", CLAIM));

  const claims = await screen.findByRole("region", { name: /answer/i });
  await within(claims).findByText(/older than 90 days at the date of onboarding/);
  expect(claims).toHaveAttribute("aria-live", "polite");
  expect(screen.getByText(/retrieve/i)).toBeInTheDocument();
  expect(screen.queryByText(/KYC-0042 v3/)).toBeNull(); // no final yet

  const chip = within(claims).getByRole("link", { name: /\[1\] citation: KYC-0042 v3/i });
  expect(chip).toHaveAttribute("href", expect.stringContaining(`/evidence/${"c".repeat(32)}`));
  chip.focus();
  expect(chip).toHaveFocus();

  stream.push(sse(4, "final", FINAL));
  stream.close();
  expect(await screen.findByText(/KYC-0042 v3/)).toBeInTheDocument();
  expect(screen.getByText(/as of 2026-10-16/i)).toBeInTheDocument();
  expect(screen.getByText("AI-generated")).toBeInTheDocument();
  expect(screen.getByText(/confidence 0\.91/i)).toBeInTheDocument();

  const body = JSON.parse(String(calls[0].init?.body));
  expect(body).toMatchObject({ question: QUESTION, stream: true });
});

test("a retracted claim disappears and an abstention shows the uniform banner", async () => {
  const stream = controlledStream();
  mockFetch((url) =>
    url === "/v1/ask"
      ? { status: 202, body: { run_id: "r2", events_url: "/v1/runs/r2/events" } }
      : stream.response,
  );
  renderApp("/");
  const user = userEvent.setup();
  await ask(user);
  stream.push(sse(1, "claim", CLAIM));
  await screen.findByText(/older than 90 days at the date/);
  stream.push(sse(2, "claim_rejected", { index: 0, reason: "retracted" }));
  await waitFor(() => expect(screen.queryByText(/older than 90 days at the date/)).toBeNull());
  stream.push(
    sse(3, "final", {
      ...FINAL,
      claims: [],
      answer: "",
      abstained: true,
      message: "I can't answer that from the policy documents available to you.",
      versions: [],
      confidence: null,
      cost_usd: null,
    }),
  );
  stream.close();
  expect(await screen.findByRole("status", { name: /no answer/i })).toHaveTextContent(
    /can't answer that/,
  );
});

test("a stream error and a 429 both show a problem with retry", async () => {
  const stream = controlledStream();
  let asks = 0;
  mockFetch((url) => {
    if (url === "/v1/ask") {
      asks += 1;
      return asks === 1
        ? { status: 202, body: { run_id: "r3", events_url: "/v1/runs/r3/events" } }
        : {
            status: 429,
            body: {
              type: "x",
              title: "Too Many Requests",
              status: 429,
              detail: "at most 30 questions per minute",
            },
            headers: { "Retry-After": "12" },
          };
    }
    return stream.response;
  });
  renderApp("/");
  const user = userEvent.setup();
  await ask(user);
  stream.push(
    sse(1, "error", {
      code: "retrieval_unavailable",
      message: "retrieval is unavailable",
      retryable: true,
    }),
  );
  stream.close();
  const alert = await screen.findByRole("alert");
  expect(alert).toHaveTextContent(/retrieval is unavailable/i);
  await user.click(within(alert).getByRole("button", { name: /retry/i }));
  const limited = await screen.findByRole("alert");
  await waitFor(() => expect(limited).toHaveTextContent(/30 questions per minute/));
  expect(limited).toHaveTextContent(/12 s/);
});

test("feedback posts a rating and reason for the run", async () => {
  const stream = controlledStream();
  const calls = mockFetch((url) => {
    if (url === "/v1/ask")
      return { status: 202, body: { run_id: "r1", events_url: "/v1/runs/r1/events" } };
    if (url === "/v1/feedback") return { status: 201, body: { id: "f1" } };
    return stream.response;
  });
  renderApp("/");
  const user = userEvent.setup();
  await ask(user);
  stream.push(sse(1, "final", FINAL));
  stream.close();
  await screen.findByText(/KYC-0042 v3/);
  await user.click(screen.getByRole("button", { name: "Helpful" }));
  await user.click(screen.getByRole("button", { name: /send feedback/i }));
  expect(await screen.findByText(/thanks/i)).toBeInTheDocument();
  const post = calls.find((c) => c.url === "/v1/feedback");
  expect(JSON.parse(String(post?.init?.body))).toEqual({
    run_id: "r1",
    rating: "up",
    reason: "correct",
  });
});

test("the answer survives opening the evidence and coming back", async () => {
  const stream = controlledStream();
  mockFetch((url) => {
    if (url === "/v1/ask")
      return { status: 202, body: { run_id: "r1", events_url: "/v1/runs/r1/events" } };
    if (url === "/v1/runs/r1/events") return stream.response;
    return {
      status: 200,
      body: {
        ...FINAL.versions[0],
        chunk_id: "c".repeat(32),
        text: "x",
        section_path: "s",
        char_start: 0,
        char_end: 1,
        current_version: 3,
      },
    };
  });
  renderApp("/");
  const user = userEvent.setup();
  await ask(user);
  stream.push(sse(1, "final", FINAL));
  stream.close();
  await screen.findByText(/KYC-0042 v3/);
  await user.click(screen.getByRole("link", { name: /\[1\] citation/i }));
  await screen.findByRole("button", { name: "Back" });
  await user.click(screen.getByRole("link", { name: "Ask" }));
  expect(
    await screen.findByText(/older than 90 days at the date of onboarding/),
  ).toBeInTheDocument();
  expect(screen.getByLabelText(/question/i)).toHaveValue(QUESTION);
});

test("an answer is not shown to the next persona", async () => {
  const stream = controlledStream();
  mockFetch((url, init) => {
    if (url === "/v1/ask")
      return { status: 202, body: { run_id: "r1", events_url: "/v1/runs/r1/events" } };
    if (url === "/v1/runs/r1/events") return stream.response;
    if (url.endsWith("/oidc/dev/token")) {
      return {
        status: 200,
        body: { access_token: fakeToken(JSON.parse(String(init?.body)).persona) },
      };
    }
    return { status: 404, body: {} };
  });
  renderApp("/");
  const user = userEvent.setup();
  await ask(user);
  stream.push(sse(1, "final", FINAL));
  stream.close();
  await screen.findByText(/KYC-0042 v3/);
  await user.selectOptions(screen.getByLabelText(/persona/i), "support");
  await waitFor(() => expect(screen.getByText(/support@northwind\.test/)).toBeInTheDocument());
  expect(screen.queryByText(/older than 90 days/)).toBeNull();
  expect(screen.queryByText(/KYC-0042 v3/)).toBeNull();
  expect(screen.getByLabelText(/question/i)).toHaveValue("");
});

test("claims streamed before an error do not stay on screen as a partial answer", async () => {
  const stream = controlledStream();
  mockFetch((url) =>
    url === "/v1/ask"
      ? { status: 202, body: { run_id: "r4", events_url: "/v1/runs/r4/events" } }
      : stream.response,
  );
  renderApp("/");
  const user = userEvent.setup();
  await ask(user);
  stream.push(sse(1, "claim", CLAIM));
  expect(
    await screen.findByText(/must not be older than 90 days at the date/i),
  ).toBeInTheDocument();
  stream.push(
    sse(2, "error", {
      code: "generation_unavailable",
      message: "generation is unavailable",
      retryable: true,
    }),
  );
  stream.close();
  expect(await screen.findByRole("alert")).toHaveTextContent(/generation is unavailable/i);
  expect(screen.queryByText(/must not be older than 90 days at the date/i)).not.toBeInTheDocument();
});
