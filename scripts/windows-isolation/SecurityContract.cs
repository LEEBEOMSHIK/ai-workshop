using System;
using System.Security.AccessControl;
using System.Security.Principal;
namespace Workshop.Isolation {
internal static class SecurityContract {
    internal static bool PrivilegedHandlesDenied(uint createProcessError,uint vmWriteError) { return createProcessError==5 && vmWriteError==5; }
    internal static CommonAce OwnedAce(SecurityIdentifier sid,int rights) {return new CommonAce(AceFlags.None,AceQualifier.AccessAllowed,rights,sid,false,null);}
    private static bool SameAce(GenericAce a,GenericAce b) {
        byte[] first=new byte[a.BinaryLength],second=new byte[b.BinaryLength]; a.GetBinaryForm(first,0); b.GetBinaryForm(second,0);
        if(first.Length!=second.Length) return false;
        for(int i=0;i<first.Length;i++) if(first[i]!=second[i]) return false;
        return true;
    }
    internal static void AddOwnedAce(RawAcl acl,CommonAce owned) {
        if(acl==null) throw new ProbeException("null_dacl_rejected");
        int insertion=acl.Count;
        for(int i=0;i<acl.Count;i++) {
            KnownAce known=acl[i] as KnownAce;
            if(known!=null && known.SecurityIdentifier.Equals(owned.SecurityIdentifier)) throw new ProbeException("ace_not_fresh");
            if((acl[i].AceFlags & AceFlags.Inherited)!=0 && insertion==acl.Count) insertion=i;
        }
        acl.InsertAce(insertion,owned);
    }
    internal static void RemoveOwnedAce(RawAcl acl,CommonAce owned) {
        if(acl==null) throw new ProbeException("null_dacl_rejected");
        int index=-1;
        for(int i=0;i<acl.Count;i++) {
            KnownAce known=acl[i] as KnownAce;
            if(known==null || !known.SecurityIdentifier.Equals(owned.SecurityIdentifier)) continue;
            if(index!=-1 || !SameAce(acl[i],owned)) throw new ProbeException("ace_changed_cleanup_blocked");
            index=i;
        }
        if(index>=0) acl.RemoveAce(index);
    }
    internal static bool IsLowNoWriteUp(RawSecurityDescriptor descriptor) {
        RawAcl acl=descriptor.SystemAcl;
        if(acl==null || acl.Count!=1) return false;
        // SYSTEM_MANDATORY_LABEL_ACE has the same binary SID layout as a CommonAce
        // but older .NET Framework exposes it as CustomAce; inspect its wire fields.
        byte[] bytes=new byte[acl[0].BinaryLength]; acl[0].GetBinaryForm(bytes,0);
        return bytes.Length==20 && bytes[0]==0x11 && bytes[1]==0 && BitConverter.ToInt32(bytes,4)==1 && new SecurityIdentifier(bytes,8).Value=="S-1-16-4096";
    }
}
}
