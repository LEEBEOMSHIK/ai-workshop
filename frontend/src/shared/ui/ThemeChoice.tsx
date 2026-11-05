"use client";

import { useId, useSyncExternalStore } from "react";
import { chooseTheme, currentTheme, subscribeTheme } from "./theme";
import styles from "./ThemeChoice.module.css";

const options = [{ value: "light", label: "라이트" }, { value: "dark", label: "다크" }] as const;

export function ThemeChoice() {
  const theme = useSyncExternalStore(subscribeTheme, currentTheme, () => "dark" as const);
  const name = useId();
  return <fieldset className={styles.field}>
    <legend>화면 모드</legend>
    <div className={styles.choices}>{options.map(({ value, label }) =>
      <label className={styles.option} key={value}>
        <input type="radio" name={name} checked={theme === value} onChange={() => chooseTheme(value)} />
        <span>{label}</span>
      </label>
    )}</div>
  </fieldset>;
}
