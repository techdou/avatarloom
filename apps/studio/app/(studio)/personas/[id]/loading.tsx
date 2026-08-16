import { Skeleton } from "@/components/ui/skeleton";

export default function Loading() {
  return (
    <div className="grid grid-cols-1 lg:grid-cols-3 gap-6">
      <div className="space-y-4">
        <Skeleton className="h-48" />
        <Skeleton className="h-32" />
      </div>
      <Skeleton className="h-96 lg:col-span-2" />
    </div>
  );
}
