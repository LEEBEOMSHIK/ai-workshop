import type { ComponentPropsWithRef, ReactNode } from "react";
import styles from "./Feedback.module.css";

export type FeedbackTone = "neutral" | "info" | "success" | "warning" | "danger";

export function StatusBadge({ tone = "neutral", className = "", ...props }:
  ComponentPropsWithRef<"span"> & { tone?: FeedbackTone }) {
  return <span {...props} className={`${styles.badge} ${styles[tone]} ${className}`} />;
}

export function Notice({ tone = "info", className = "", ...props }:
  ComponentPropsWithRef<"div"> & { tone?: FeedbackTone }) {
  return <div {...props} className={`${styles.notice} ${styles[tone]} ${className}`} />;
}

type EmptyStateProps = Omit<ComponentPropsWithRef<"div">, "title"> & { title: ReactNode; description?: ReactNode };

export function EmptyState({ title, description, children, className = "", ...props }: EmptyStateProps) {
  return <div {...props} className={`${styles.empty} ${className}`}>
    <strong>{title}</strong>
    {description && <p>{description}</p>}
    {children}
  </div>;
}

export function Disclosure({ summary, children, className = "", ...props }:
  ComponentPropsWithRef<"details"> & { summary: ReactNode }) {
  return <details {...props} className={`${styles.disclosure} ${className}`}>
    <summary>{summary}</summary>
    <div className={styles.disclosureBody}>{children}</div>
  </details>;
}
