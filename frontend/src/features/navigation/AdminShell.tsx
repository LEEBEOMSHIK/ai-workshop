import type {ReactNode} from "react";
import type {SessionUser} from "../identity/session";
import {ApplicationShell} from "./ApplicationShell";
export {APPLICATION_MOBILE_QUERY as ADMIN_MOBILE_QUERY} from "./ApplicationShell";
export function AdminShell({user,children}:{user:SessionUser;children?:ReactNode}){return <ApplicationShell area="admin" user={user}>{children}</ApplicationShell>;}
