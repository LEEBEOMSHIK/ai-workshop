import type {ReactNode} from "react";
import {ApplicationShell} from "./ApplicationShell";
export function PublicNavigation({children,immersive,onMenuOpenChange}:{children?:ReactNode;immersive?:boolean;onMenuOpenChange?:(open:boolean)=>void}){return <ApplicationShell area="public" immersive={immersive} onMenuOpenChange={onMenuOpenChange}>{children}</ApplicationShell>;}
