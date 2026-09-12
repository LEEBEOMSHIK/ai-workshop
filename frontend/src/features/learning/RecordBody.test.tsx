import { render, screen } from "@testing-library/react";

import { RecordBody } from "./RecordBody";

describe("RecordBody", () => {
  it("renders hostile HTML and Markdown as plain text without active nodes", () => {
    const body = '<script>alert(1)</script> <a href="https://invalid.test">link</a> ![x](https://invalid.test/x)';
    const { container } = render(<RecordBody body={body} />);

    expect(screen.getByText(body)).toBeVisible();
    expect(container.querySelector("script")).toBeNull();
    expect(container.querySelector("img")).toBeNull();
    expect(container.querySelector("a")).toBeNull();
  });
});
