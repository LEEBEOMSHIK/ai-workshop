import Link from "next/link";
import { routes } from "../../../../shared/routing/routes";
import styles from "../../../../features/flowcharts/Flowcharts.module.css";

export default function FlowNotFound() {
  return <main className={styles.shell}><h1>흐름도를 찾을 수 없습니다</h1><p>분류와 흐름 주소를 확인해 주세요.</p><Link href={routes.workshopFlows}>흐름도 목록으로</Link></main>;
}
