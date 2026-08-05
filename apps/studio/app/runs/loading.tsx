import { Skeleton } from "@/components/ui/skeleton";

/** Runs 加载占位——匹配 run 列表卡片布局（含 metrics 4 列）。 */
export default function Loading() {
  return (
    <div>
      <Skeleton className="h-7 w-20 mb-6" />
      <div className="space-y-2">
        {[0, 1, 2, 3].map((i) => (
          <div key={i} className="card">
            <div className="flex items-center justify-between mb-2">
              <Skeleton className="h-4 w-48" />
              <div className="flex items-center gap-2">
                <Skeleton className="h-5 w-16 rounded-md" />
                <Skeleton className="h-4 w-36" />
              </div>
            </div>
            <div className="grid grid-cols-4 gap-3">
              {[0, 1, 2, 3].map((j) => (
                <div key={j}>
                  <Skeleton className="h-3 w-10" />
                  <Skeleton className="h-4 w-16 mt-1" />
                </div>
              ))}
            </div>
          </div>
        ))}
      </div>
    </div>
  );
}
