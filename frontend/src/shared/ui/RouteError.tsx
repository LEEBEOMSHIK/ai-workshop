"use client";

interface RouteErrorProps {
  error: Error & { digest?: string };
  reset: () => void;
}

export function RouteError({ error, reset }: RouteErrorProps) {
  return (
    <main className="route-error" role="alert">
      <p className="eyebrow">REQUEST FAILED</p>
      <h1>화면을 불러오지 못했습니다.</h1>
      <p>서버 상태를 확인한 뒤 다시 시도해 주세요.</p>
      {error.digest ? <p>프론트 진단 참조: {error.digest}</p> : null}
      <button type="button" onClick={reset}>다시 시도</button>
    </main>
  );
}
