"use client";

import { useSyncExternalStore } from "react";
import { subscribeTheme } from "@/shared/ui/theme";
import styles from "./Gallery.module.css";

export function ColorValue({ token }: { token: string }) {
  const value = useSyncExternalStore(subscribeTheme,
    () => getComputedStyle(document.documentElement).getPropertyValue(token).trim().toUpperCase(),
    () => "");
  return <code className={styles.hex}>{value || "—"}</code>;
}
