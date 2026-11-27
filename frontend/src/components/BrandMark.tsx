/** CHG-495 UIRD-003: R2 logo mark. Colours come from theme tokens, so it follows light and dark. */
export function BrandMark({ size = 22 }: { size?: number }) {
  const small = size < 48;
  return (
    <svg className="brand-logo" width={size} height={size} viewBox={small ? "0 0 48 52" : "0 0 48 48"} aria-hidden="true" focusable="false">
      {small ? (
        <>
          <polygon points="24,7 42,16 24,25 6,16" fill="var(--logo-c)" stroke="var(--logo-c)" strokeWidth="4" strokeLinejoin="round" />
          <polyline points="6,27 24,36 42,27" fill="none" stroke="var(--amber)" strokeWidth="6.5" strokeLinecap="round" strokeLinejoin="round" />
          <polyline points="6,37 24,46 42,37" fill="none" stroke="var(--logo-a)" strokeWidth="6.5" strokeLinecap="round" strokeLinejoin="round" />
        </>
      ) : (
        <>
          <polygon points="24,6 41,14.5 24,23 7,14.5" fill="var(--logo-c)" stroke="var(--logo-c)" strokeWidth="3.5" strokeLinejoin="round" />
          <polyline points="7,24 24,32.5 41,24" fill="none" stroke="var(--amber)" strokeWidth="5.5" strokeLinecap="round" strokeLinejoin="round" />
          <polyline points="7,33 24,41.5 41,33" fill="none" stroke="var(--logo-a)" strokeWidth="5.5" strokeLinecap="round" strokeLinejoin="round" />
        </>
      )}
    </svg>
  );
}
