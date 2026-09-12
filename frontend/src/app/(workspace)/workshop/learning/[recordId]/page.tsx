import { LearningRecordPage } from "../../../../../features/learning/LearningRecordPage";

export default async function LearningDetailRoute({
  params,
}: {
  params: Promise<{ recordId: string }>;
}) {
  const { recordId } = await params;
  return <LearningRecordPage recordId={recordId} />;
}
