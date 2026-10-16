/**
 * The one card recipe for Monitor, Users and Settings: 16px padding, a title
 * trimmed to its letters (so the space above it matches the space below the
 * content), an optional description and right-hand aside, then the content.
 * `flush` puts the header in a ruled bar and lets the body run edge to edge,
 * for tables. Services tiles have their own design and don't use this.
 */
export default function Panel({
  title,
  description,
  aside,
  flush = false,
  as = 'section',
  className = '',
  children,
  ...rest
}) {
  const Tag = as;
  return (
    <Tag className={`bp-card bp-panel ${flush ? 'bp-panel-flush' : ''} ${className}`} {...rest}>
      {(title || aside) && (
        <div className="bp-panel-head">
          <div className="bp-panel-row">
            {title && <h3 className="bp-panel-title">{title}</h3>}
            {aside && <div className="bp-panel-aside">{aside}</div>}
          </div>
          {/* Full width under the title row, even when there's an aside. */}
          {description && <p className="bp-panel-desc">{description}</p>}
        </div>
      )}
      {children}
    </Tag>
  );
}
