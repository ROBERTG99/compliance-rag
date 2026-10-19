import { screen, within } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import { afterEach, beforeEach, expect, test, vi } from "vitest";
import { mockFetch, renderApp, signInAs } from "../../test/render";

const PAGE = {
  items: [
    {
      document_id: "CMP-0215",
      title: "Litigation Hold",
      domain: "complaints",
      owner: "Legal",
      current_version: 2,
      versions: 2,
      restricted: true,
      acl_groups: ["legal"],
    },
    {
      document_id: "KYC-0042",
      title: "Proof of Address Requirements",
      domain: "kyc",
      owner: "Compliance",
      current_version: 3,
      versions: 3,
      restricted: false,
      acl_groups: ["all"],
    },
  ],
  next_cursor: "S1lDLTAwNDI=",
};
const DETAIL = {
  document_id: "KYC-0042",
  title: "Proof of Address Requirements",
  domain: "kyc",
  owner: "Compliance",
  restricted: false,
  versions: [
    {
      version: 2,
      status: "active",
      source_format: "md",
      valid_from: "2025-01-01",
      valid_to: "2026-03-01",
      uploaded_at: "2025-01-01T00:00:00Z",
      activated_at: "2025-01-01T00:00:00Z",
      size_bytes: 100,
      chunks: 4,
      in_force: false,
    },
    {
      version: 3,
      status: "active",
      source_format: "md",
      valid_from: "2026-03-01",
      valid_to: null,
      uploaded_at: "2026-03-01T00:00:00Z",
      activated_at: "2026-03-01T00:00:00Z",
      size_bytes: 120,
      chunks: 5,
      in_force: true,
    },
  ],
};

beforeEach(() => sessionStorage.clear());
afterEach(() => vi.unstubAllGlobals());

test("admins see restricted badges; filters reach the API; more pages load", async () => {
  signInAs("admin");
  const calls = mockFetch((url) =>
    url.startsWith("/v1/documents?") || url === "/v1/documents"
      ? { status: 200, body: url.includes("cursor=") ? { items: [], next_cursor: null } : PAGE }
      : { status: 404, body: {} },
  );
  renderApp("/library");
  const list = await screen.findByRole("list", { name: /documents/i });
  const restricted = within(list).getByText("CMP-0215").closest("li")!;
  expect(within(restricted).getByText(/restricted · legal/i)).toBeInTheDocument();
  const user = userEvent.setup();
  await user.selectOptions(screen.getByLabelText(/domain/i), "kyc");
  await user.click(screen.getByRole("button", { name: /load more/i }));
  expect(calls.some((c) => c.url.includes("domain=kyc"))).toBe(true);
  expect(calls.some((c) => c.url.includes("cursor="))).toBe(true);
});

test("non-admins do not see ACL groups", async () => {
  signInAs("analyst");
  mockFetch(() => ({
    status: 200,
    body: { ...PAGE, items: PAGE.items.map((d) => ({ ...d, acl_groups: undefined })) },
  }));
  renderApp("/library");
  await screen.findByText("KYC-0042");
  expect(screen.queryByText(/restricted ·/i)).toBeNull();
});

test("a document shows its versions timeline with the version in force", async () => {
  signInAs("analyst");
  mockFetch((url) =>
    url === "/v1/documents/KYC-0042" ? { status: 200, body: DETAIL } : { status: 404, body: {} },
  );
  renderApp("/library/KYC-0042");
  const timeline = await screen.findByRole("list", { name: /versions/i });
  const items = within(timeline).getAllByRole("listitem");
  expect(items).toHaveLength(2);
  expect(within(items[1]).getByText(/in force/i)).toBeInTheDocument();
  expect(within(items[0]).getByText(/superseded/i)).toBeInTheDocument();
});
