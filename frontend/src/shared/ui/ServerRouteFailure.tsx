import { ApiError } from "../api/client";
import { RouteRetryButton } from "./RouteRetryButton";

export interface ServerRouteFailureData {
  status: number;
  code: string;
  correlationId?: string;
}

export type ServerRouteResult<T> =
  | { ok: true; value: T }
  | { ok: false; failure: ServerRouteFailureData };

export function toServerRouteFailure(error: ApiError): ServerRouteFailureData {
  return {
    status: error.status,
    code: error.code,
    ...(error.correlationId ? { correlationId: error.correlationId } : {}),
  };
}

export async function captureServerRoute<T>(
  operation: () => Promise<T>,
): Promise<ServerRouteResult<T>> {
  try {
    return { ok: true, value: await operation() };
  } catch (error) {
    if (!(error instanceof ApiError)) throw error;
    return { ok: false, failure: toServerRouteFailure(error) };
  }
}

export function ServerRouteFailure({
  failure,
}: {
  failure: ServerRouteFailureData;
}) {
  return (
    <main
      className="route-error"
      role="alert"
      data-upstream-status={failure.status}
      data-error-code={failure.code}
    >
      <p className="eyebrow">REQUEST FAILED</p>
      <h1>화면을 불러오지 못했습니다.</h1>
      <p>서버 상태를 확인한 뒤 다시 시도해 주세요.</p>
      {failure.correlationId ? (
        <p>오류 참조: {failure.correlationId}</p>
      ) : null}
      <RouteRetryButton />
    </main>
  );
}
