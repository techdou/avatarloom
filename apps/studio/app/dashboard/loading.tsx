import { Skeleton } from "@/components/ui/skeleton";

/** Dashboard 加载占位——匹配总览页布局（3 stat 卡片 + 快速开始卡片）。 */
export default function Loading() {
  return (
    <div>
      <div className="page-header">
        <div>
          <Skeleton className="h-7 w-32" />
          <Skeleton className="h-4 w-72 mt-2" />
        </div>
        <Skeleton className="h-9 w-36 rounded-lg" />
      </div>

      <div className="grid grid-cols-1 sm:grid-cols-3 gap-4 mb-8">
        {[0, 1, 2].map((i) => (
          <div key={i} className="card">
            <div className="flex items-center justify-between">
              <Skeleton className="h-4 w-28" />
              <Skeleton className="h-5 w-14 rounded-md" />
            </div>
            <Skeleton className="h-8 w-12 mt-2" />
          </div>
        ))}
      </div>

      <div className="card">
        <Skeleton className="h-5 w-24 mb-4" />
        <div className="space-y-3">
          {[0, 1, 2, 3].map((i) => (
            <div key={i} className="flex items-start gap-3">
              <Skeleton className="w-5 h-5 rounded-full shrink-0" />
              <div className="flex-1 space-y-1.5">
                <Skeleton className="h-4 w-48" />
                <Skeleton className="h-3 w-72" />
              </div>
            </div>
          ))}
        </div>
      </div>
    </div>
  );
}
