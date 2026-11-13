import { BookOpen, FileText, Folder } from "lucide-react";

export default function LoginKnowledgeIllustration() {
  return <svg className="login-knowledge-illustration" viewBox="0 0 500 370" fill="none" aria-hidden="true" focusable="false">
    <defs>
      <filter id="login-paper-shadow" x="-40%" y="-30%" width="180%" height="180%"><feDropShadow dx="0" dy="10" stdDeviation="12" floodColor="#2F7D57" floodOpacity=".08" /></filter>
    </defs>
    <path d="M30 226C-8 171 54 117 113 137C174 157 178 92 245 128C319 168 367 74 424 113C488 156 443 204 467 250C490 296 387 335 308 310C225 283 81 337 30 226Z" fill="#DCEFE5" fillOpacity=".7" />
    <path d="M64 92C102 66 145 125 171 116C216 102 264 76 291 102C330 140 401 78 450 99" stroke="#D9EEE3" strokeWidth="32" strokeLinecap="round" opacity=".55" />
    <g stroke="#9DCEB7" strokeWidth="1.6" strokeLinecap="round">
      <path d="M250 75C281 108 226 111 250 155M138 69C171 73 186 93 190 130M365 112C367 142 341 150 325 157M163 239C109 247 92 269 77 303M333 245C367 260 374 296 413 302" />
    </g>
    <g filter="url(#login-paper-shadow)">
      <g transform="rotate(-8 124 221)">
        <rect x="69" y="146" width="120" height="169" rx="7" fill="#F9FDFB" />
        <rect x="87" y="168" width="38" height="7" rx="2" fill="#BFDCCE" />
        <path d="M87 190H164M87 205H159M87 220H164M87 235H151M87 250H158M87 265H144" stroke="#D5E9DF" strokeWidth="4" strokeLinecap="round" />
      </g>
      <g transform="rotate(8 376 224)">
        <rect x="317" y="148" width="117" height="165" rx="7" fill="#F9FDFB" />
        <rect x="337" y="172" width="36" height="7" rx="2" fill="#BFDCCE" />
        <path d="M337 194H411M337 209H407M337 224H411M337 239H398M337 254H405M337 269H392" stroke="#D5E9DF" strokeWidth="4" strokeLinecap="round" />
      </g>
      <rect x="164" y="120" width="174" height="207" rx="9" fill="#FCFDFB" />
      <rect x="190" y="150" width="81" height="10" rx="3" fill="#90C5AD" />
      <path d="M190 178H309M190 194H303M190 210H310M250 233H308M250 248H300M250 263H308M250 278H291M190 303H302" stroke="#D3E8DD" strokeWidth="5" strokeLinecap="round" />
      <rect x="190" y="231" width="42" height="49" rx="4" fill="#C9E3D6" />
    </g>
    <g fill="#CBE7D9"><circle cx="250" cy="53" r="34" /><circle cx="64" cy="319" r="32" /><circle cx="429" cy="317" r="33" /></g>
    <g color="#2F7D57"><BookOpen x={235} y={38} width={30} height={30} strokeWidth={1.8} /><FileText x={51} y={305} width={27} height={29} strokeWidth={1.8} /><Folder x={414} y={302} width={31} height={29} strokeWidth={1.8} /></g>
    <g fill="#78B99A"><circle cx="138" cy="69" r="6" /><circle cx="365" cy="112" r="6" /><circle cx="171" cy="346" r="7" /></g>
  </svg>;
}
