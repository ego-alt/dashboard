// Icon ink colours — light enough to read on the dark chip.
const ACCENTS = [
  'text-rose-400', 'text-amber-400', 'text-emerald-400', 'text-sky-400',
  'text-violet-400', 'text-fuchsia-400', 'text-teal-400', 'text-indigo-400',
];

function hashSlug(slug) {
  let h = 0;
  for (const ch of slug) h = (h * 31 + ch.charCodeAt(0)) >>> 0;
  return h;
}

function accentFor(slug) {
  return ACCENTS[hashSlug(slug) % ACCENTS.length];
}

/** The built-in icon a service's `homehub.icon` label names (book, calendar, music), if any. */
function resolveIconKey(icon) {
  const key = icon?.trim().toLowerCase();
  return key && Object.hasOwn(ICONS, key) ? key : null;
}

function IconShell({ slug, textClass, accent, children }) {
  const text = accentFor(slug);
  return (
    <span
      className="flex h-10 w-10 shrink-0 items-center justify-center rounded-lg border"
      style={{ background: 'var(--color-bg-inset)', borderColor: 'var(--color-border)' }}
    >
      <span className={accent ? undefined : (textClass ?? text)} style={accent ? { color: accent } : undefined}>{children}</span>
    </span>
  );
}

const ICON_COLORS = {
  music: 'text-orange-400',
};

function BookIcon() {
  return (
    <svg viewBox="0 0 24 24" fill="none" className="h-5 w-5" aria-hidden>
      <path
        d="M4 19.5A2.5 2.5 0 0 1 6.5 17H20"
        stroke="currentColor"
        strokeWidth="1.75"
        strokeLinecap="round"
        strokeLinejoin="round"
      />
      <path
        d="M6.5 2H20v20H6.5A2.5 2.5 0 0 1 4 19.5v-15A2.5 2.5 0 0 1 6.5 2Z"
        stroke="currentColor"
        strokeWidth="1.75"
        strokeLinecap="round"
        strokeLinejoin="round"
      />
    </svg>
  );
}

function CalendarIcon() {
  return (
    <svg viewBox="0 0 24 24" fill="none" className="h-5 w-5" aria-hidden>
      <path
        d="M8 2v4M16 2v4M3 10h18M5 4h14a2 2 0 0 1 2 2v14a2 2 0 0 1-2 2H5a2 2 0 0 1-2-2V6a2 2 0 0 1 2-2Z"
        stroke="currentColor"
        strokeWidth="1.75"
        strokeLinecap="round"
        strokeLinejoin="round"
      />
    </svg>
  );
}

function MusicIcon() {
  return (
    <svg viewBox="0 0 24 24" fill="none" className="h-5 w-5" aria-hidden>
      <path
        d="M9 18V5l12-2v13"
        stroke="currentColor"
        strokeWidth="1.75"
        strokeLinecap="round"
        strokeLinejoin="round"
      />
      <circle cx="6" cy="18" r="3" stroke="currentColor" strokeWidth="1.75" />
      <circle cx="18" cy="16" r="3" stroke="currentColor" strokeWidth="1.75" />
    </svg>
  );
}

const ICONS = {
  book: BookIcon,
  calendar: CalendarIcon,
  music: MusicIcon,
};

function Monogram({ name, slug, accent }) {
  const letter = (name || '?').trim().charAt(0).toUpperCase() || '?';
  const text = accent ? '' : accentFor(slug);
  return (
    <IconShell slug={slug} accent={accent}>
      <span className={`text-sm font-semibold tracking-tight ${text}`}>{letter}</span>
    </IconShell>
  );
}

// An added app's own SVG, used as a mask so it takes the tile's ink colour.
function UrlIcon({ url }) {
  const mask = `url("${url}") center / contain no-repeat`;
  return <span className="block h-5 w-5 bg-current" style={{ mask, WebkitMask: mask }} aria-hidden />;
}

export default function ServiceIcon({ icon, iconUrl, accent, name, slug }) {
  if (iconUrl) {
    return (
      <IconShell slug={slug} accent={accent}>
        <UrlIcon url={iconUrl} />
      </IconShell>
    );
  }
  const key = resolveIconKey(icon);
  const Icon = key ? ICONS[key] : null;
  if (Icon) {
    return (
      <IconShell slug={slug} textClass={ICON_COLORS[key]} accent={accent}>
        <Icon />
      </IconShell>
    );
  }
  return <Monogram name={name} slug={slug} accent={accent} />;
}
