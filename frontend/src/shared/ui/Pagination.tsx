import { Button } from "./Button";
import styles from "./Pagination.module.css";

type PaginationProps = {
  label: string;
  position: string;
  canGoBack: boolean;
  canGoForward: boolean;
  onPrevious: () => void;
  onNext: () => void;
};

export function PageArrow({ direction }: { direction: "first" | "previous" | "next" }) {
  return <svg aria-hidden="true" width="18" height="18" viewBox="0 0 24 24"
    fill="none" stroke="currentColor" strokeWidth="1.8" strokeLinecap="round" strokeLinejoin="round">
    {direction === "first" && <path d="M5 5v14" />}
    <path d={direction === "next" ? "m9 5 7 7-7 7" : "m15 5-7 7 7 7"} />
  </svg>;
}

export function Pagination({ label, position, canGoBack, canGoForward, onPrevious, onNext }: PaginationProps) {
  return (
    <nav aria-label={label} className={styles.pager}>
      <Button variant="quiet" className={styles.iconButton} aria-label="이전 페이지" title="이전 페이지" disabled={!canGoBack} onClick={onPrevious}>
        <PageArrow direction="previous" />
      </Button>
      <span>{position}</span>
      <Button variant="quiet" className={styles.iconButton} aria-label="다음 페이지" title="다음 페이지" disabled={!canGoForward} onClick={onNext}>
        <PageArrow direction="next" />
      </Button>
    </nav>
  );
}
