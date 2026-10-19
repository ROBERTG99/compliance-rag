import { screen } from "@testing-library/react";
import { beforeEach, expect, test } from "vitest";
import { renderApp, signInAs } from "./test/render";

beforeEach(() => sessionStorage.clear());

test("signed-out visitors are asked to sign in", () => {
  renderApp("/");
  expect(screen.getByRole("heading", { name: /sign in to continue/i })).toBeInTheDocument();
});

test("admin screens look like unknown pages to other roles", () => {
  signInAs("analyst");
  renderApp("/jobs");
  expect(screen.getByRole("heading", { name: /page not found/i })).toBeInTheDocument();
});

test("admins reach the admin screens", () => {
  signInAs("admin");
  renderApp("/jobs");
  expect(screen.getByRole("heading", { name: /ingestion jobs/i })).toBeInTheDocument();
});
