import { Skeleton } from "@/components/ui/skeleton";

/** Profiles 加载占位——匹配 profile 卡片列表布局。 */
export default function Loading() {
  return (
    <div>
      <div className="page-header">
        <div>
          <Skeleton className="h-7 w-36" />
          <Skeleton className="h-4 w-80 mt-2" />
        </div>
        <Skeleton className="h-5 w-20 rounded-md" />
      </div>
      <div className="space-y-3">
        {[0, 1, 2].map((i) => (
          <div key={i} className="card">
            <div className="flex items-start justify-between gap-3 mb-2">
              <Skeleton className="h-5 w-40" />
              <div className="flex items-center gap-2">
                <Skeleton className="h-5 w-16 rounded-md" />
                <Skeleton className="h-4 w-28" />
              </div>
            </div>
            <Skeleton className="h-4 w-full" />
            <div className="flex flex-wrap gap-1.5 mt-3">
              {[0, 1, 2].map((j) => (
                <Skeleton key={j} className="h-5 w-24 rounded-md" />
              ))}
            </div>
          </div>
        ))}
      </div>
    </div>
  );
}
