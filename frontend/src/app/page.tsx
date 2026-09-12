import { GameClient } from "../features/office-game/GameClient";

export const metadata = {
  alternates: { canonical: "/" },
};

export default function HomeRoute() {
  return <GameClient />;
}
