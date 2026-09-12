using System;
using System.Collections.Generic;
using System.Runtime.InteropServices;
namespace Workshop.Isolation {
internal sealed class LaunchAttributes : IDisposable {
    private readonly List<IntPtr> allocations=new List<IntPtr>();
    public IntPtr Pointer { get; private set; }
    public LaunchAttributes() {
        IntPtr size=IntPtr.Zero;
        Native.InitializeProcThreadAttributeList(IntPtr.Zero,4,0,ref size);
        if(size==IntPtr.Zero || size.ToInt64()>65536) throw new ProbeException("attribute_size_failed");
        Pointer=Marshal.AllocHGlobal(size);
        if(!Native.InitializeProcThreadAttributeList(Pointer,4,0,ref size)) { Marshal.FreeHGlobal(Pointer); Pointer=IntPtr.Zero; throw new ProbeException("attribute_init_failed"); }
    }
    private void Put(long key,IntPtr memory,int size) {
        allocations.Add(memory);
        if(!Native.UpdateProcThreadAttribute(Pointer,0,new IntPtr(key),memory,new IntPtr(size),IntPtr.Zero,IntPtr.Zero)) throw new ProbeException("attribute_update_"+Marshal.GetLastWin32Error());
    }
    public void Configure(IntPtr sid,IntPtr input,IntPtr output) {
        Native.SECURITY_CAPABILITIES caps=new Native.SECURITY_CAPABILITIES(); caps.AppContainerSid=sid;
        IntPtr c=Marshal.AllocHGlobal(Marshal.SizeOf(caps)); Marshal.StructureToPtr(caps,c,false);
        Put(Native.PROC_THREAD_ATTRIBUTE_SECURITY_CAPABILITIES,c,Marshal.SizeOf(caps));
        IntPtr opt=Marshal.AllocHGlobal(4); Marshal.WriteInt32(opt,Native.PROCESS_CREATION_ALL_APPLICATION_PACKAGES_OPT_OUT);
        Put(Native.PROC_THREAD_ATTRIBUTE_ALL_APPLICATION_PACKAGES_POLICY,opt,4);
        IntPtr child=Marshal.AllocHGlobal(4); Marshal.WriteInt32(child,Native.PROCESS_CREATION_CHILD_PROCESS_RESTRICTED);
        Put(Native.PROC_THREAD_ATTRIBUTE_CHILD_PROCESS_POLICY,child,4);
        IntPtr handles=Marshal.AllocHGlobal(IntPtr.Size*2); Marshal.WriteIntPtr(handles,input); Marshal.WriteIntPtr(handles,IntPtr.Size,output);
        Put(Native.PROC_THREAD_ATTRIBUTE_HANDLE_LIST,handles,IntPtr.Size*2);
    }
    public void Dispose() {
        if(Pointer!=IntPtr.Zero) { Native.DeleteProcThreadAttributeList(Pointer); Marshal.FreeHGlobal(Pointer); Pointer=IntPtr.Zero; }
        foreach(IntPtr p in allocations) Marshal.FreeHGlobal(p); allocations.Clear();
    }
}
internal static class LaunchVerification {
    private static IntPtr TokenField(IntPtr token,int field) {
        int size;
        Native.GetTokenInformation(token,field,IntPtr.Zero,0,out size);
        if(size<4 || size>65536) throw new ProbeException("token_query_size_failed");
        IntPtr data=Marshal.AllocHGlobal(size);
        if(!Native.GetTokenInformation(token,field,data,size,out size)) { Marshal.FreeHGlobal(data); throw new ProbeException("token_query_"+Marshal.GetLastWin32Error()); }
        return data;
    }
    public static void Verify(IntPtr process,IntPtr sid,IntPtr job) {
        bool inJob;
        if(!Native.IsProcessInJob(process,job,out inJob) || !inJob) throw new ProbeException("job_membership_failed");
        IntPtr token;
        if(!Native.OpenProcessToken(process,Native.TOKEN_QUERY,out token)) throw new ProbeException("token_open_failed");
        try {
            foreach(int field in new int[]{Native.TokenIsAppContainer,Native.TokenIsLessPrivilegedAppContainer}) {
                IntPtr p=TokenField(token,field);
                try { if(Marshal.ReadInt32(p)!=1) throw new ProbeException("token_boundary_mismatch"); } finally {Marshal.FreeHGlobal(p);}
            }
            IntPtr package=TokenField(token,Native.TokenAppContainerSid);
            try { if(!Native.EqualSid(Marshal.ReadIntPtr(package),sid)) throw new ProbeException("package_sid_mismatch"); } finally {Marshal.FreeHGlobal(package);}
            IntPtr caps=TokenField(token,Native.TokenCapabilities);
            try { if(Marshal.ReadInt32(caps)!=0) throw new ProbeException("unexpected_capabilities"); } finally {Marshal.FreeHGlobal(caps);}
        } finally {Native.CloseHandle(token);}
        uint policy;
        if(!Native.GetProcessMitigationPolicy(process,Native.ProcessChildProcessPolicy,out policy,4) || (policy&1)!=1 || (policy&4)!=0) throw new ProbeException("child_policy_mismatch");
    }
}
}
