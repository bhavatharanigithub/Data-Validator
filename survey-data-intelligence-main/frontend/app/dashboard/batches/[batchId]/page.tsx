import BatchDetailPage from "@/components/batches/batch-detail-page";

export const dynamic = "force-dynamic";

export default async function BatchDetailRoute({
  params,
  searchParams,
}: {
  params: Promise<{ batchId: string }>;
  searchParams: Promise<{ run?: string | string[] }>;
}) {
  const resolved = await params;
  const query = await searchParams;
  const raw = resolved?.batchId;
  const batchId = Array.isArray(raw) ? String(raw[0] ?? "") : String(raw ?? "");
  const rawRun = Array.isArray(query?.run) ? query.run[0] : query?.run;
  const pipelineRunId = rawRun && /^\d+$/.test(rawRun) ? Number(rawRun) : null;
  return <BatchDetailPage batchId={batchId} pipelineRunId={pipelineRunId} />;
}
