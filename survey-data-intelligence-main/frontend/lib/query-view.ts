export type QueryView = "loading" | "error" | "empty" | "ready";

export function queryView(
  state: { isPending?: boolean; isError?: boolean },
  hasItems: boolean
): QueryView {
  if (state.isPending) return "loading";
  if (state.isError) return "error";
  if (!hasItems) return "empty";
  return "ready";
}

export function pipelineHeadline(status: string | null | undefined): string {
  switch (status) {
    case "PENDING":
      return "PENDING";
    case "RUNNING":
      return "RUNNING";
    case "COMPLETED":
      return "COMPLETED";
    case "PARTIAL":
      return "PARTIAL";
    case "FAILED":
      return "FAILED";
    default:
      return status || "UNKNOWN";
  }
}
