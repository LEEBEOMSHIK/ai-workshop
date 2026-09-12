"use client";

import { useCallback, useEffect, useRef } from "react";

const warning = "저장하지 않은 변경이 있습니다. 이 페이지를 떠나시겠습니까?";

export function useUnsavedChanges(dirty: boolean) {
  const successfulNavigation = useRef(false);
  useEffect(() => {
    successfulNavigation.current = false;
    if (!dirty) return;

    const beforeUnload = (event: BeforeUnloadEvent) => {
      if (successfulNavigation.current) return;
      event.preventDefault();
      event.returnValue = warning;
    };
    const click = (event: MouseEvent) => {
      if (successfulNavigation.current) return;
      const target = event.target;
      if (!(target instanceof Element)) return;
      const link = target.closest("a[href]");
      if (!link || link.getAttribute("target") === "_blank") return;
      if (!window.confirm(warning)) event.preventDefault();
    };
    const popState = () => {
      if (successfulNavigation.current) return;
      if (!window.confirm(warning)) window.history.go(1);
    };

    window.addEventListener("beforeunload", beforeUnload);
    document.addEventListener("click", click, true);
    window.addEventListener("popstate", popState);
    return () => {
      window.removeEventListener("beforeunload", beforeUnload);
      document.removeEventListener("click", click, true);
      window.removeEventListener("popstate", popState);
    };
  }, [dirty]);

  return useCallback(() => {
    successfulNavigation.current = true;
  }, []);
}
