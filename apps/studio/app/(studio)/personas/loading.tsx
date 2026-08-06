import { Skeleton } from "@/components/ui/skeleton";

/** Personas 加载占位——匹配 persona 列表卡片布局。 */
export default function Loading() {
  return (
    <div>
      <div className="page-header">
        <div>
          <Skeleton className="h-7 w-24" />
          <Skeleton className="h-4 w-64 mt-2" />
        </div>
        <Skeleton className="h-9 w-16 rounded-lg" />
      </div>
      <div className="space-y-2.5">
        {[0, 1, 2, 3].map((i) => (
          <div key={i} className="card">
            <div className="flex items-start justify-between gap-3">
              <div className="flex items-center gap-2">
                <Skeleton className="w-8 h-8 rounded-lg" />
                <div className="space-y-1.5">
                  <Skeleton className="h-4 w-32" />
                  <Skeleton className="h-3 w-24" />
                </div>
              </div>
              <Skeleton className="h-4 w-32" />
            </div>
            <Skeleton className="h-4 w-full mt-3" />
            <Skeleton className="h-4 w-3/4 mt-1.5" />
          </div>
        ))}
      </div>
    </div>
  );
}
