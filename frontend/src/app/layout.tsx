import type { Metadata } from "next";
import type { ReactNode } from "react";
import { themeBootstrap } from "../shared/ui/theme";

import "./styles.css";
import "./office-tailwind.css";

export const metadata: Metadata = {
  title: "AI Workshop",
  description: "AI 기술 관리자와 실제 기능, 설계와 해결 과정을 탐색하는 AI 작업소",
};

export default function RootLayout({ children }: Readonly<{ children: ReactNode }>) {
  return (
    <html lang="ko" suppressHydrationWarning>
      <head><script dangerouslySetInnerHTML={{ __html: themeBootstrap }} /></head>
      <body>{children}</body>
    </html>
  );
}
