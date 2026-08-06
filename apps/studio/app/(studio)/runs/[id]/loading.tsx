import { Skeleton } from "@/components/ui/skeleton";

/** Run 详情加载占位——匹配详情页 3 列布局（指标/管道 + 可靠性/产物）。 */
export default function Loading() {
  return (
    <div>
      <div className="flex items-center gap-3 mb-5 text-sm">
        <Skeleton className="h-4 w-20" />
        <Skeleton className="h-4 w-3" />
        <Skeleton className="h-4 w-48" />
      </div>
      <div className="page-header">
        <div>
          <Skeleton className="h-7 w-28" />
          <Skeleton className="h-4 w-64 mt-2" />
        </div>
        <Skeleton className="h-8 w-24 rounded-lg" />
      </div>
      <div className="grid grid-cols-1 lg:grid-cols-3 gap-6">
        <div className="lg:col-span-2 space-y-6">
          <div className="card">
            <Skeleton className="h-5 w-24 mb-1" />
            <Skeleton className="h-3 w-72 mb-4" />
            <div className="space-y-3">
              {[0, 1, 2, 3].map((i) => (
                <div key={i}>
                  <div className="flex justify-between mb-1.5">
                    <Skeleton className="h-3 w-24" />
                    <Skeleton className="h-3 w-14" />
                  </div>
                  <Skeleton className="h-2 w-full rounded-full" />
                </div>
              ))}
            </div>
          </div>
          <div className="card">
            <Skeleton className="h-5 w-20 mb-4" />
            <div className="space-y-4">
              {[0, 1, 2, 3, 4].map((i) => (
                <div key={i} className="flex items-center gap-3">
                  <Skeleton className="w-3.5 h-3.5 rounded-full" />
                  <Skeleton className="h-4 w-40" />
                </div>
              ))}
            </div>
          </div>
        </div>
        <div className="space-y-6">
          <div className="card">
            <Skeleton className="h-5 w-20 mb-3" />
            <div className="grid grid-cols-2 gap-3">
              {[0, 1, 2, 3].map((i) => (
                <div key={i}>
                  <Skeleton className="h-3 w-16" />
                  <Skeleton className="h-6 w-12 mt-1" />
                </div>
              ))}
            </div>
          </div>
          <div className="card">
            <Skeleton className="h-5 w-16 mb-3" />
            <div className="space-y-2">
              {[0, 1].map((i) => (
                <Skeleton key={i} className="h-14 w-full rounded-md" />
              ))}
            </div>
          </div>
        </div>
      </div>
    </div>
  );
}
