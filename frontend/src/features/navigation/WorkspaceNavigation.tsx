import type {ReactNode} from "react";
import type {SessionUser} from "../identity/session";
import {ApplicationShell} from "./ApplicationShell";
export function WorkspaceNavigation({user,children}:{user:SessionUser;children?:ReactNode}){return <ApplicationShell area="workspace" user={user}>{children}</ApplicationShell>;}
