import { fireEvent, render, screen } from "@testing-library/react";
import { expect, it, vi } from "vitest";

import GlobalError from "./error";

it("renders an accessible retry boundary without exposing an error message", () => {
  const reset = vi.fn();
  render(<GlobalError error={new Error("database password should not render")} reset={reset} />);

  expect(screen.getByRole("heading", { name: /could not be displayed/i })).toBeInTheDocument();
  expect(screen.queryByText(/database password/i)).not.toBeInTheDocument();
  fireEvent.click(screen.getByRole("button", { name: /retry/i }));
  expect(reset).toHaveBeenCalledOnce();
});
