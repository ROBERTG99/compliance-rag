import { render, screen } from "@testing-library/react";
import App from "./App";

test("renders the application shell", () => {
  render(<App />);
  expect(screen.getByRole("heading", { name: /compliance assistant/i })).toBeInTheDocument();
});
