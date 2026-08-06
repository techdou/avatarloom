import { CreateAvatarForm } from "@/components/avatar/create-form";

export default function NewAvatarPage() {
  return (
    <div>
      <h1 className="mb-6">新建 Avatar</h1>
      <div className="max-w-lg">
        <div className="card">
          <p className="text-sm text-fg-muted mb-4">
            创建一个独立的数字人形象实体。创建后可上传肖像图、idle 视频、音色参考。
            Avatar 与 Persona 解耦——多个 Persona 可以引用同一个 Avatar。
          </p>
          <CreateAvatarForm />
        </div>
      </div>
    </div>
  );
}
