import { createStore } from "zustand/vanilla";
import { npcCatalog } from "./npcs";
import { preparingRooms, type PreparingRoomId } from "./preparingRooms";
import type { Position } from "./spatial";
export interface GameState {
  currentRoom: string; selectedNPC: string | null; nearbyNPC: string | null;
  selectedNotice: PreparingRoomId | null; nearbyNotice: PreparingRoomId | null;
  selectNotice: (id: string) => void; setNearbyNotice: (id: string | null) => void;
  interactionAvailable: boolean; dialogueOpen: boolean; researchPanelOpen: boolean;
  playerPosition: Position; status: "loading" | "ready" | "error";
  setNearbyNpc: (id: string | null) => void;
  openDialogue: () => void; closeDialogue: () => void;
  selectNpc: (id: string) => void;
  updateWorld: (position: Position, room: string) => void;
  setStatus: (status: GameState["status"]) => void;
}
export function createGameStore() {
  return createStore<GameState>()((set, get) => ({
    currentRoom: "lobby", selectedNPC: null, nearbyNPC: null, interactionAvailable: false,
    selectedNotice: null, nearbyNotice: null,
    dialogueOpen: false, researchPanelOpen: false, playerPosition: { x: 0, y: 0 }, status: "loading",
    setNearbyNpc: (id) => {
      const nearbyNPC = npcCatalog.some((npc) => npc.id === id) ? id : null;
      if (get().nearbyNPC !== nearbyNPC) set({ nearbyNPC, interactionAvailable: nearbyNPC !== null || get().nearbyNotice !== null });
    },
    setNearbyNotice: (id) => {
      const nearbyNotice = preparingRooms.find((room) => room.id === id)?.id ?? null;
      if (get().nearbyNotice !== nearbyNotice) set({ nearbyNotice, interactionAvailable: nearbyNotice !== null || get().nearbyNPC !== null });
    },
    selectNotice: (id) => {
      const notice = preparingRooms.find((room) => room.id === id);
      if (get().status !== "ready" || get().dialogueOpen || !notice) return;
      set({ selectedNotice: notice.id, selectedNPC: null, dialogueOpen: true });
    },
    openDialogue: () => {
      const id = get().nearbyNPC;
      if (id) get().selectNpc(id);
      else if (get().nearbyNotice) get().selectNotice(get().nearbyNotice!);
    },
    selectNpc: (id) => {
      if (get().status !== "ready" || get().dialogueOpen || !npcCatalog.some((npc) => npc.id === id)) return;
      set({ selectedNPC: id, selectedNotice: null, dialogueOpen: true });
    },
    closeDialogue: () => set({ dialogueOpen: false, selectedNPC: null, selectedNotice: null }),
    updateWorld: (playerPosition, currentRoom) => set({ playerPosition, currentRoom }),
    setStatus: (status) => set({ status }),
  }));
}
export type GameStore = ReturnType<typeof createGameStore>;
