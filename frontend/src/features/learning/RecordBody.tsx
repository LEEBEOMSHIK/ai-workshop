import styles from "./Learning.module.css";

export function RecordBody({ body }: { body: string }) {
  return <div className={styles.recordBody}>{body}</div>;
}
