using System;
using System.IO;
using System.Collections.Generic;
using System.Runtime.InteropServices;
using System.Security.AccessControl;
using System.Security.Principal;
namespace Workshop.Isolation {
internal sealed class SecurityScope : IDisposable {
    private const uint DaclInformation=4, LabelInformation=0x10;
    private readonly OwnedChanges changes=new OwnedChanges();
    private readonly List<KeyValuePair<string,Native.FILE_INFORMATION>> pinnedPaths=new List<KeyValuePair<string,Native.FILE_INFORMATION>>();
    public string Root { get; private set; }
    public string Profile { get; private set; }
    public string Executable { get; private set; }
    public string Scratch { get; private set; }
    public string Protected { get; private set; }
    public IntPtr Sid { get; private set; }
    public bool CleanupFailed { get { return changes.CleanupFailed; } }
    public SecurityScope(string root,string id) { Root=Contract.Child(root,"run-"+id); Profile="AIWorkshop.Isolation."+id; }
    public void Prepare(string source,string hash) {
        // No SHARE_DELETE: pin existing ancestor directory entries before mutation.
        string ancestor=Path.GetDirectoryName(Root);
        while(!String.IsNullOrEmpty(ancestor)) {Pin(ancestor,true,0); ancestor=Path.GetDirectoryName(ancestor);}
        VerifyPinnedPaths();
        Contract.Canonical(Root);
        if(!Native.CreateDirectoryW(Root,IntPtr.Zero)) throw new ProbeException("run_directory_not_fresh");
        IntPtr directory=Pin(Root,true,0x60000); // READ_CONTROL | WRITE_DAC
        FileStream owner=new FileStream(Path.Combine(Root,"owner.lock"),FileMode.CreateNew,FileAccess.ReadWrite,FileShare.None);
        changes.Add(owner.Dispose);
        Executable=Path.Combine(Root,"Canary.exe");
        using(FileStream input=new FileStream(source,FileMode.Open,FileAccess.Read,FileShare.Read))
        using(FileStream output=new FileStream(Executable,FileMode.CreateNew,FileAccess.Write,FileShare.None)) input.CopyTo(output);
        FileStream exeLock=new FileStream(Executable,FileMode.Open,FileAccess.Read,FileShare.Read);
        changes.Add(exeLock.Dispose); Contract.VerifyHash(Executable,hash);
        IntPtr executable=Pin(Executable,false,0x60000);
        Scratch=Path.Combine(Root,"scratch.dat"); Protected=Path.Combine(Root,"protected.dat");
        using(FileStream f=new FileStream(Scratch,FileMode.CreateNew,FileAccess.Write,FileShare.None)) f.WriteByte(41);
        using(FileStream f=new FileStream(Protected,FileMode.CreateNew,FileAccess.Write,FileShare.None)) f.WriteByte(42);
        IntPtr scratch=Pin(Scratch,false,0xe0000); // READ_CONTROL | WRITE_DAC | WRITE_OWNER (label)
        Pin(Protected,false,0);
        VerifyPinnedPaths();
        IntPtr sid;
        int hr=Native.CreateAppContainerProfile(Profile,Profile,"Synthetic LPAC experiment",IntPtr.Zero,0,out sid);
        if(hr<0) throw new ProbeException("profile_create_"+unchecked((uint)hr));
        Sid=sid;
        changes.Add(delegate {
            if(changes.CleanupFailed) throw new ProbeException("profile_cleanup_blocked_by_prior_failure");
            if(Native.DeleteAppContainerProfile(Profile)<0) throw new ProbeException("profile_cleanup_failed");
        });
        Grant(directory,FileSystemRights.ReadAndExecute | FileSystemRights.Synchronize);
        Grant(executable,FileSystemRights.ReadAndExecute | FileSystemRights.Synchronize);
        Grant(scratch,FileSystemRights.Read | FileSystemRights.Write | FileSystemRights.Synchronize);
        LowIntegrity(scratch);
    }
    private IntPtr Pin(string path,bool directory,uint access) {
        Contract.Canonical(path);
        Native.SECURITY_ATTRIBUTES sa=new Native.SECURITY_ATTRIBUTES(); sa.Length=Marshal.SizeOf(sa);
        uint flags=0x00200000u | (directory?0x02000000u:0u); // OPEN_REPARSE_POINT | BACKUP_SEMANTICS
        IntPtr h=Native.CreateFileW(path,access,3,ref sa,Native.OPEN_EXISTING,flags,IntPtr.Zero);
        if(h==Native.INVALID_HANDLE_VALUE) throw new ProbeException("object_pin_"+Marshal.GetLastWin32Error());
        changes.Add(delegate {if(!Native.CloseHandle(h)) throw new ProbeException("object_close_failed");});
        Native.FILE_INFORMATION info;
        if(!Native.GetFileInformationByHandle(h,out info)) throw new ProbeException("object_identity_failed");
        Contract.CheckAttributes((FileAttributes)info.Attributes);
        if(directory!=((info.Attributes & (uint)FileAttributes.Directory)!=0)) throw new ProbeException("object_kind_mismatch");
        pinnedPaths.Add(new KeyValuePair<string,Native.FILE_INFORMATION>(path,info));
        return h;
    }
    private void VerifyPinnedPaths() {
        foreach(KeyValuePair<string,Native.FILE_INFORMATION> item in pinnedPaths) {
            Contract.Canonical(item.Key);
            Native.SECURITY_ATTRIBUTES sa=new Native.SECURITY_ATTRIBUTES(); sa.Length=Marshal.SizeOf(sa);
            IntPtr current=Native.CreateFileW(item.Key,0,3,ref sa,Native.OPEN_EXISTING,0x02200000,IntPtr.Zero);
            if(current==Native.INVALID_HANDLE_VALUE) throw new ProbeException("pinned_path_unavailable");
            try {
                Native.FILE_INFORMATION info;
                if(!Native.GetFileInformationByHandle(current,out info) || info.Volume!=item.Value.Volume || info.IndexHigh!=item.Value.IndexHigh || info.IndexLow!=item.Value.IndexLow) throw new ProbeException("pinned_path_identity_changed");
                Contract.CheckAttributes((FileAttributes)info.Attributes);
            } finally {Native.CloseHandle(current);}
        }
    }
    private static RawSecurityDescriptor ReadSecurity(IntPtr handle,uint information) {
        IntPtr owner,group,dacl,sacl,descriptor;
        uint code=Native.GetSecurityInfo(handle,1,information,out owner,out group,out dacl,out sacl,out descriptor);
        if(code!=0) throw new ProbeException("security_read_"+code);
        try {
            uint length=Native.GetSecurityDescriptorLength(descriptor);
            if(length==0 || length>65536) throw new ProbeException("security_descriptor_size");
            byte[] data=new byte[length]; Marshal.Copy(descriptor,data,0,data.Length); return new RawSecurityDescriptor(data,0);
        } finally {Native.LocalFree(descriptor);}
    }
    private static void WriteSecurity(IntPtr handle,uint information,RawSecurityDescriptor descriptor) {
        byte[] data=new byte[descriptor.BinaryLength]; descriptor.GetBinaryForm(data,0);
        IntPtr memory=Marshal.AllocHGlobal(data.Length);
        try {
            Marshal.Copy(data,0,memory,data.Length);
            bool present,defaulted; IntPtr acl;
            bool ok=information==DaclInformation ? Native.GetSecurityDescriptorDacl(memory,out present,out acl,out defaulted) : Native.GetSecurityDescriptorSacl(memory,out present,out acl,out defaulted);
            if(!ok) throw new ProbeException("security_descriptor_invalid");
            uint code=Native.SetSecurityInfo(handle,1,information,IntPtr.Zero,IntPtr.Zero,information==DaclInformation?acl:IntPtr.Zero,information==LabelInformation?acl:IntPtr.Zero);
            if(code!=0) throw new ProbeException("security_write_"+code);
        } finally {Marshal.FreeHGlobal(memory);}
    }
    private void Grant(IntPtr handle,FileSystemRights rights) {
        CommonAce ace=SecurityContract.OwnedAce(new SecurityIdentifier(Sid),(int)rights);
        RawSecurityDescriptor acl=ReadSecurity(handle,DaclInformation);
        SecurityContract.AddOwnedAce(acl.DiscretionaryAcl,ace);
        // Operate on the same pinned object, not a pathname that could be replaced.
        changes.Add(delegate {
            RawSecurityDescriptor current=ReadSecurity(handle,DaclInformation);
            SecurityContract.RemoveOwnedAce(current.DiscretionaryAcl,ace);
            WriteSecurity(handle,DaclInformation,current);
        });
        WriteSecurity(handle,DaclInformation,acl);
    }
    private void LowIntegrity(IntPtr handle) {
        RawSecurityDescriptor original=ReadSecurity(handle,LabelInformation);
        string originalLabel=original.GetSddlForm(AccessControlSections.Audit);
        RawSecurityDescriptor low=new RawSecurityDescriptor("S:(ML;;NW;;;LW)");
        changes.Add(delegate {
            RawSecurityDescriptor current=ReadSecurity(handle,LabelInformation);
            if(current.GetSddlForm(AccessControlSections.Audit)==originalLabel) return;
            if(!SecurityContract.IsLowNoWriteUp(current)) throw new ProbeException("scratch_label_changed_cleanup_blocked");
            WriteSecurity(handle,LabelInformation,original);
        });
        WriteSecurity(handle,LabelInformation,low);
        if(!SecurityContract.IsLowNoWriteUp(ReadSecurity(handle,LabelInformation))) throw new ProbeException("scratch_label_verification_failed");
    }
    public void Dispose() {
        changes.Dispose();
        if(Sid!=IntPtr.Zero) {Native.FreeSid(Sid); Sid=IntPtr.Zero;}
    }
}
}
