import { createBrowserRouter, type RouteObject } from "react-router-dom";

import { LoginPage } from "../platform/identity/LoginPage";
import { WorkspacePage } from "../platform/workspaces/WorkspacePage";
import { App } from "./App";

export const routes: RouteObject[] = [
  {
    path: "/",
    element: <App />,
  },
  {
    path: "/login",
    element: <LoginPage />,
  },
  {
    path: "/workspaces",
    element: <WorkspacePage />,
  },
];

export const router = createBrowserRouter(routes);
