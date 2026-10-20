"use client";

import { useId } from "react";
import styles from "./ChoiceGroup.module.css";

export type ChoiceOption<Value extends string> = {
  value: Value;
  label: string;
  disabled?: boolean;
};

export type ChoiceGroupProps<Value extends string> = {
  legend: string;
  description?: string;
  options: readonly ChoiceOption<Value>[];
  value: Value;
  onChange: (value: Value) => void;
  disabled?: boolean;
  variant?: "default" | "segmented";
};

export function ChoiceGroup<Value extends string>({ legend, description, options, value, onChange, disabled = false, variant = "default" }: ChoiceGroupProps<Value>) {
  const id = useId();
  const descriptionId = description ? `${id}-description` : undefined;
  return <fieldset className={`${styles.group}${variant === "segmented" ? ` ${styles.segmented}` : ""}`} disabled={disabled} aria-describedby={descriptionId}>
    <legend className={styles.legend}>{legend}</legend>
    {description ? <p id={descriptionId} className={styles.description}>{description}</p> : null}
    <div className={styles.choices}>
      {options.map(option => <label className={styles.choice} key={option.value}>
        <input className={styles.radio} type="radio" name={`${id}-choice`} value={option.value}
          checked={value === option.value} disabled={disabled || option.disabled}
          onChange={() => onChange(option.value)} />
        <span>{option.label}</span>
      </label>)}
    </div>
  </fieldset>;
}
