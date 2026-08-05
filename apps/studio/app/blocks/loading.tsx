import { Skeleton } from "@/components/ui/skeleton";

/** Blocks 加载占位——匹配按 category 分组的列表布局。 */
export default function Loading() {
  return (
    <div>
      <Skeleton className="h-7 w-36 mb-6" />
      <div className="space-y-6">
        {[0, 1].map((g) => (
          <div key={g}>
            <Skeleton className="h-4 w-28 mb-2" />
            <div className="space-y-1">
              {[0, 1, 2].map((i) => (
                <div key={i} className="card flex items-center justify-between py-3">
                  <div className="space-y-1.5">
                    <Skeleton className="h-4 w-40" />
                    <Skeleton className="h-3 w-24" />
                  </div>
                  <div className="flex items-center gap-2">
                    <Skeleton className="h-5 w-20 rounded-md" />
                    <Skeleton className="h-5 w-16 rounded-md" />
                  </div>
                </div>
              ))}
            </div>
          </div>
        ))}
      </div>
    </div>
  );
}
