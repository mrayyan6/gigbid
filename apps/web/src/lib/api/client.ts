// Typed API client. Types come from the generated schema (npm run gen:api), never hand edited.
import createClient, { type Middleware } from "openapi-fetch";
import type { paths, components } from "./schema";
import { clearSession, getToken } from "../auth";

export type Schemas = components["schemas"];

const authMiddleware: Middleware = {
  onRequest({ request }) {
    const token = getToken();
    if (token) request.headers.set("Authorization", `Bearer ${token}`);
    return request;
  },
  onResponse({ response, request }) {
    const isLogin = new URL(request.url).pathname.endsWith("/auth/login");
    if (response.status === 401 && !isLogin && typeof window !== "undefined") {
      clearSession();
      if (window.location.pathname !== "/login") window.location.assign("/login");
    }
    return response;
  },
};

export const api = createClient<paths>({ baseUrl: "" });
api.use(authMiddleware);

export class ApiError extends Error {
  status: number;
  constructor(message: string, status: number) {
    super(message);
    this.status = status;
  }
}

function detailOf(error: unknown): string {
  if (error && typeof error === "object" && "detail" in error) {
    const d = (error as { detail: unknown }).detail;
    if (typeof d === "string") return d;
    try {
      return JSON.stringify(d);
    } catch {
      return "request failed";
    }
  }
  return "request failed";
}

type Result<T> = { data?: T; error?: unknown; response: Response };

/** Turn an openapi-fetch result into data or a thrown ApiError. */
export async function unwrap<T>(p: Promise<Result<T>>): Promise<T> {
  let r: Result<T>;
  try {
    r = await p;
  } catch {
    throw new ApiError("Cannot reach the API", 0);
  }
  if (r.error !== undefined || r.data === undefined) {
    throw new ApiError(detailOf(r.error), r.response.status);
  }
  return r.data;
}

export function errorMessage(e: unknown): string {
  if (e instanceof ApiError) return e.message;
  if (e instanceof Error) return e.message;
  return "Something went wrong";
}
