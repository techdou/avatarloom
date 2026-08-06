import { Skeleton } from "@/components/ui/skeleton";

/** Avatars 加载占位——匹配 4 列头像卡片网格布局。 */
export default function Loading() {
  return (
    <div>
      <div className="page-header">
        <div>
          <Skeleton className="h-7 w-32" />
          <Skeleton className="h-4 w-72 mt-2" />
        </div>
        <Skeleton className="h-9 w-16 rounded-lg" />
      </div>
      <div className="grid grid-cols-1 sm:grid-cols-2 md:grid-cols-3 lg:grid-cols-4 gap-4">
        {[0, 1, 2, 3, 4, 5, 6, 7].map((i) => (
          <div key={i} className="card p-0 overflow-hidden">
            <Skeleton className="aspect-[4/3] w-full rounded-none" />
            <div className="p-3.5 space-y-2">
              <Skeleton className="h-4 w-24" />
              <div className="flex items-center gap-1.5">
                <Skeleton className="h-4 w-12 rounded-md" />
                <Skeleton className="h-4 w-20 rounded-md" />
              </div>
            </div>
          </div>
        ))}
      </div>
    </div>
  );
}
