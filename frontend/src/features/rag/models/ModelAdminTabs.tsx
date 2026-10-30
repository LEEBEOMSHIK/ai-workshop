import { useEffect, useId, useRef, type ReactNode } from "react";
import styles from "./ModelAdmin.module.css";

const tabs = ["등록 현황", "모델 연결", "처리 설정", "데이터 정책"] as const;

export function ModelAdminTabs({ panels, selected, onSelect }: {
  panels: readonly [ReactNode, ReactNode, ReactNode, ReactNode]; selected: number; onSelect: (index: number) => void;
}) {
  const id = useId();
  const buttons = useRef<(HTMLButtonElement | null)[]>([]);
  const previousSelected = useRef(selected);
  useEffect(() => {
    if (previousSelected.current !== selected) buttons.current[selected]?.focus();
    previousSelected.current = selected;
  }, [selected]);
  return <>
    <div role="tablist" aria-label="모델 관리 작업" className={styles.tabs}>
      {tabs.map((label, index) => <button key={label} ref={(element) => { buttons.current[index] = element; }}
        type="button" role="tab" id={`${id}-tab-${index}`} aria-controls={`${id}-panel-${index}`}
        aria-selected={selected === index} tabIndex={selected === index ? 0 : -1}
        onClick={() => onSelect(index)} onKeyDown={(event) => {
          const next = event.key === "ArrowRight" ? (index + 1) % tabs.length
            : event.key === "ArrowLeft" ? (index + tabs.length - 1) % tabs.length
              : event.key === "Home" ? 0 : event.key === "End" ? tabs.length - 1 : null;
          if (next === null) return;
          event.preventDefault(); onSelect(next); buttons.current[next]?.focus();
        }}>{label}</button>)}
    </div>
    {panels.map((panel, index) => <section key={tabs[index]} className={styles.tabPanel}
      role="tabpanel" id={`${id}-panel-${index}`} aria-labelledby={`${id}-tab-${index}`}
      tabIndex={0} hidden={selected !== index}>{panel}</section>)}
  </>;
}
