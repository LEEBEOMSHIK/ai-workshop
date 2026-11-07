import type { ComponentPropsWithRef, ReactNode } from "react";
import styles from "./CheckboxField.module.css";

export type CheckboxFieldProps = Omit<ComponentPropsWithRef<"input">, "type" | "children"> & { label: ReactNode };

export function CheckboxField({ label, className = "", ...props }: CheckboxFieldProps) {
  return <label className={`${styles.choice} ${className}`}>
    <input {...props} type="checkbox" className={styles.input} />
    <svg className={styles.check} aria-hidden="true" viewBox="0 0 20 20" fill="none" stroke="currentColor" strokeWidth="2.4" strokeLinecap="round" strokeLinejoin="round"><path d="m5 10 3.2 3.2L15 6.5" /></svg>
    <span className={styles.label}>{label}</span>
  </label>;
}
