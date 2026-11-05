import type { ComponentPropsWithRef } from "react";

import styles from "./Fields.module.css";

export type TextFieldProps = Omit<ComponentPropsWithRef<"input">, "children"> & { label: string };
export type SelectFieldProps = ComponentPropsWithRef<"select"> & { label: string };
export type TextAreaFieldProps = ComponentPropsWithRef<"textarea"> & { label: string };

export function TextField({ label, className = "", ...props }: TextFieldProps) {
  return <label className={styles.field}>
    <span>{label}</span>
    <input {...props} className={`${styles.control} ${className}`} />
  </label>;
}

export function SelectField({ label, className = "", children, ...props }: SelectFieldProps) {
  return <label className={styles.field}>
    <span>{label}</span>
    <select {...props} className={`${styles.control} ${className}`}>{children}</select>
  </label>;
}

export function TextAreaField({ label, className = "", ...props }: TextAreaFieldProps) {
  return <label className={styles.field}>
    <span>{label}</span>
    <textarea {...props} className={`${styles.control} ${className}`} />
  </label>;
}
