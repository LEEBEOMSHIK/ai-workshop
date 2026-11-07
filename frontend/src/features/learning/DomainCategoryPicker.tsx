"use client";

import { useId, useState } from "react";
import { Button } from "../../shared/ui/Button";
import { CheckboxField } from "../../shared/ui/CheckboxField";
import { TextField } from "../../shared/ui/Fields";
import styles from "./DomainCategoryPicker.module.css";

interface DomainCategoryPickerProps {
  value: string[];
  onChange: (value: string[]) => void;
  disabled?: boolean;
}

export function DomainCategoryPicker({ value, onChange, disabled = false }: DomainCategoryPickerProps) {
  const helpId = useId();
  const [added, setAdded] = useState<string[]>(() => [...value]);
  const [text, setText] = useState("");
  const [announcement, setAnnouncement] = useState("");
  const options = [...new Set([...added, ...value])];
  const candidate = text.trim();

  const add = () => {
    if (disabled || !candidate) return;
    setAdded((previous) => previous.includes(candidate) ? previous : [...previous, candidate]);
    if (!value.includes(candidate)) onChange([...value, candidate]);
    setAnnouncement(`${candidate} 분야가 선택되었습니다.`);
    setText("");
  };

  return <fieldset className={styles.picker} disabled={disabled} aria-describedby={helpId}>
    <legend>업무 분야</legend>
    <p id={helpId} className={styles.help}>업무 분야를 추가하면 카테고리로 선택할 수 있습니다. 여러 분야를 선택할 수 있습니다.</p>
    {options.length > 0 && <div className={styles.choices}>
      {options.map((label) => <CheckboxField key={label} label={label} checked={value.includes(label)} onChange={(event) => {
        onChange(event.target.checked ? [...value, label] : value.filter((item) => item !== label));
      }} />)}
    </div>}
    <div className={styles.addRow}>
      <TextField label="새 업무 분야" value={text} placeholder="분야 이름을 하나씩 입력하세요" onChange={(event) => setText(event.target.value)} onKeyDown={(event) => {
        if (event.key === "Enter" && !event.nativeEvent.isComposing) {
          event.preventDefault();
          add();
        }
      }} />
      <Button disabled={disabled || !candidate} onClick={add}>분야 추가</Button>
    </div>
    <span className={styles.announcement} role="status">{announcement}</span>
  </fieldset>;
}
