export interface SessionUser {
  id: string;
  display_name: string;
  email: string;
  role: "owner";
}

export interface ApiErrorBody {
  error?: {
    code?: string;
    message?: string;
    correlation_id?: string;
  };
}

export class ApiError extends Error {
  constructor(
    message: string,
    public readonly status: number,
    public readonly correlationId?: string,
  ) {
    super(message);
  }
}
