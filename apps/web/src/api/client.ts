const BASE_URL = import.meta.env.VITE_API_URL ?? 'http://localhost:8000';

export class ApiError extends Error {
  readonly status: number;
  readonly notes: string[];

  constructor(status: number, message: string, notes: string[] = []) {
    super(message);
    this.name = 'ApiError';
    this.status = status;
    this.notes = notes;
  }
}

async function parseErrorBody(response: Response): Promise<ApiError> {
  try {
    const body = (await response.json()) as {
      detail?: string | { msg?: string }[];
      notes?: string[];
    };
    const message =
      typeof body.detail === 'string'
        ? body.detail
        : Array.isArray(body.detail)
          ? (body.detail[0]?.msg ?? response.statusText)
          : response.statusText;
    return new ApiError(response.status, message, body.notes ?? []);
  } catch {
    return new ApiError(response.status, response.statusText);
  }
}

export async function apiFetch<T>(path: string, init?: RequestInit): Promise<T> {
  const response = await fetch(`${BASE_URL}${path}`, {
    ...init,
    headers: {
      Accept: 'application/json',
      ...(init?.body ? { 'Content-Type': 'application/json' } : {}),
      ...init?.headers,
    },
  });

  if (!response.ok) {
    throw await parseErrorBody(response);
  }

  if (response.status === 204) {
    return undefined as T;
  }

  return (await response.json()) as T;
}
