import { render, screen } from "@testing-library/react";
import { describe, expect, it } from "vitest";

import Home, { PROVISIONAL_NOTICE } from "./page";

/**
 * These protect a project rule, not a rendering detail.
 *
 * M0 is deployed publicly while it is still a skeleton. The rule is that it makes no model claims,
 * so the page must carry a visible statement that nothing here has been evaluated. If someone later
 * deletes the notice while the model is still absent, this test fails and says why.
 */
describe("M0 landing page", () => {
  it("identifies the project", () => {
    render(<Home />);

    expect(
      screen.getByRole("heading", { level: 1, name: /touchline intelligence platform/i }),
    ).toBeInTheDocument();
  });

  it("states that no evaluated model is present yet", () => {
    render(<Home />);

    expect(screen.getByRole("note")).toHaveTextContent(PROVISIONAL_NOTICE);
  });

  it("attributes StatsBomb as the data source", () => {
    render(<Home />);

    expect(screen.getByText(/data provided by statsbomb/i)).toBeInTheDocument();
  });
});
