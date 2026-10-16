/**
 * The one page heading: a fixed-height row (title left, optional controls
 * right), an optional line under it, then 16px to the first card. Every page
 * uses it, so the space between heading and content is the same everywhere.
 */
export default function PageHeader({ title, aside, children }) {
  return (
    <div className="mb-4">
      <div className="flex h-9 items-center gap-3">
        <h2 className="text-lg font-semibold text-[var(--color-text-primary)]">{title}</h2>
        {aside && <div className="ml-auto flex items-center gap-3">{aside}</div>}
      </div>
      {children}
    </div>
  );
}
