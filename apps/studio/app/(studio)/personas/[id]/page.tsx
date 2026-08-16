import Link from "next/link";
import { notFound } from "next/navigation";
import { apiFetch, type Persona } from "@/lib/api";
import { PersonaEditor } from "@/components/persona/prompt-editor";

interface PageProps {
  params: { id: string };
}

async function getPersona(id: string): Promise<Persona | null> {
  try {
    return await apiFetch<Persona>(`/personas/${id}`);
  } catch {
    return null;
  }
}

/** Persona 详情页——基本信息 + 系统提示词编辑（PATCH /personas/{id}）。 */
export default async function PersonaDetailPage({ params }: PageProps) {
  const persona = await getPersona(params.id);
  if (!persona) {
    notFound();
  }

  return (
    <div>
      {/* 顶部导航 */}
      <div className="flex items-center gap-3 mb-6 text-sm">
        <Link href="/personas" className="text-fg-muted hover:text-fg">← Personas</Link>
        <span className="text-fg-subtle">/</span>
        <span className="font-medium">{persona.name}</span>
      </div>

      <div className="grid grid-cols-1 lg:grid-cols-3 gap-6">
        {/* 左：基本信息 */}
        <div className="space-y-4">
          <div className="card">
            <h3 className="mb-3">基本信息</h3>
            <dl className="text-sm space-y-2">
              <InfoRow label="ID" value={<code className="text-xs">{persona.id}</code>} />
              <InfoRow label="名称" value={persona.name} />
              <InfoRow
                label="标签"
                value={persona.label ? <span className="badge">{persona.label}</span> : "—"}
              />
              <InfoRow label="版本" value={<code className="text-xs">{persona.version}</code>} />
              <InfoRow
                label="关联 Avatar"
                value={persona.avatar_id ? <code className="text-xs">{persona.avatar_id}</code> : "—"}
              />
            </dl>
          </div>

          <div className="card">
            <h3 className="mb-2">使用说明</h3>
            <p className="text-sm text-fg-muted">
              Persona 定义数字人的性格与语气，可在 Playground 顶部「人设」下拉切换；
              进行中的会话切换会重建会话。
            </p>
          </div>
        </div>

        {/* 右：提示词编辑 */}
        <div className="card lg:col-span-2">
          <h3 className="mb-3">系统提示词</h3>
          <PersonaEditor
            personaId={persona.id}
            initialLabel={persona.label || ""}
            initialPrompt={persona.prompt}
          />
        </div>
      </div>
    </div>
  );
}

function InfoRow({ label, value }: { label: string; value: React.ReactNode }) {
  return (
    <div className="flex justify-between items-center">
      <dt className="text-fg-muted">{label}</dt>
      <dd>{value}</dd>
    </div>
  );
}
