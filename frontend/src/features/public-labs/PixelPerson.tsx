import { humanPixels, type HumanIdentity } from "./human-art";
import styles from "./PublicLabScene.module.css";

export function PixelPerson({ identity }: { identity: HumanIdentity }) {
  return <svg className={styles.pixelPerson} viewBox="0 0 48 64" aria-hidden="true" shapeRendering="crispEdges">
    {humanPixels(identity).map(([fill, x, y, width, height], index) => <rect key={index} {...{fill, x, y, width, height}} />)}
  </svg>;
}
