import type { ModelApiErrorInfo } from "@/lib/model-api";

/**
 * One failure presentation for every model-API dependency on the site: what failed, what the
 * API said, and its machine-readable code. The code is shown because these messages end up in
 * bug reports, and a code turns "it didn't work" into something searchable.
 */
export function ErrorNotice({ title, error }: { title: string; error: ModelApiErrorInfo }) {
  return (
    <div className="notice notice-error" role="alert">
      <strong>{title}</strong>
      <span>{error.message}</span>
      <code>{error.code}</code>
    </div>
  );
}
