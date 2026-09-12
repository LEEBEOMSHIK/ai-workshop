import { useId, useRef, useState, type ReactNode } from "react";
import styles from "./ModelAdmin.module.css";

const tabs = ["현재 구성 확인", "모델·실행 환경 설정", "처리·검색·답변 구성", "데이터 사용 범위·승인", "연결 검사·사용 준비"] as const;

export function ModelAdminTabs({ panels }: { panels: readonly [ReactNode, ReactNode, ReactNode, ReactNode, ReactNode] }) {
  const [selected, setSelected] = useState(0);
  const id = useId();
  const buttons = useRef<(HTMLButtonElement | null)[]>([]);
  return <>
    <div role="tablist" aria-label="모델 관리 작업" className={styles.tabs}>
      {tabs.map((label, index) => <button key={label} ref={(element) => { buttons.current[index] = element; }}
        type="button" role="tab" id={`${id}-tab-${index}`} aria-controls={`${id}-panel-${index}`}
        aria-selected={selected === index} tabIndex={selected === index ? 0 : -1}
        onClick={() => setSelected(index)} onKeyDown={(event) => {
          const next = event.key === "ArrowRight" ? (index + 1) % tabs.length
            : event.key === "ArrowLeft" ? (index + tabs.length - 1) % tabs.length
              : event.key === "Home" ? 0 : event.key === "End" ? tabs.length - 1 : null;
          if (next === null) return;
          event.preventDefault(); setSelected(next); buttons.current[next]?.focus();
        }}>{label}</button>)}
    </div>
    {panels.map((panel, index) => <section key={tabs[index]} className={styles.tabPanel}
      role="tabpanel" id={`${id}-panel-${index}`} aria-labelledby={`${id}-tab-${index}`}
      tabIndex={0} hidden={selected !== index}>{panel}</section>)}
  </>;
}
