import { createBrowserRouter, type RouteObject } from "react-router-dom";

import { LoginPage } from "../platform/identity/LoginPage";
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
];

export const router = createBrowserRouter(routes);
