import type { ComponentProps } from "react";

// Router boundary only; the harness exercises no Next navigation or authenticated route.
export default function Link(props: ComponentProps<"a">) {
  return <a {...props} />;
}
