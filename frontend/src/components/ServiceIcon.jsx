const ACCENTS = [
  { text: 'text-rose-600', ring: 'ring-rose-200/80' },
  { text: 'text-amber-600', ring: 'ring-amber-200/80' },
  { text: 'text-emerald-600', ring: 'ring-emerald-200/80' },
  { text: 'text-sky-600', ring: 'ring-sky-200/80' },
  { text: 'text-violet-600', ring: 'ring-violet-200/80' },
  { text: 'text-fuchsia-600', ring: 'ring-fuchsia-200/80' },
  { text: 'text-teal-600', ring: 'ring-teal-200/80' },
  { text: 'text-indigo-600', ring: 'ring-indigo-200/80' },
];

const ICON_ALIASES = {
  '📚': 'book',
  '📅': 'calendar',
  '🎵': 'music',
  library: 'book',
  book: 'book',
  calendar: 'calendar',
  music: 'music',
  tapes: 'music',
};

const SLUG_ICONS = {
  library: 'book',
  calendar: 'calendar',
  music: 'music',
};

function hashSlug(slug) {
  let h = 0;
  for (const ch of slug) h = (h * 31 + ch.charCodeAt(0)) >>> 0;
  return h;
}

function accentFor(slug) {
  return ACCENTS[hashSlug(slug) % ACCENTS.length];
}

function resolveIconKey(icon, slug) {
  if (icon) {
    const trimmed = icon.trim();
    const key = ICON_ALIASES[trimmed] ?? ICON_ALIASES[trimmed.toLowerCase()];
    if (key) return key;
  }
  return SLUG_ICONS[slug] || null;
}

function IconShell({ slug, textClass, children }) {
  const { text, ring } = accentFor(slug);
  return (
    <span
      className={`flex h-10 w-10 shrink-0 items-center justify-center rounded-lg border border-slate-200/90 bg-slate-50 ring-1 ring-inset ${ring}`}
    >
      <span className={textClass ?? text}>{children}</span>
    </span>
  );
}

const ICON_COLORS = {
  music: 'text-orange-500',
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

function Monogram({ name, slug }) {
  const letter = (name || '?').trim().charAt(0).toUpperCase() || '?';
  const { text } = accentFor(slug);
  return (
    <IconShell slug={slug}>
      <span className={`text-sm font-semibold tracking-tight ${text}`}>{letter}</span>
    </IconShell>
  );
}

export default function ServiceIcon({ icon, name, slug }) {
  const key = resolveIconKey(icon, slug);
  const Icon = key ? ICONS[key] : null;
  if (Icon) {
    return (
      <IconShell slug={slug} textClass={ICON_COLORS[key]}>
        <Icon />
      </IconShell>
    );
  }
  return <Monogram name={name} slug={slug} />;
}
