import type { ComponentPropsWithRef } from "react";
import Link from "next/link";
import styles from "./Button.module.css";

export type ButtonProps = ComponentPropsWithRef<"button"> & {
  variant?: "primary" | "secondary" | "quiet" | "danger";
};

export function Button({ variant = "secondary", type = "button", className = "", ...props }: ButtonProps) {
  return <button {...props} type={type} className={`${styles.button} ${styles[variant]} ${className}`} />;
}

type ButtonLinkProps = ComponentPropsWithRef<typeof Link> & { variant?: ButtonProps["variant"] };

export function ButtonLink({ variant = "secondary", className = "", ...props }: ButtonLinkProps) {
  return <Link {...props} className={`${styles.button} ${styles[variant]} ${className}`} />;
}
