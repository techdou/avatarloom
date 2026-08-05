import { Skeleton } from "@/components/ui/skeleton";

/** Avatar 详情加载占位——匹配 3 列布局（信息 / 预览 / 上传）。 */
export default function Loading() {
  return (
    <div>
      <div className="flex items-center gap-3 mb-6 text-sm">
        <Skeleton className="h-4 w-24" />
        <Skeleton className="h-4 w-3" />
        <Skeleton className="h-4 w-32" />
      </div>
      <div className="grid grid-cols-1 lg:grid-cols-3 gap-6">
        {/* 左：信息 */}
        <div className="space-y-4">
          <div className="card">
            <Skeleton className="h-5 w-24 mb-3" />
            <div className="space-y-3">
              {[0, 1, 2, 3].map((i) => (
                <div key={i} className="flex items-center justify-between">
                  <Skeleton className="h-4 w-16" />
                  <Skeleton className="h-4 w-28" />
                </div>
              ))}
            </div>
          </div>
          <div className="card">
            <Skeleton className="h-5 w-32 mb-2" />
            <Skeleton className="h-4 w-full mb-3" />
            <Skeleton className="h-20 w-full rounded-lg" />
          </div>
        </div>
        {/* 中：预览 */}
        <div className="space-y-4">
          <div className="card">
            <Skeleton className="h-5 w-24 mb-3" />
            <Skeleton className="aspect-[4/3] w-full rounded-md" />
          </div>
          <div className="card">
            <Skeleton className="h-5 w-28 mb-3" />
            <Skeleton className="aspect-video w-full rounded-md" />
          </div>
        </div>
        {/* 右：上传 */}
        <div className="space-y-3">
          <Skeleton className="h-4 w-20" />
          {[0, 1, 2].map((i) => (
            <div key={i} className="border border-border rounded-md p-3">
              <Skeleton className="h-4 w-28 mb-2" />
              <Skeleton className="h-16 w-full rounded-md" />
            </div>
          ))}
        </div>
      </div>
    </div>
  );
}
