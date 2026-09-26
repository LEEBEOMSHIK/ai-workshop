import type {ReactNode} from "react";
import type {SessionUser} from "../identity/session";
import {ApplicationShell} from "./ApplicationShell";
import type {Area} from "./areaMenus";
export function AreaNavigation({area,user,children}:{area:Area;user?:SessionUser;children?:ReactNode}){return <ApplicationShell area={area} user={user}>{children}</ApplicationShell>;}
