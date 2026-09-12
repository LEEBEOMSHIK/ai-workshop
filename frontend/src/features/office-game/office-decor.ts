import type Phaser from "phaser";
import type { PlacedDecoration } from "./map";
import { OFFICE } from "./config";

/** Separate furnishings, authored at native pixel size; no flattened room background. */
export function createOfficeDecoration(scene: Phaser.Scene, item: PlacedDecoration) {
  const key = `office-decor-${item.id}`;
  const w = item.width, h = item.height;
  const texture = scene.textures.createCanvas(key, w + 12, h + 12);
  if (!texture) throw new Error("Cannot create office furnishing");
  const c = texture.context;
  const r = (color: string, x: number, y: number, width: number, height: number) => { c.fillStyle = color; c.fillRect(Math.round(x), Math.round(y), Math.round(width), Math.round(height)); };
  const line = (color: string, x: number, y: number, x2: number, y2: number, width = 2) => { c.strokeStyle = color; c.lineWidth = width; c.beginPath(); c.moveTo(x,y); c.lineTo(x2,y2); c.stroke(); };
  const text = (label: string, x: number, y: number, size = 12, color = "#f4e4bc") => { c.fillStyle = color; c.font = `bold ${size}px sans-serif`; c.fillText(label,x,y); };
  const shadow = () => { r("#21342b25",8,h-13,w,20); r("#21342b13",12,h-8,w,20); };
  const desk = () => {
    shadow(); r("#4d4135",8,h-25,10,25); r("#4d4135",w-18,h-25,10,25);
    r("#795e43",0,h*.32,w,h*.5); r("#b68b5f",0,8,w,h*.48);
    r("#e4bd83",0,5,w,7); r("#936c49",0,h*.54,w,5);
    for (let y=18;y<h*.5;y+=12) { line("#c99d6c",6,y,w-7,y,1); line("#a87a50",w*.65,y+3,w*.8,y+3,1); }
    r("#564836",w*.08,h*.7,w*.24,3); r("#e4c38b",w*.15,h*.65,12,3);
    r("#a78054",w*.52,h*.64,w*.4,3);
  };
  const monitor = (x:number,y:number,mw:number,mh:number) => {
    r("#263d43",x+mw*.43,y+mh,mw*.15,10); r("#425958",x+mw*.24,y+mh+9,mw*.55,4);
    r("#182e38",x,y,mw,mh); r("#678482",x+2,y+2,mw-4,3);
    r("#2c5965",x+5,y+6,mw-10,mh-12); r("#619b9b",x+7,y+8,mw-14,3);
    for(let i=0;i<3;i++){r(i===1?"#d7b982":"#8ac2b3",x+10,y+16+i*7,(mw-23)*[.85,.5,.7][i],2);}
    r("#a4d6b7",x+mw-9,y+mh-5,3,2);
  };
  switch(item.kind) {
    case "rug":
      r("#6f706324",6,6,w,h); r("#a88c67",0,0,w,h); r("#d8c6a1",3,3,w-6,h-6);
      r("#647b72",10,10,w-20,h-20); r("#839487",15,15,w-30,h-30);
      for(let y=22;y<h-20;y+=7) r("#c5c1a124",20,y,w-40,1);
      for(let x=25;x<w-20;x+=22){ r("#ddd3ab",x,6,8,2); r("#ddd3ab",x,h-8,8,2); }
      break;
    case "wall-panel":
      r("#1c343d",0,0,w,h); r("#3e5b61",0,0,w,8); r("#aac0af",0,0,w,3);
      if(w>h) {
        r("#e6d6b5",0,8,w,h-25); r("#b7ab90",0,h-22,w,4);
        r("#456364",0,h-18,w,14); r("#233f43",0,h-4,w,4);
        for(let x=24;x<w-10;x+=64) { r("#cbbb9b",x,13,2,h-37); r("#f2e5c9",x+2,13,1,h-37); }
      } else { r("#4b6769",3,8,w-9,h-8); r("#769086",3,8,3,h-8); r("#1a3136",w-6,8,6,h-8); }
      break;
    case "door-frame":
      r("#e7d4b0",0,0,6,h); r("#e7d4b0",w-6,0,6,h);
      r("#8c7252",6,7,3,h-7); r("#8c7252",w-9,7,3,h-7);
      r("#3f665f",10,h-5,w-20,5); r("#bcad89",11,h-3,w-22,2);
      break;
    case "window":
      r("#746451",3,3,w,h); r("#ece2c4",0,0,w-3,h-3);
      r("#759da0",7,7,w-17,h-19); r("#acd2c4",9,9,w-21,h*.36);
      for(let x=18;x<w-12;x+=30) r("#d1e4ca66",x,12,8,h-28);
      r("#395e65",9,h-34,w-21,14);
      for(let x=15;x<w-12;x+=25) {r("#547978",x,h-51,15,31);r("#abc6aa",x+4,h-45,3,3);}
      r("#f1e4c5",w/2-3,5,6,h-13); r("#d6c39e",3,h-12,w-3,9);
      break;
    case "executive-desk": case "reception": case "workbench": case "coffee-table":
      desk();
      if(item.kind==="reception") { r("#294d50",w*.35,h*.55,w*.3,24);text("WELCOME",w*.37,h*.55+16,10);r("#ecdec0",w-48,16,30,20);line("#997852",w-44,22,w-26,22); }
      else if(item.kind!=="coffee-table") { monitor(w*.17,-1,w*.35,h*.45);r("#e9dfc3",w*.62,18,w*.2,22);line("#9caa97",w*.65,24,w*.78,24);line("#9caa97",w*.65,29,w*.75,29);r("#34574f",w*.62,45,20,3); }
      else {r("#efe0b9",w*.3,18,32,22);r("#447c6d",w*.3+3,21,26,16);}
      r("#ecddbd",w-26,18,11,13); r("#6e4c38",w-24,20,7,3); r("#ecddbd",w-16,22,5,5);
      break;
    case "sofa":
      shadow(); r("#304948",3,h-24,w-6,20);r("#203b3d",10,h-5,10,5);r("#203b3d",w-20,h-5,10,5);
      r("#537c73",3,10,w-6,h-30);r("#789c88",5,8,w-10,8);
      for(let x=14;x<w-14;x+=(w-28)/3){r("#729687",x,21,(w-35)/3,27);r("#4b7169",x,49,(w-35)/3,7);r("#93aa90",x+3,23,(w-50)/3,2);}
      r("#41675f",0,23,14,h-31);r("#41675f",w-14,23,14,h-31);r("#aabb94",2,23,10,5);r("#aabb94",w-12,23,10,5);
      r("#d6b777",w*.68,22,25,22);r("#ead3a0",w*.68+3,24,18,3);
      break;
    case "bookcase":
      shadow();r("#765236",0,0,w,h);r("#bb9060",0,0,w,7);r("#4d4130",7,9,w-14,h-18);
      for(let y=32;y<h;y+=48){for(let x=12;x<w-14;x+=12){const colors=["#b4b894","#547c78","#c08459","#d8bd83"];r(colors[(x+y)%4],x,y-15,8,27);r("#ead8a1",x+1,y-10,6,2);}r("#b28a5b",5,y+14,w-10,6);r("#d3ab77",5,y+14,w-10,2);}
      r("#ab8054",0,6,7,h-6);r("#ab8054",w-7,6,7,h-6);
      break;
    case "recruitment-board":
      shadow();r("#4c655b",12,h-22,6,22);r("#4c655b",w-18,h-22,6,22);
      r("#806747",0,0,w,h-18);r("#eadbbc",5,5,w-10,h-28);
      r("#375e5b",10,10,w-20,30);text("관리자 모집 중",22,31,18,"#fff4d8");
      text("기능 준비 중",41,65,16,"#315954");
      text("클릭 / 가까이에서 E",22,83,12,"#59695b");
      break;
    case "knowledge-board":
      shadow();r("#806747",0,0,w,h-18);r("#e9e7cc",6,6,w-12,h-30);
      text("KNOWLEDGE GRAPH",14,25,12,"#315954");
      for(const [x,y,x2,y2] of [[62,57,180,75],[180,75,300,48],[180,75,310,96],[62,57,64,98]])line("#708d84",x,y,x2,y2,3);
      for(const [x,y,label] of [[62,57,"개념"],[180,75,"관계"],[300,48,"지식"],[310,96,"구조"],[64,98,"맥락"]] as const){r("#466e67",x-24,y-11,48,23);text(label,x-13,y+5,12,"#f2e7cc");}
      r("#4c655b",12,h-20,6,20);r("#4c655b",w-18,h-20,6,20);
      break;
    case "study-board": case "direction-board": case "whiteboard":
      shadow();r("#4c655b",10,h-22,5,22);r("#4c655b",w-15,h-22,5,22);
      r("#806747",0,0,w,h-17);r("#d5c297",3,3,w-6,h-23);
      r("#e9e7cc",7,7,w-14,h-31);text(item.kind==="study-board"?"STUDY NOTES":item.kind==="direction-board"?"RESEARCH NOTES":"EVIDENCE FLOW",12,24,10,"#315954");
      for(let i=0;i<3;i++){r(["#dba776","#a3b7a0","#e2cf8c"][i],13,34+i*16,18,11);line("#647970",38,38+i*16,w-18,38+i*16);line("#9aa894",38,43+i*16,w-32,43+i*16,1);}
      break;
    case "monitor-bank": monitor(0,0,w,h-15);break;
    case "server-rack":
      shadow();r("#1e3740",0,0,w,h);r("#557677",2,2,w-4,5);r("#304f58",5,12,w-10,h-21);
      for(let y=18;y<h-20;y+=27){r("#17323b",10,y,w-20,21);r("#6c8b88",12,y+2,w-24,2);r("#8acaaa",w-21,y+8,4,4);r("#d9bd78",w-29,y+8,4,4);for(let x=15;x<w-35;x+=5)r("#4d6d72",x,y+8,2,7);}
      break;
    case "plant":
      shadow();r("#876445",w*.24,h*.64,w*.53,h*.29);r("#c19a65",w*.2,h*.6,w*.61,8);r("#d0af77",w*.25,h*.68,5,h*.2);
      line("#4e6b42",w*.5,h*.67,w*.47,h*.16,4);
      for(const [x,y,s] of [[.13,.32,.3],[.44,.1,.32],[.47,.35,.39],[.06,.12,.31],[.59,.22,.3]]) {
        r("#3e6f50",w*x,h*y,w*s,h*.19);r("#648e5b",w*x+3,h*y+2,w*s-4,5);r("#8daf69",w*x+4,h*y+2,5,3);
      }
      break;
    case "directory":
      r("#244748",0,0,w,h);r("#a7bba0",2,2,w-4,2);text("01  FOUNDER     02  RAG",12,22,11);
      break;
    default: throw new Error(`Unknown office decoration: ${item.kind}`);
  }
  texture.refresh();
  const floorArt = item.kind === "rug" || item.kind === "directory" || item.kind === "door-frame";
  return scene.add.image(item.x,item.y,key).setOrigin(0).setDepth(floorArt ? OFFICE.depth.floor+2 : item.y+item.height);
}
