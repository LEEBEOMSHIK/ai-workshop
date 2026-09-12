import { ragStationArt } from "./rag-station-art";
import styles from "./PublicLabScene.module.css";

export function RagWorkbench({ slug }: { slug: string }) {
  const art = ragStationArt(slug);
  return <svg viewBox="0 0 320 184" className={styles.benchArt} aria-hidden="true" shapeRendering="crispEdges">
    <path fill="#233e3820" d="M30 142h257v23H30zM40 165h257v7H40z" />
    <path fill="#514c3c" d="M38 116h12v43H38zm223 0h12v43h-12z" />
    <path fill="#a78259" d="M26 89h256v49H26z" />
    <path fill="#d0ad7a" d="M26 79h256v30H26z" />
    <path fill="#f0d2a0" d="M26 79h256v5H26z" />
    <path stroke="#b98d60" strokeWidth="1" d="M32 92h242M33 99h161M226 100h45" />
    <path fill="#8c6f50" d="M26 109h256v6H26z" />
    <path fill="#c19c6b" d="M42 118h64v15H42z" />
    <path fill="#685742" d="M65 122h16v3H65z" />
    <path fill="#f1dec0" d="M236 72h13v17h-13zm13 3h5v9h-5z" />
    <path fill="#735445" d="M239 73h7v3h-7z" />
    {art.equipment === "scanner" ? <g>
      <path fill="#405c5e" d="M46 41h89v40H46z" /><path fill="#8dada3" d="M41 45h98v23H41z" />
      <path fill="#c4d0b9" d="M47 31h78v19H47z" /><path fill="#f4e9cc" d="M61 13h54v32H61zM67 68h55v25H67z" />
      <path stroke="#8aa794" strokeWidth="3" d="M70 23h35m-35 7h28m-21 47h34m-34 6h27" />
      <path fill={art.accent} d="M48 55h77v3H48z" />
      <path fill="#e4cb93" d="M163 64h37v20h-37zM168 58h37v20h-37z" />
    </g> : art.equipment === "index" ? <g>
      <path fill="#284852" d="M51 13h66v72H51z" /><path fill="#78969a" d="M53 15h62v4H53z" />
      {[0,1,2].map((i)=><g key={i}><path fill="#173a48" d={`M57 ${24+i*18}h54v14H57z`} /><path fill="#6a8790" d={`M61 ${27+i*18}h29v2H61z`} /><rect fill="#97c8a5" x="99" y={28+i*18} width="5" height="4" /></g>)}
      <path fill="#d0bb8c" d="M132 54h44v33h-44z" /><path fill="#edddbb" d="M137 58h34v4h-34z" /><path stroke="#876c4c" strokeWidth="2" d="M140 70h28m-28 7h22" />
    </g> : <g>
      <path fill="#3f5f60" d="M85 61h12v21H85zM68 80h45v5H68z" />
      <path fill="#203e49" d="M39 11h109v56H39z" /><path fill="#6c9290" d="M42 14h103v3H42z" />
      <path fill="#335c67" d="M45 21h97v39H45z" />
      {art.equipment === "segments" ? <g fill={art.accent}><path d="M53 28h32v7H53zm38 0h39v7H91zm-38 13h47v7H53zm53 0h24v7h-24z" /></g>
      : art.equipment === "source" ? <g><path fill="#ece3c4" d="M71 24h46v33H71z" /><path stroke="#97a58e" strokeWidth="2" d="M76 30h31m-31 7h28m-28 7h32m-32 7h24" /><path fill={art.accent} d="M76 40h31v6H76z" /></g>
      : art.equipment === "evaluation" ? <g fill={art.accent}><path d="M55 43h12v12H55zm20-8h12v20H75zm20-9h12v29H95zm20 9h12v20h-12z" /></g>
      : <g><path fill="#79b6aa" d="M53 29h28v4H53zm0 9h24v4H53zm0 9h33v4H53z" /><path fill="#d3bc83" d="M99 29h32v4H99zm0 9h21v4H99zm0 9h28v4H99z" /></g>}
      <path fill="#c4d0b5" d="M59 90h74v8H59z" /><path stroke="#6f8981" strokeWidth="1" d="M64 92h64m-60 0v4m6-4v4m6-4v4m6-4v4m6-4v4m6-4v4m6-4v4m6-4v4m6-4v4" />
      <path fill="#ede0be" d="M163 65h31v25h-31zM168 61h31v25h-31z" /><path stroke={art.accent} strokeWidth="3" d="M173 67h20m-20 7h16m-16 7h20" />
    </g>}
    <path fill="#385b47" d="M256 39h4v28h-4zM244 37h13v10h-13zM260 29h15v12h-15z" /><path fill="#7ba169" d="M245 35h11v5h-11zm17-8h12v5h-12z" /><path fill="#bd9462" d="M249 59h21l-3 18h-15z" />
    <path fill={art.accent} d="M137 116h115v17H137z" />
    <text x="143" y="128" fontFamily="monospace" fontSize="8" fill="#193d41">{art.label}</text>
  </svg>;
}
