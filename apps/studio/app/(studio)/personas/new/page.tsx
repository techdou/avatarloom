import Link from "next/link";
import { CreatePersonaForm } from "@/components/persona/create-form";

export default function NewPersonaPage() {
  return (
    <div>
      <div className="flex items-center gap-3 mb-6 text-sm">
        <Link href="/personas" className="text-fg-muted hover:text-fg dark:text-fg-muted dark:hover:text-fg">
          ← Personas
        </Link>
        <span className="text-fg-subtle">/</span>
        <span className="font-medium">新建</span>
      </div>

      <div className="max-w-lg">
        <div className="card">
          <p className="text-sm text-fg-muted mb-4 dark:text-fg-muted">
            创建一个数字人人设。Persona 与 Avatar 解耦——定义性格与提示词，
            之后可关联到任意 Avatar 形象。
          </p>
          <CreatePersonaForm />
        </div>
      </div>
    </div>
  );
}
