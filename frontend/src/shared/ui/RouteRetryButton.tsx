"use client";

import { useRouter } from "next/navigation";

export function RouteRetryButton() {
  const router = useRouter();
  return (
    <button type="button" onClick={() => router.refresh()}>
      다시 시도
    </button>
  );
}
