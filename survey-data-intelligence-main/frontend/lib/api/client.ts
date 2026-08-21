const API_BASE_URL = process.env.NEXT_PUBLIC_API_BASE_URL ?? "";

export class ApiError extends Error {
  status: number;
  constructor(status: number, message: string) {
    super(message);
    this.status = status;
  }
}

async function parse<T>(response: Response): Promise<T> {
  if (!response.ok) {
    let message = `Request failed: ${response.status}`;
    try {
      const body = await response.clone().json();
      if (body && typeof body.detail === "string") message = body.detail;
    } catch {
      // response wasn't JSON (or had no body); keep the generic message
    }
    throw new ApiError(response.status, message);
  }
  if (response.status === 204) return undefined as T;
  const text = await response.text();
  if (!text) return undefined as T;
  try {
    return JSON.parse(text) as T;
  } catch {
    throw new ApiError(response.status, "The server returned an invalid response.");
  }
}

async function request<T>(input: RequestInfo | URL, init?: RequestInit): Promise<T> {
  try {
    return await parse<T>(await fetch(input, init));
  } catch (error) {
    if (error instanceof ApiError) throw error;
    throw new ApiError(0, "The validation service is unavailable.");
  }
}

export async function apiGet<T>(path: string): Promise<T> {
  return request<T>(`${API_BASE_URL}${path}`, { credentials: "include" });
}

export async function apiPost<T>(path: string, body?: unknown): Promise<T> {
  return request<T>(`${API_BASE_URL}${path}`, {
    method: "POST",
    credentials: "include",
    headers: body ? { "Content-Type": "application/json" } : undefined,
    body: body ? JSON.stringify(body) : undefined,
  });
}

export async function apiPatch<T>(path: string, body?: unknown): Promise<T> {
  return request<T>(`${API_BASE_URL}${path}`, {
    method: "PATCH",
    credentials: "include",
    headers: body ? { "Content-Type": "application/json" } : undefined,
    body: body ? JSON.stringify(body) : undefined,
  });
}

export async function apiPostForm<T>(path: string, form: FormData): Promise<T> {
  return request<T>(`${API_BASE_URL}${path}`, { method: "POST", credentials: "include", body: form });
}

export function reportUrl(kind: string, batchId: string, view: string = "current_batch"): string {
  const base = API_BASE_URL || "";
  const search = new URLSearchParams();
  if (view === "cumulative") {
    search.set("view", "cumulative");
  } else {
    search.set("batch_id", batchId);
  }
  return `${base}/api/dashboard/reports/${kind}?${search.toString()}`;
}

export { API_BASE_URL };
