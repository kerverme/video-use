import type { SVGProps } from "react";

type P = SVGProps<SVGSVGElement> & { size?: number };

function Svg({ size = 16, children, ...rest }: P & { children: React.ReactNode }) {
  return (
    <svg width={size} height={size} viewBox="0 0 16 16" fill="none" stroke="currentColor" strokeWidth={1.3}
      strokeLinecap="round" strokeLinejoin="round" aria-hidden="true" className="icon" {...rest}>
      {children}
    </svg>
  );
}

export const IconPlus = (p: P) => <Svg {...p}><path d="M8 3v10M3 8h10" /></Svg>;
export const IconFolder = (p: P) => <Svg {...p}><path d="M2 4.5A1.5 1.5 0 0 1 3.5 3h2.6l1.4 1.5h5A1.5 1.5 0 0 1 14 6v5.5a1.5 1.5 0 0 1-1.5 1.5h-9A1.5 1.5 0 0 1 2 11.5v-7Z" /></Svg>;
export const IconFilm = (p: P) => <Svg {...p}><rect x="2" y="3" width="12" height="10" rx="1.5" /><path d="M5 3v10M11 3v10M2 6h3M2 10h3M11 6h3M11 10h3" /></Svg>;
export const IconSettings = (p: P) => <Svg {...p}><circle cx="8" cy="8" r="2" /><path d="M8 1.8v1.6M8 12.6v1.6M14.2 8h-1.6M3.4 8H1.8M12.4 3.6l-1.1 1.1M4.7 11.3l-1.1 1.1M12.4 12.4l-1.1-1.1M4.7 4.7 3.6 3.6" /></Svg>;
export const IconUpload = (p: P) => <Svg {...p}><path d="M8 10.5V2.5M5 5.5l3-3 3 3M2.5 10.5v1.5A1.5 1.5 0 0 0 4 13.5h8a1.5 1.5 0 0 0 1.5-1.5v-1.5" /></Svg>;
export const IconGrip = (p: P) => <Svg {...p} strokeWidth={0}><g fill="currentColor"><circle cx="6" cy="4" r="1" /><circle cx="10" cy="4" r="1" /><circle cx="6" cy="8" r="1" /><circle cx="10" cy="8" r="1" /><circle cx="6" cy="12" r="1" /><circle cx="10" cy="12" r="1" /></g></Svg>;
export const IconTrash = (p: P) => <Svg {...p}><path d="M3 4.5h10M6.5 4.5V3h3v1.5M4.5 4.5l.6 8.1a1 1 0 0 0 1 .9h3.8a1 1 0 0 0 1-.9l.6-8.1" /></Svg>;
export const IconUp = (p: P) => <Svg {...p}><path d="M4 10l4-4 4 4" /></Svg>;
export const IconDown = (p: P) => <Svg {...p}><path d="M4 6l4 4 4-4" /></Svg>;
export const IconChevron = (p: P) => <Svg {...p}><path d="M6 4l4 4-4 4" /></Svg>;
export const IconCheck = (p: P) => <Svg {...p}><path d="M3.5 8.5l3 3 6-7" /></Svg>;
export const IconX = (p: P) => <Svg {...p}><path d="M4 4l8 8M12 4l-8 8" /></Svg>;
export const IconAlert = (p: P) => <Svg {...p}><path d="M8 2.5 14 13H2L8 2.5Z" /><path d="M8 6.5v3M8 11.3v.2" /></Svg>;
export const IconSparkle = (p: P) => <Svg {...p}><path d="M8 2v3M8 11v3M2 8h3M11 8h3M4 4l1.8 1.8M10.2 10.2 12 12M12 4l-1.8 1.8M5.8 10.2 4 12" /></Svg>;
export const IconPlay = (p: P) => <Svg {...p}><path d="M5 3.5v9l7-4.5-7-4.5Z" /></Svg>;
export const IconDownload = (p: P) => <Svg {...p}><path d="M8 2.5v8M5 7.5l3 3 3-3M2.5 11v1A1.5 1.5 0 0 0 4 13.5h8a1.5 1.5 0 0 0 1.5-1.5v-1" /></Svg>;
export const IconExternal = (p: P) => <Svg {...p}><path d="M9 3h4v4M13 3 7.5 8.5M11 9.5V12a1 1 0 0 1-1 1H4a1 1 0 0 1-1-1V6a1 1 0 0 1 1-1h2.5" /></Svg>;
export const IconLayers = (p: P) => <Svg {...p}><path d="M8 2 14 5 8 8 2 5 8 2Z" /><path d="M2 8l6 3 6-3M2 11l6 3 6-3" /></Svg>;
export const IconLock = (p: P) => <Svg {...p}><rect x="3" y="7" width="10" height="7" rx="1.5" /><path d="M5.5 7V5a2.5 2.5 0 0 1 5 0v2" /></Svg>;
export const IconEdit = (p: P) => <Svg {...p}><path d="M10.5 3 13 5.5 6 12.5H3.5V10L10.5 3Z" /></Svg>;
export const IconClock = (p: P) => <Svg {...p}><circle cx="8" cy="8" r="5.5" /><path d="M8 5v3l2 1.5" /></Svg>;
export const IconRender = (p: P) => <Svg {...p}><circle cx="8" cy="8" r="5.5" /><path d="M6.5 5.8v4.4L10.2 8 6.5 5.8Z" /></Svg>;
