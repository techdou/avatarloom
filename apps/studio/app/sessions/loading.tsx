import { Skeleton } from "@/components/ui/skeleton";

/** Sessions 加载占位——匹配会话列表行布局。 */
export default function Loading() {
  return (
    <div>
      <Skeleton className="h-7 w-24 mb-6" />
      <div className="space-y-1">
        {[0, 1, 2, 3, 4, 5].map((i) => (
          <div key={i} className="card flex items-center justify-between py-3">
            <Skeleton className="h-4 w-48" />
            <div className="flex items-center gap-3">
              <Skeleton className="h-5 w-16 rounded-md" />
              <Skeleton className="h-4 w-40" />
            </div>
          </div>
        ))}
      </div>
    </div>
  );
}
